"""
trace_analyzer.py
2段階・3段階パイプラインで精密3Dを生成する

Stage1: detect_lines_with_lengths() で線を検出 (line_detector.py)
Stage2: generate_clean_trace_png() で白紙に線だけのクリーントレース生成
        → analyze_trace_for_building() でGPT-4oが建物要素を分類
Stage3: building dict → generate_building_3d_html() で3D表示
"""

import base64
import io
import json
import math

from PIL import Image, ImageDraw, ImageFont


def generate_clean_trace_png(
    lines: list,
    scale_m_per_px: float,
    canvas_w: int = 900,
    min_length_m: float = 0.3,
    show_grid: bool = True,
) -> bytes:
    """
    検出した線リストを白紙に再描画したクリーンPNGを生成する。

    Parameters
    ----------
    lines          : detect_lines_with_lengths() の lines リスト
    scale_m_per_px : 1px = Xm のスケール係数
    canvas_w       : 出力画像の幅
    min_length_m   : この長さ未満は描画しない
    show_grid      : 1m単位グリッドを描画するか

    Returns
    -------
    PNG バイト列
    """
    draw_lines = [l for l in lines if l["real_m"] >= min_length_m]
    if not draw_lines:
        img = Image.new("RGB", (canvas_w, 400), "white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    # 元ピクセル座標のバウンディングボックス
    xs = [l["x1"] for l in draw_lines] + [l["x2"] for l in draw_lines]
    ys = [l["y1"] for l in draw_lines] + [l["y2"] for l in draw_lines]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    orig_w = max_x - min_x or 1
    orig_h = max_y - min_y or 1

    # スケーリング
    margin = 50
    draw_w = canvas_w - margin * 2
    draw_h = int(draw_w * orig_h / orig_w)
    canvas_h = draw_h + margin * 2

    def tx(x): return int(margin + (x - min_x) * draw_w / orig_w)
    def ty(y): return int(margin + (y - min_y) * draw_h / orig_h)

    # 白背景
    img = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # グリッド（1m刻み）
    if show_grid and scale_m_per_px > 0:
        step_px = 1.0 / scale_m_per_px  # 1m = Xpx（元画像空間）
        x = min_x
        while x <= max_x + step_px:
            sx = tx(x)
            draw.line([(sx, margin), (sx, margin + draw_h)], fill=(220, 235, 250), width=1)
            x += step_px
        y = min_y
        while y <= max_y + step_px:
            sy = ty(y)
            draw.line([(margin, sy), (margin + draw_w, sy)], fill=(220, 235, 250), width=1)
            y += step_px

    # フォント
    try:
        font    = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 11)
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
    except Exception:
        font = font_sm = ImageFont.load_default()

    # 色マップ
    def _color(real_m):
        if real_m >= 8.0:  return (0, 150, 50)
        if real_m >= 3.0:  return (210, 100, 0)
        if real_m >= 1.0:  return (30, 80, 220)
        return (160, 30, 160)

    # 線描画
    for ln in draw_lines:
        x1s, y1s = tx(ln["x1"]), ty(ln["y1"])
        x2s, y2s = tx(ln["x2"]), ty(ln["y2"])
        col = _color(ln["real_m"])
        lw = 3 if ln["real_m"] >= 3.0 else 2

        draw.line([(x1s, y1s), (x2s, y2s)], fill=col, width=lw)

        r = 3
        draw.ellipse([(x1s - r, y1s - r), (x1s + r, y1s + r)], fill=col)
        draw.ellipse([(x2s - r, y2s - r), (x2s + r, y2s + r)], fill=col)

        # ラベル（0.5m以上）
        if ln["real_m"] >= 0.5:
            mx = (x1s + x2s) // 2
            my = (y1s + y2s) // 2
            orient = "H" if ln["angle_deg"] < 10 else ("V" if ln["angle_deg"] > 80 else f"{ln['angle_deg']:.0f}°")
            label = f"{ln.get('id', '')} {ln['real_m']:.2f}m {orient}"
            try:
                bbox = draw.textbbox((mx, my - 12), label, font=font_sm)
                draw.rectangle([bbox[0] - 2, bbox[1] - 1, bbox[2] + 2, bbox[3] + 1],
                               fill=(255, 255, 255))
            except Exception:
                pass
            draw.text((mx, my - 12), label, fill=col, font=font_sm)

    # 凡例
    legend_y = canvas_h - 18
    draw.text((margin, legend_y), "■8m+ 緑  ■3m+ 橙  ■1m+ 青  ■1m未満 紫  │グリッド1マス=1m",
              fill=(100, 100, 100), font=font_sm)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()



def _filter_structural_lines(lines: list, img_w: int = 0, img_h: int = 0, 
                              min_m: float = 1.0, border_ratio: float = 0.03) -> list:
    """
    構造線のみを残すフィルタ。
    - 端点が画像端 border_ratio 以内の線（外枠線）を除外
    - min_m 未満の線を除外
    """
    bx = img_w * border_ratio if img_w else 0
    by = img_h * border_ratio if img_h else 0
    result = []
    for ln in lines:
        if ln['real_m'] < min_m:
            continue
        # 図面外枠チェック（両端が画像端に接している線）
        if img_w and img_h:
            x1, y1, x2, y2 = ln['x1'], ln['y1'], ln['x2'], ln['y2']
            near_left  = x1 < bx and x2 < bx
            near_right = x1 > img_w - bx and x2 > img_w - bx
            near_top   = y1 < by and y2 < by
            near_bottom = y1 > img_h - by and y2 > img_h - by
            if near_left or near_right or near_top or near_bottom:
                continue  # 外枠線を除外
        result.append(ln)
    return result


# ── GPT プロンプト ────────────────────────────────────────────

_SYSTEM = """あなたは建築図面を精密に読み取る専門家です。
提供されるのは建築立面図から自動検出した線分を白紙に再描画したトレース画像と、各線の実寸データです。
建物の3D構造を正確にJSONで返してください。JSONのみ・説明文不要。"""

_USER_TMPL = """## トレース画像の読み方

- **緑の線（8m以上）**: 外壁主要輪郭線
- **橙の線（3〜8m）**: 屋根ライン・床ライン・主要区画
- **青の線（1〜3m）**: 窓・ドア等の開口部
- **紫の線（1m未満）**: 細部
- ラベル例: `A1 9.10m H` = ブロックA1 / 実寸9.10m / 水平(H)
- グリッド1マス = 1m（青い薄いグリッド線）

## 上位{N}本の線データ

```json
{LINE_JSON}
```

## 返答JSON形式

```json
{{
  "building_type": "立面図 or 平面図",
  "note": "読み取り根拠（日本語で具体的に）",
  "dimensions": {{
    "total_width": 最長水平線の実寸(m),
    "total_depth": 幅×0.8(m)（立面図のみの場合）,
    "eave_height": 軒高(m),
    "ridge_height": 棟高(m)
  }},
  "walls": [
    {{"label":"南壁","x":0,"y":0,"z":0,"width":幅,"height":軒高,"depth":0.2}},
    {{"label":"北壁","x":0,"y":奥行き,"z":0,"width":幅,"height":軒高,"depth":0.2}},
    {{"label":"西壁","x":0,"y":0,"z":0,"width":0.2,"height":軒高,"depth":奥行き}},
    {{"label":"東壁","x":幅,"y":0,"z":0,"width":0.2,"height":軒高,"depth":奥行き}}
  ],
  "roof": {{
    "type": "切妻 or 寄棟 or 片流れ or 陸屋根",
    "eave_height": 数値,
    "ridge_height": 数値
  }},
  "openings": [
    {{
      "type": "窓 or ドア or 玄関",
      "x": 建物左端からの水平距離(m),
      "y": 0,
      "z": 床面からの高さ(m),
      "width": 開口幅(m),
      "height": 開口高さ(m)
    }}
  ],
  "floors": [
    {{"label":"基礎","x":0,"y":0,"z":-0.3,"width":幅,"depth":奥行き,"height":0.3}}
  ],
  "floor_footprints": [
    {{
      "floor": 1,
      "width": 1階の幅(m),
      "depth": null,
      "x_offset": 0,
      "z_offset": 0,
      "floor_height": 1階の高さ(m)
    }},
    {{
      "floor": 2,
      "width": 2階の幅(m)（セットバックがある場合のみ）,
      "depth": null,
      "x_offset": 左端からのオフセット(m),
      "z_offset": 0,
      "floor_height": 2階の高さ(m)
    }}
  ]
}}
```

## 厳守ルール
- 実寸は**必ずラベルの数値を使う**（例: `A1 9.10m H` → 幅9.10m）
- **最長線が画像全体を横断する（幅の95%以上）場合は図面外枠→無視すること**
- 建物の幅（水平）: 複数の同じ長さの水平線が上下に並んでいる長さ
- 建物の軒高（垂直）: **必ず2.5m〜8.0mの範囲**（住宅の物理的制約）
  - 平屋: 2.5〜3.5m / 2階建て: 4.5〜6.5m / 3階建て: 7.0〜8.0m
  - この範囲外の垂直線長は外枠・寸法線なので建物高さに使わないこと
- 青い水平線が縦にグループ化している領域 → 窓の候補
- openings の z = 床面からの高さ（1階腰窓=0.9、掃出窓=0、ドア=0、2階窓=3.5）
- floors の color フィールドは省略
- walls は南北東西の4面を必ず記述
- **floor_footprints**: 1階と2階で幅が異なる場合（セットバック）は必ず2要素を記述
  - 1階幅と2階幅が同じ or 平屋 → floor_footprints は空配列 `[]` で返す
  - セットバックあり（2階が1階より狭い）→ 両フロアを記述する
  - x_offset: 2階が左端から何m内側に入るか。例: 1階10m、2階8m、中央揃え → x_offset=1.0
  - floor_height: 各階の高さ（一般的住宅: 2.6〜3.2m）
  - depth は null でよい（3Dジェネレーターが建物奥行から自動補完する）
- JSONのみ返すこと（説明文不要）"""


def analyze_trace_for_building(
    clean_png_bytes: bytes,
    lines: list,
    scale_m_per_px: float,
    api_key: str,
    top_n: int = 60,
) -> dict:
    """
    クリーントレース画像 + 線データをGPT-4oに送り建物要素を分類する。

    Parameters
    ----------
    clean_png_bytes : generate_clean_trace_png() の出力
    lines           : detect_lines_with_lengths() の lines
    scale_m_per_px  : スケール係数
    api_key         : OpenAI API キー
    top_n           : GPTに渡す上位線数

    Returns
    -------
    building dict（generate_building_3d_html()に渡せる形式）
    エラー時: {"error": "...", "_raw_gpt_response": "..."}
    """
    raw_text = ""
    try:
        from openai import OpenAI
        from core.logger import log_gpt_call, log_error
        client = OpenAI(api_key=api_key)

        # 構造線のみにフィルタリング（外枠除外 + min 1.0m以上）
        # img_w/img_h を lines の座標から推定
        all_xs = [l['x1'] for l in lines] + [l['x2'] for l in lines]
        all_ys = [l['y1'] for l in lines] + [l['y2'] for l in lines]
        _img_w = max(all_xs) if all_xs else 0
        _img_h = max(all_ys) if all_ys else 0
        structural = _filter_structural_lines(lines, img_w=_img_w, img_h=_img_h, min_m=1.0)
        if len(structural) < 5:  # フィルタ過多の場合はフォールバック
            structural = [l for l in lines if l['real_m'] >= 0.5]
        # 上位N本（実寸降順）の線データ
        key_lines = sorted(structural, key=lambda x: x["real_m"], reverse=True)[:top_n]
        lines_data = [
            {
                "id": l.get("id", ""),
                "real_m": l["real_m"],
                "orientation": l["orientation"],
                "angle_deg": round(l["angle_deg"], 1),
            }
            for l in key_lines
        ]

        user_msg = _USER_TMPL.replace("{N}", str(len(lines_data))) \
                              .replace("{LINE_JSON}", json.dumps(lines_data, ensure_ascii=False, indent=2))

        b64 = base64.b64encode(clean_png_bytes).decode("utf-8")

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": _SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_msg},
                        {"type": "image_url", "image_url": {
                            "url": f"data:image/png;base64,{b64}",
                            "detail": "high",
                        }},
                    ],
                },
            ],
            max_tokens=3000,
            temperature=0.1,
        )

        finish_reason = response.choices[0].finish_reason
        raw_text = response.choices[0].message.content.strip()
        _raw_log = raw_text

        # ログ記録
        log_gpt_call(
            func_name="trace_analyzer.analyze_trace_for_building",
            model="gpt-4o",
            system_prompt=_SYSTEM[:200],
            user_message_summary=f"線データ{len(lines_data)}本 + クリーントレース画像",
            response_text=raw_text,
            tokens_prompt=response.usage.prompt_tokens if response.usage else None,
            tokens_completion=response.usage.completion_tokens if response.usage else None,
            tokens_total=response.usage.total_tokens if response.usage else None,
        )

        # 空レスポンスガード
        if not raw_text:
            return {"error": f"GPTが空レスポンスを返しました (finish_reason={finish_reason})", "_raw_gpt_response": ""}

        # マークダウンコードブロック除去
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]

        result = json.loads(raw_text.strip())
        result["_raw_gpt_response"] = _raw_log
        result["_pipeline"] = "trace_v2"  # どのパイプラインで生成したか識別
        return result

    except json.JSONDecodeError as e:
        log_error("JSONパースエラー: trace_analyzer.analyze_trace_for_building", e, "GPT")
        return {"error": f"JSONパースエラー: {e}", "_raw_gpt_response": raw_text}
    except Exception as e:
        log_error("エラー: trace_analyzer.analyze_trace_for_building", e, "GPT")
        return {"error": str(e), "_raw_gpt_response": raw_text}



# ═══════════════════════════════════════════════════════════════════════
# 多段階精密解析パイプライン v2（Stage 1〜N、大幅増強版）
#
# 考え方: 一度に多くを聞かない。各GPT呼び出しは「1つの質問」だけ。
#   Stage 1 : 各面（南/北/東/西）の画像内位置をratioで特定
#   Stage 2a: 各面の建物外形（left/right/ground/eave）をpixel ratioで特定
#   Stage 2b: 各面の寸法数値を読む（幅・軒高・棟高）
#   Stage 2c: 各面の1F/2F境界線の位置をratioで特定
#   Stage 2d: 各面のセットバック（凸凹）を検出
#   Stage 3a: 各面・1Fの窓数をカウント
#   Stage 3b: 各面・1Fの各窓の位置とサイズをpixel ratioで取得
#   Stage 3c: 各面・2Fの窓数をカウント
#   Stage 3d: 各面・2Fの各窓の位置とサイズをpixel ratioで取得
#   Stage 3e: 各面のドア・玄関を検出
#   Stage 4 : 屋根タイプを判定（南面）
#   Stage 5 : 全データを3Dデータに組み立て
# ═══════════════════════════════════════════════════════════════════════

_SYS = "あなたは建築図面の精密解析専門家です。JSONのみ返してください。説明文・コードブロック不要。"


def _gpt_json(client, user_text: str, img_bytes: bytes, max_tokens: int = 300) -> tuple:
    """GPT-4o Vision→JSONパース共通ヘルパー。(parsed, usage)を返す。"""
    b64 = base64.b64encode(img_bytes).decode("utf-8")
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": _SYS},
            {"role": "user", "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"}},
            ]},
        ],
        max_tokens=max_tokens,
        temperature=0.05,
    )
    raw = resp.choices[0].message.content.strip()
    # ① コードブロック除去
    if "```" in raw:
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"): raw = raw[4:]
        raw = raw.strip()
    # ② コードブロックがなくても { or [ の位置からJSONを抽出（フォールバック）
    if not raw.startswith(("{", "[")):
        for start_ch, end_ch in [('{', '}'), ('[', ']')]:
            si = raw.find(start_ch)
            if si != -1:
                ei = raw.rfind(end_ch)
                if ei > si:
                    raw = raw[si:ei+1]
                    break
    return json.loads(raw.strip()), resp.usage


def _crop_r(img_bytes: bytes, x1: float, y1: float, x2: float, y2: float, pad: float = 0.01) -> bytes:
    """0〜1 ratio でクロップ。pad=余白比率。失敗時は元画像を返す。"""
    from PIL import Image
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    iw, ih = img.size
    lx = max(0, int((x1 - pad) * iw))
    ly = max(0, int((y1 - pad) * ih))
    rx = min(iw, int((x2 + pad) * iw))
    ry = min(ih, int((y2 + pad) * ih))
    if rx - lx < 30 or ry - ly < 30:
        return img_bytes
    cropped = img.crop((lx, ly, rx, ry))
    buf = io.BytesIO()
    cropped.save(buf, format="PNG")
    return buf.getvalue()


# ── Stage 1: 各面の位置特定 ──────────────────────────────────────────

def ms_stage1_layout(img_bytes: bytes, api_key: str) -> dict:
    """
    Stage 1: 図面内の南/北/東/西 立面図のbounding boxを0〜1 ratioで返す。
    返値: {"south": {"x1":f,"y1":f,"x2":f,"y2":f}, "north":..., "east":..., "west":...}
    見つからない面はnull。
    """
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    q = """この建築図面に 南立面図・北立面図・東立面図・西立面図 が配置されています。
各立面図のラベル文字（「南立面図」「北立面図」等）を読んで、
それぞれの領域を画像全体に対する割合（0.0〜1.0）で返してください。
見つからない面はnullを返す。

```json
{"south":{"x1":0.0,"y1":0.0,"x2":0.5,"y2":0.5},"north":{"x1":0.5,"y1":0.0,"x2":1.0,"y2":0.5},"east":{"x1":0.0,"y1":0.5,"x2":0.5,"y2":1.0},"west":{"x1":0.5,"y1":0.5,"x2":1.0,"y2":1.0}}
```"""
    result, _ = _gpt_json(client, q, img_bytes, max_tokens=400)
    return result


# ── Stage 2a: 建物外形のpixel ratio特定 ──────────────────────────────

def ms_stage2a_bounds(face_img: bytes, face_label: str, api_key: str) -> dict:
    """
    Stage 2a: クロップ済み立面図内で、建物の外形（輪郭）を
    画像に対する0〜1 ratioで特定する。
    寸法線・タイトル文字・外枠は除外すること。
    返値: {"left":f, "right":f, "ground":f, "eave":f}
    """
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    q = f"""これは{face_label}の切り抜き画像です。
建物本体の外形輪郭（外壁の一番外の線）を、この画像全体に対する0〜1の割合で特定してください。
寸法線・タイトル文字・図面外枠は含めないこと。

返却フォーマット:
```json
{{"left": 0.08, "right": 0.92, "ground": 0.78, "eave": 0.18}}
```

left: 建物左端（画像幅に対する割合）
right: 建物右端
ground: 地面ライン（画像高さに対する割合、下が大きい値）
eave: 軒先ライン（屋根の出始め、上が小さい値）"""
    result, _ = _gpt_json(client, q, face_img, max_tokens=150)
    return result


# ── Stage 2b: 寸法数値を読む ─────────────────────────────────────────

def ms_stage2b_dims(face_img: bytes, face_label: str, api_key: str) -> dict:
    """
    Stage 2b: 立面図の寸法線に書かれた数値を読む。
    返値: {"width_m": float|None, "eave_height_m": float|None, "ridge_height_m": float|None}
    """
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    q = f"""これは{face_label}です。
図面内の寸法線（←→ や |..| で示された数値）を読み取ってください。

- width_m: 建物の幅（水平の寸法、m単位）
- eave_height_m: 軒高（地面から軒先、m単位）  
- ridge_height_m: 棟高（地面から棟頂点、m単位）

読み取れない項目はnull。住宅の合理的な範囲外（幅>30m、軒高>10m）はnull。

```json
{{"width_m": 12.9, "eave_height_m": 6.5, "ridge_height_m": 8.693}}
```"""
    result, _ = _gpt_json(client, q, face_img, max_tokens=150)
    return result


# ── Stage 2c: 1F/2F境界線の検出 ──────────────────────────────────────

def ms_stage2c_floor_line(face_img: bytes, face_label: str, api_key: str) -> dict:
    """
    Stage 2c: 立面図内の1F/2F境界（1F天井＝2F床）の水平線を
    画像高さに対する0〜1 ratioで返す。
    平屋や1階建てならnull。
    返値: {"has_second_floor": bool, "floor2_start_y_ratio": float|None}
    floor2_start_y_ratio: 0=上端, 1=下端。2階の始まりを示す。
    """
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    q = f"""これは{face_label}です。
建物が2階建ての場合、1F天井と2F床の境界を示す水平線はありますか？

```json
{{"has_second_floor": true, "floor2_start_y_ratio": 0.55}}
```

floor2_start_y_ratio は画像上端=0, 下端=1 の割合で境界線の位置を示します。
平屋・1階建てなら `{{"has_second_floor": false, "floor2_start_y_ratio": null}}`"""
    result, _ = _gpt_json(client, q, face_img, max_tokens=100)
    return result


# ── Stage 2d: セットバック（凸凹）検出 ───────────────────────────────

def ms_stage2d_setback(face_img: bytes, face_label: str, api_key: str) -> dict:
    """
    Stage 2d: 立面図で1Fより2Fが狭い（凸凹形状）かを検出。
    返値: {
      "has_setback": bool,
      "f1_left_ratio": float,   # 1Fの左端（0〜1）
      "f1_right_ratio": float,  # 1Fの右端
      "f2_left_ratio": float,   # 2Fの左端（1Fより大きい値なら右にセットバック）
      "f2_right_ratio": float   # 2Fの右端
    }
    """
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    q = f"""これは{face_label}です。
1階と2階を比べたとき、形が凸凹（2階が1階より狭い・オフセットがある）していますか？

例: 1階が幅いっぱいで、2階が少し内側に収まっている → セットバックあり

```json
{{"has_setback": true, "f1_left_ratio": 0.0, "f1_right_ratio": 1.0, "f2_left_ratio": 0.05, "f2_right_ratio": 0.90}}
```

has_setback=falseなら全て0〜1のデフォルト値でよい。
値は建物外形内での相対割合（建物左端=0、右端=1）で表す。"""
    result, _ = _gpt_json(client, q, face_img, max_tokens=150)
    return result


# ── Stage 3a/3c: 各階の窓数カウント ──────────────────────────────────

def ms_stage3_count_openings(face_img: bytes, face_label: str, floor_num: int, api_key: str) -> dict:
    """
    Stage 3a/3c: 指定階の窓・ドアの数をカウントする。
    floor_num: 1 or 2
    返値: {"window_count": int, "door_count": int}
    """
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    q = f"""これは{face_label}です。
{floor_num}階部分に見える「窓」と「ドア・玄関」をそれぞれ数えてください。

```json
{{"window_count": 3, "door_count": 1}}
```

窓: 壁に開いた矩形の開口（格子・ガラス面として表現）
ドア: 地面から続く背の高い開口"""
    result, _ = _gpt_json(client, q, face_img, max_tokens=80)
    return result


# ── Stage 3b/3d: 各開口のpixel ratio位置取得 ─────────────────────────

def ms_stage3_opening_positions(
    face_img: bytes, face_label: str, floor_num: int,
    opening_type: str, count: int,
    width_m: float, floor_height_m: float, api_key: str,
) -> list:
    """
    Stage 3b/3d: {floor_num}階の{opening_type}を1つずつ位置取得。
    返値: [{"x_ratio": f, "z_ratio": f, "w_ratio": f, "h_ratio": f}, ...]
    すべて建物外形内の0〜1 ratio（x=左端0,右端1 / z=地面0,軒高1）
    """
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    q = f"""これは{face_label}です。
{floor_num}階に{count}個の{opening_type}があります。
左から順番に各{opening_type}の位置を答えてください。

座標は建物全体の外形に対する0〜1の割合で表してください:
- x_ratio: 建物左端=0、右端=1（水平位置・開口中心）
- z_ratio: 地面=0、軒高=1（垂直位置・開口中心）
- w_ratio: 建物幅に対する開口幅の割合（例:幅1.6m÷建物幅12.9m=0.124）
- h_ratio: 建物軒高に対する開口高さの割合

参考: 建物幅={width_m}m / 対象階高={floor_height_m}m

```json
[{{"x_ratio":0.15,"z_ratio":0.25,"w_ratio":0.12,"h_ratio":0.18}}]
```"""
    result, _ = _gpt_json(client, q, face_img, max_tokens=400)
    return result if isinstance(result, list) else []


# ── Stage 4: 屋根タイプ判定 ───────────────────────────────────────────

def ms_stage4_roof_type(south_img: bytes, api_key: str) -> str:
    """Stage 4: 南面から屋根タイプを判定する。"""
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    q = """この南立面図の屋根の形状を判定してください。

切妻: 正面から三角形に見える（ガーブル）
寄棟: 正面から台形に見える（ヒップ）
片流れ: 一方向だけ傾斜
陸屋根: 平ら

```json
{"roof_type": "切妻"}
```"""
    try:
        result, _ = _gpt_json(client, q, south_img, max_tokens=60)
        return result.get("roof_type", "寄棟")
    except Exception:
        return "寄棟"


# ── Stage 5: 3Dデータ組み立て ─────────────────────────────────────────

def ms_stage5_assemble(
    layout: dict,
    face_bounds: dict,       # {face: {left,right,ground,eave}}
    face_dims: dict,         # {face: {width_m, eave_height_m, ridge_height_m}}
    face_floor_lines: dict,  # {face: {has_second_floor, floor2_start_y_ratio}}
    face_setbacks: dict,     # {face: {has_setback, f1_*, f2_*}}
    face_openings_raw: dict, # {face: {"1F_窓":[ratio_list], "1F_ドア":[...], "2F_窓":[...], ...}}
    roof_type: str,
) -> dict:
    """
    Stage 5: 各面のすべての解析結果を3Dデータに変換する。
    pixel ratioをメートル値に変換して返す。
    """
    # 南面優先で基準寸法を決定
    s_dim = face_dims.get("south") or {}
    e_dim = face_dims.get("east")  or {}
    w_dim = face_dims.get("west")  or {}

    total_width  = float(s_dim.get("width_m") or
                         max((v.get("width_m") or 0 for v in face_dims.values()), default=10.0))
    eave_height  = float(s_dim.get("eave_height_m") or
                         next((v.get("eave_height_m") for v in face_dims.values() if v.get("eave_height_m")), 6.0))
    ridge_height = float(s_dim.get("ridge_height_m") or
                         next((v.get("ridge_height_m") for v in face_dims.values() if v.get("ridge_height_m")), eave_height + 1.5))
    total_depth  = float(e_dim.get("width_m") or w_dim.get("width_m") or round(total_width * 0.72, 2))

    # 南面のfloor_line から1F高さを計算
    s_fl = face_floor_lines.get("south") or {}
    floor2_y = s_fl.get("floor2_start_y_ratio")
    s_bounds = face_bounds.get("south") or {}
    ground_y = s_bounds.get("ground", 0.8)
    eave_y   = s_bounds.get("eave",   0.2)
    bldg_span_y = ground_y - eave_y if ground_y > eave_y else 0.6

    if s_fl.get("has_second_floor") and floor2_y is not None and bldg_span_y > 0:
        # floor2_start_y_ratio は画像全体の割合なので、建物内での割合に変換
        f2_frac = (ground_y - floor2_y) / bldg_span_y  # 地面からの割合
        floor1_h = round(eave_height * f2_frac, 2)
        floor2_h = round(eave_height - floor1_h, 2)
        stories  = [{"floor": 1, "floor_height": floor1_h}, {"floor": 2, "floor_height": floor2_h}]
    else:
        floor1_h = eave_height
        floor2_h = 0.0
        stories  = []

    # セットバック → floor_footprints
    s_sb = face_setbacks.get("south") or {}
    floor_footprints = []
    if s_sb.get("has_setback") and floor2_h > 0:
        f1l = float(s_sb.get("f1_left_ratio",  0.0))
        f1r = float(s_sb.get("f1_right_ratio", 1.0))
        f2l = float(s_sb.get("f2_left_ratio",  0.05))
        f2r = float(s_sb.get("f2_right_ratio", 0.95))
        f1w = total_width * (f1r - f1l)
        f2w = total_width * (f2r - f2l)
        x_off = total_width * (f2l - f1l)
        floor_footprints = [
            {"floor": 1, "width": round(f1w, 2), "depth": total_depth,
             "x_offset": 0.0, "z_offset": 0.0, "floor_height": floor1_h},
            {"floor": 2, "width": round(f2w, 2), "depth": total_depth,
             "x_offset": round(x_off, 2), "z_offset": 0.0, "floor_height": floor2_h},
        ]

    # openings（pixel ratio → メートル変換）
    openings_all = []
    face_order = {"south": "south", "north": "north", "east": "east", "west": "west"}
    for face_key in face_order:
        ops_raw = face_openings_raw.get(face_key) or {}
        for floor_key, items in ops_raw.items():
            # floor_key 例: "1F_窓", "2F_ドア"
            parts = floor_key.split("_")
            f_num  = int(parts[0][0]) if parts and parts[0][0].isdigit() else 1
            o_type = parts[1] if len(parts) > 1 else "窓"

            # このfloorの地面からの高さオフセット
            z_offset = 0.0
            if f_num == 2 and floor1_h > 0:
                z_offset = floor1_h

            for op in items:
                xr = float(op.get("x_ratio", 0.5))
                zr = float(op.get("z_ratio", 0.5))
                wr = float(op.get("w_ratio", 0.1))
                hr = float(op.get("h_ratio", 0.15))

                # x: 建物幅に対するratio→メートル（左端基準）
                op_w = round(wr * total_width, 2)
                op_h = round(hr * eave_height, 2)
                # x_ratio は中心位置なので左端に変換
                op_x = round(xr * total_width - op_w / 2, 2)
                # z: 地面からの高さ
                floor_h = floor1_h if f_num == 1 else floor2_h
                if floor_h < 0.1: floor_h = eave_height
                op_z = round(z_offset + zr * floor_h - op_h / 2, 2)
                op_z = max(0.0, op_z)

                openings_all.append({
                    "face":   face_key,
                    "type":   o_type,
                    "x":      op_x,
                    "y":      0,
                    "z":      op_z,
                    "width":  max(0.3, op_w),
                    "height": max(0.3, op_h),
                })

    detected_faces = [k for k in face_dims if face_dims[k].get("width_m")]
    note = (f"多段階v2: {len(detected_faces)}面 | "
            f"幅{total_width}m / 軒高{eave_height}m / 棟高{ridge_height}m / 奥行{total_depth}m"
            + (f" / セットバック検出" if floor_footprints else ""))

    return {
        "building_type": "立面図（多段階v2）",
        "note": note,
        "dimensions": {
            "total_width":  total_width,
            "total_depth":  total_depth,
            "eave_height":  eave_height,
            "ridge_height": ridge_height,
        },
        "walls": [],
        "roof": {"type": roof_type, "eave_height": eave_height, "ridge_height": ridge_height},
        "openings":        openings_all,
        "floors": [{"label": "基礎", "x": 0, "y": 0, "z": -0.3,
                    "width": total_width, "depth": total_depth, "height": 0.3}],
        "floor_footprints": floor_footprints,
        "stories": stories,
        "_pipeline":   "multistage_v2",
        "_face_dims":  face_dims,
        "_face_setbacks": face_setbacks,
        "_layout":     {k: v for k, v in layout.items() if k != "_stage"},
    }

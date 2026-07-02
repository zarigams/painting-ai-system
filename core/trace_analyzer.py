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
  ]
}}
```

## 厳守ルール
- 実寸は**必ずラベルの数値を使う**（例: `A1 9.10m H` → 幅9.10m）
- 最長の水平線群 → 建物の幅
- 最長の垂直線群 → 建物の高さ（軒高）
- 青い水平線が縦にグループ化している領域 → 窓の候補
- openings の z = 床面からの高さ（1階腰窓=0.9、掃出窓=0、ドア=0、2階窓=3.5）
- floors の color フィールドは省略
- walls は南北東西の4面を必ず記述
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
        client = OpenAI(api_key=api_key)

        # 上位N本（実寸降順）の線データ
        key_lines = sorted(lines, key=lambda x: x["real_m"], reverse=True)[:top_n]
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

        raw_text = response.choices[0].message.content.strip()
        _raw_log = raw_text

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
        return {"error": f"JSONパースエラー: {e}", "_raw_gpt_response": raw_text}
    except Exception as e:
        return {"error": str(e), "_raw_gpt_response": raw_text}

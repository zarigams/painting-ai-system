"""
line_3d_builder.py
==================
線座標→3D パイプライン（方法4）

設計方針:
  - Canny+HoughLinesP で検出した線の real_m（縮尺換算済み実寸）を直接3D頂点に使用
  - GPT-4o は「どの線が何か（意味分類）」にのみ使用。座標推定には一切使わない
  - SAM（Segment Anything）は Phase2 で追加予定

メインAPI:
  build_3d_from_line_analysis(img_bytes, scale, api_key, face_regions=None) -> dict
"""

from __future__ import annotations
import io, json, math, base64
from typing import Optional

# ─────────────────────────────────────────────
#  ヘルパー: 面クロップ
# ─────────────────────────────────────────────

def _crop_region(img_bytes: bytes, x1r: float, y1r: float, x2r: float, y2r: float) -> bytes:
    """0〜1 ratio で画像をクロップして bytes を返す。"""
    from PIL import Image
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    W, H = img.size
    box = (int(x1r*W), int(y1r*H), int(x2r*W), int(y2r*H))
    cropped = img.crop(box)
    buf = io.BytesIO()
    cropped.save(buf, format="PNG")
    return buf.getvalue()


# ─────────────────────────────────────────────
#  Stage A: 面ラベル判定（GPT 1回のみ）
# ─────────────────────────────────────────────

def detect_face_labels(img_bytes: bytes, api_key: str) -> dict:
    """
    図面画像を4分割（左上/右上/左下/右下）し、
    各象限が南/北/東/西のどれかをGPTに1回で判定させる。

    Returns:
      {"top_left": "west", "top_right": "south", "bottom_left": "north", "bottom_right": "east"}
      値は south/north/east/west/unknown のいずれか
    """
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    b64 = base64.b64encode(img_bytes).decode()

    prompt = """この建築立面図に4つの立面図（南・北・東・西）が2×2で配置されています。
各象限（左上・右上・左下・右下）がどの立面図か、ラベル文字を読んで教えてください。
わからない場合は "unknown" にしてください。

```json
{"top_left": "west", "top_right": "south", "bottom_left": "north", "bottom_right": "east"}
```"""

    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"}},
            ]
        }],
        max_tokens=150,
        temperature=0.0,
    )
    raw = resp.choices[0].message.content.strip()
    # JSONを抽出
    if "```" in raw:
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"): raw = raw[4:]
        raw = raw.strip()
    if not raw.startswith("{"):
        si = raw.find("{")
        if si != -1:
            raw = raw[si:raw.rfind("}")+1]
    try:
        result = json.loads(raw)
    except Exception:
        # フォールバック: 住吉屋邸レイアウト（西/南/北/東）
        result = {"top_left": "west", "top_right": "south", "bottom_left": "north", "bottom_right": "east"}

    # quadrant→ratio のマッピング
    quad_ratios = {
        "top_left":     (0.0, 0.0, 0.5, 0.5),
        "top_right":    (0.5, 0.0, 1.0, 0.5),
        "bottom_left":  (0.0, 0.5, 0.5, 1.0),
        "bottom_right": (0.5, 0.5, 1.0, 1.0),
    }
    # 日本語→英語の正規化（GPT-4oが「南」「北面」等で返す場合に対応）
    _JP_NORM = {
        "南": "south", "南面": "south", "南立面": "south", "南立面図": "south",
        "北": "north", "北面": "north", "北立面": "north", "北立面図": "north",
        "東": "east",  "東面": "east",  "東立面": "east",  "東立面図": "east",
        "西": "west",  "西面": "west",  "西立面": "west",  "西立面図": "west",
    }
    face_regions = {}
    for quad, face in result.items():
        face = _JP_NORM.get(str(face).strip(), face)  # 日本語→英語
        if face in ("south","north","east","west") and quad in quad_ratios:
            face_regions[face] = quad_ratios[quad]
    return face_regions  # {"south": (x1r,y1r,x2r,y2r), ...}


# ─────────────────────────────────────────────
#  Stage B: 線を面領域でフィルタ
# ─────────────────────────────────────────────

def _lines_in_region(lines: list, x1r: float, y1r: float, x2r: float, y2r: float,
                     img_w: int, img_h: int) -> list:
    """各線の中点が face region 内に入っているものだけ返す。"""
    x1p, y1p = x1r * img_w, y1r * img_h
    x2p, y2p = x2r * img_w, y2r * img_h
    result = []
    for l in lines:
        mx = (l["x1"] + l["x2"]) / 2
        my = (l["y1"] + l["y2"]) / 2
        if x1p <= mx <= x2p and y1p <= my <= y2p:
            result.append(l)
    return result


# ─────────────────────────────────────────────
#  Stage C: 面ごとの建物外形を線座標から抽出（GPT不要）
# ─────────────────────────────────────────────

def extract_face_geometry(lines: list, m_per_px: float, face_h_px: int) -> dict:
    """
    1つの立面図領域内の線リストから建物外形を算出。GPT不要。

    【窓検出アルゴリズム改善 v2】
    「2水平線ペア」ではなく「4線矩形検出」を使用。
    - 水平ペア（上端・下端）+ 両端に垂直線が存在する場合のみ窓として確定
    - 建物外形ボックス（left_x〜right_x, eave_y〜ground_y）の内側のみ対象
    - 1面最大8個に制限

    Returns:
      {
        "width_m", "height_m", "floor1_h_m", "floor_line_ratio",
        "windows": [{"x_m","z_m","w_m","h_m"}],
        "eave_y_px", "ground_y_px", "left_x_px", "right_x_px",
      }
    """
    MIN_WALL_M  = 2.0   # 外壁候補の最小長さ（m）
    MIN_WIN_M   = 0.4   # 窓幅の最小（m）
    MAX_WIN_M   = 2.6   # 窓幅の最大（m）
    MAX_WIN_H_M = 2.0   # 窓高さの最大（m）
    MIN_WIN_H_M = 0.25  # 窓高さの最小（m）
    MAX_WINS    = 8     # 1面の最大窓数

    h_lines = [l for l in lines if l.get("orientation") == "horizontal"]
    v_lines = [l for l in lines if l.get("orientation") == "vertical"]

    if not h_lines:
        return {"error": "水平線なし"}

    # ── 軒と地盤の検出 ──────────────────────────────────────────────────
    long_h = sorted([l for l in h_lines if l.get("real_m", 0) >= MIN_WALL_M],
                    key=lambda l: l.get("real_m", 0), reverse=True)
    if not long_h:
        long_h = sorted(h_lines, key=lambda l: l.get("real_m", 0), reverse=True)

    eave_y   = min((l["y1"]+l["y2"])/2 for l in long_h)
    ground_y = max((l["y1"]+l["y2"])/2 for l in long_h)
    height_px = max(ground_y - eave_y, 1.0)
    height_m  = round(height_px * m_per_px, 2)

    # ── 建物幅の検出 ──────────────────────────────────────────────────────
    if v_lines:
        long_v = sorted([l for l in v_lines if l.get("real_m", 0) >= MIN_WALL_M],
                        key=lambda l: l.get("real_m", 0), reverse=True)
        if not long_v:
            long_v = sorted(v_lines, key=lambda l: l.get("real_m", 0), reverse=True)
        left_x  = min((l["x1"]+l["x2"])/2 for l in long_v)
        right_x = max((l["x1"]+l["x2"])/2 for l in long_v)
    else:
        left_x  = min(min(l["x1"], l["x2"]) for l in long_h)
        right_x = max(max(l["x1"], l["x2"]) for l in long_h)

    width_px = max(right_x - left_x, 1.0)
    width_m  = round(width_px * m_per_px, 2)

    # ── 建物外形ボックスのマージン ─────────────────────────────────────────
    # 外壁線自体 (left_x, right_x) から内側にマージンを取る
    wall_margin_px = max(5.0, width_px * 0.02)  # 幅の2%
    inner_left  = left_x  + wall_margin_px
    inner_right = right_x - wall_margin_px
    inner_top   = eave_y  + height_px * 0.05   # 軒から5%下
    inner_bot   = ground_y - height_px * 0.02  # 地盤から2%上

    # ── 1F/2F境界の検出 ───────────────────────────────────────────────────
    # 建物幅の30%以上の長さを持ち、建物内部にある水平線のうち
    # 最も密集するy座標 = 1F/2F境界
    mid_h = [l for l in h_lines
             if inner_top < (l["y1"]+l["y2"])/2 < inner_bot
             and l.get("real_m", 0) >= width_m * 0.3
             and inner_left <= min(l["x1"],l["x2"])
             and max(l["x1"],l["x2"]) <= inner_right + wall_margin_px * 5]
    if mid_h:
        from collections import Counter
        bucket_size = max(5, int(height_px * 0.03))
        buckets = Counter(int((l["y1"]+l["y2"])/2 / bucket_size) for l in mid_h)
        best_bucket = max(buckets, key=buckets.get)
        floor_line_y = best_bucket * bucket_size
        # サニティチェック: 境界は建物高さの30%〜75%の間
        fl_ratio_raw = (floor_line_y - eave_y) / height_px
        fl_ratio = max(0.30, min(0.75, fl_ratio_raw))
        floor_line_y = eave_y + fl_ratio * height_px
        floor_line_ratio = fl_ratio
        floor1_h_m = round((ground_y - floor_line_y) * m_per_px, 2)
    else:
        floor_line_ratio = 0.55
        floor1_h_m = round(height_m * 0.45, 2)

    # サニティチェック: 1F高さは建物全高の20%〜75%
    floor1_h_m = max(height_m * 0.20, min(floor1_h_m, height_m * 0.75))
    floor1_h_m = round(floor1_h_m, 2)

    # ── 窓検出: 4線矩形検出 ───────────────────────────────────────────────
    # Step1: 建物内部の小さな水平線候補（窓の上端・下端）
    win_candidates_h = [l for l in h_lines
                        if inner_top < (l["y1"]+l["y2"])/2 < inner_bot
                        and MIN_WIN_M <= l.get("real_m", 0) <= MAX_WIN_M
                        and inner_left <= min(l["x1"],l["x2"])
                        and max(l["x1"],l["x2"]) <= inner_right]

    win_candidates_h_sorted = sorted(win_candidates_h, key=lambda l: (l["y1"]+l["y2"])/2)

    windows = []
    used_ids = set()

    for i, top_line in enumerate(win_candidates_h_sorted):
        if len(windows) >= MAX_WINS:
            break
        if id(top_line) in used_ids:
            continue

        ty  = (top_line["y1"] + top_line["y2"]) / 2
        tx1 = min(top_line["x1"], top_line["x2"])
        tx2 = max(top_line["x1"], top_line["x2"])
        tw_m = top_line.get("real_m", 0)

        for bot_line in win_candidates_h_sorted[i+1:]:
            if id(bot_line) in used_ids:
                continue
            by  = (bot_line["y1"] + bot_line["y2"]) / 2
            bx1 = min(bot_line["x1"], bot_line["x2"])
            bx2 = max(bot_line["x1"], bot_line["x2"])
            bw_m = bot_line.get("real_m", 0)

            dy_m = (by - ty) * m_per_px
            if dy_m > MAX_WIN_H_M:
                break
            if dy_m < MIN_WIN_H_M:
                continue

            # 幅の一致チェック（15%以内）
            if abs(tw_m - bw_m) > max(0.3, tw_m * 0.15):
                continue

            # x位置の重なりチェック（50%以上）
            overlap = min(tx2, bx2) - max(tx1, bx1)
            span    = max(tx2, bx2) - min(tx1, bx1)
            if span <= 0 or overlap / span < 0.5:
                continue

            # 【4線矩形チェック】両端に垂直線が存在するか
            win_x1 = max(tx1, bx1)
            win_x2 = min(tx2, bx2)
            cx = (win_x1 + win_x2) / 2
            has_left_v  = any(
                abs((l["x1"]+l["x2"])/2 - win_x1) < width_px * 0.04
                and min((l["y1"]+l["y2"])/2, l["y1"], l["y2"]) <= ty + 5
                and max((l["y1"]+l["y2"])/2, l["y1"], l["y2"]) >= by - 5
                for l in v_lines
            )
            has_right_v = any(
                abs((l["x1"]+l["x2"])/2 - win_x2) < width_px * 0.04
                and min((l["y1"]+l["y2"])/2, l["y1"], l["y2"]) <= ty + 5
                and max((l["y1"]+l["y2"])/2, l["y1"], l["y2"]) >= by - 5
                for l in v_lines
            )

            if not (has_left_v or has_right_v):
                # 垂直線ゼロなら除外（寸法線・ハッチング除去）
                continue

            # 窓確定
            x_m = round((cx - left_x) * m_per_px - tw_m / 2, 2)
            x_m = max(0.0, min(x_m, width_m - tw_m))
            z_m = round((ground_y - by) * m_per_px, 2)
            z_m = max(0.0, z_m)

            windows.append({
                "x_m": x_m,
                "z_m": z_m,
                "w_m": round(tw_m, 2),
                "h_m": round(dy_m, 2),
            })
            used_ids.add(id(top_line))
            used_ids.add(id(bot_line))
            break

    return {
        "width_m":          width_m,
        "height_m":         height_m,
        "floor1_h_m":       floor1_h_m,
        "floor_line_ratio": round(floor_line_ratio, 3),
        "windows":          windows,
        "eave_y_px":        round(eave_y, 1),
        "ground_y_px":      round(ground_y, 1),
        "left_x_px":        round(left_x, 1),
        "right_x_px":       round(right_x, 1),
    }



# ─────────────────────────────────────────────
#  Stage C-GPT: 面ごとの窓検出（GPT）
# ─────────────────────────────────────────────

def detect_face_windows_gpt(face_img: bytes, face_label_jp: str,
                             width_m: float, height_m: float, api_key: str) -> list:
    """
    面クロップ画像からGPT-4o Visionで窓・ドアの位置を検出。
    線ベース検出の代替。各面1回のGPT呼び出し。

    Returns: [{"x_m", "z_m", "w_m", "h_m"}, ...]
      x_m: 建物左端からの距離（m）
      z_m: 地面からの高さ（m）
    """
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    b64 = base64.b64encode(face_img).decode()

    prompt = f"""この建物の{face_label_jp}立面図を見て、すべての窓・ドアの位置を教えてください。

建物の実寸: 幅{width_m}m × 高さ{height_m}m

各開口部を、建物左端からの距離(x_m)・地面からの高さ(z_m)・幅(w_m)・高さ(h_m) をメートル単位で返してください。
窓が見当たらない場合は空配列にしてください。

```json
{{"windows": [
  {{"x_m": 1.2, "z_m": 3.5, "w_m": 1.5, "h_m": 1.2, "type": "窓"}},
  {{"x_m": 3.0, "z_m": 0.2, "w_m": 0.9, "h_m": 2.0, "type": "ドア"}}
]}}
```"""

    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"}},
        ]}],
        max_tokens=600,
        temperature=0.0,
    )
    raw = resp.choices[0].message.content.strip()
    # デバッグ用: 生レスポンスを返却に含める
    _debug_raw = raw[:300]
    try:
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"): raw = raw[4:]
        if not raw.startswith("{"):
            si = raw.find("{")
            if si != -1: raw = raw[si:raw.rfind("}")+1]
        data = json.loads(raw)
        wins = data.get("windows", [])
        result = []
        for w in wins:
            x  = float(w.get("x_m", 0))
            z  = float(w.get("z_m", 0))
            ww = float(w.get("w_m", 0))
            wh = float(w.get("h_m", 0))
            # サニティチェック（建物範囲内・現実的なサイズ）
            if 0.3 <= ww <= 3.0 and 0.3 <= wh <= 2.5 and 0 <= x < width_m and 0 <= z < height_m:
                result.append({"x_m": round(x,2), "z_m": round(z,2),
                                "w_m": round(ww,2), "h_m": round(wh,2)})
        # GPTの生応答（デバッグ）と検出前の窓数もタプルで返す
        return result, _debug_raw, len(wins)
    except Exception as _e:
        return [], f"JSONパースエラー: {_e} / raw={_debug_raw}", 0

# ─────────────────────────────────────────────
#  Stage C-Slice: 輪切り（水平スライス）方式ウィンドウ検出（GPT不要）
# ─────────────────────────────────────────────

def scan_face_profile_windows(
    region_lines: list,
    left_x: float, right_x: float,
    eave_y: float, ground_y: float,
    m_per_px: float,
    n_y_strips: int = 40,
    n_x_bins: int = 60,
) -> list:
    """
    輪切り（水平スライス）方式でウィンドウを検出。GPT不要。

    設計思想（ユーザー指示に基づく）:
    1. 排除せず全線を読み込む
    2. 水平スライス × 垂直ビンの2Dグリッドを作成
    3. 各セルに線の有無を記録（密度マップ）
    4. 密度が低い（壁がない）領域 = 窓/ドア候補
    5. 連続した低密度矩形を窓として確定（サニティフィルタ付き）

    Returns:
      [{"x_m", "z_m", "w_m", "h_m"}, ...]  ← extract_face_geometry と同形式
    """
    H = max(ground_y - eave_y, 1.0)
    W = max(right_x - left_x, 1.0)

    # ── ステップ1: 2Dグリッドに全線を投影 ────────────────────────────────
    # grid[yi][xi] = 1 なら「線あり（壁）」、0 なら「線なし（空白）」
    grid = [[0] * n_x_bins for _ in range(n_y_strips)]

    for l in region_lines:
        x1, y1 = l.get("x1", 0), l.get("y1", 0)
        x2, y2 = l.get("x2", 0), l.get("y2", 0)
        orient = l.get("orientation", "")

        # グリッド座標変換
        xi1 = int((x1 - left_x) / W * n_x_bins)
        yi1 = int((y1 - eave_y) / H * n_y_strips)
        xi2 = int((x2 - left_x) / W * n_x_bins)
        yi2 = int((y2 - eave_y) / H * n_y_strips)

        # 線分を描画（Bresenham簡易版）
        steps = max(abs(xi2 - xi1), abs(yi2 - yi1), 1)
        for t in range(steps + 1):
            xi = xi1 + int((xi2 - xi1) * t / steps)
            yi = yi1 + int((yi2 - yi1) * t / steps)
            if 0 <= xi < n_x_bins and 0 <= yi < n_y_strips:
                # 垂直線は強くマーク、水平線は弱くマーク
                if orient == "vertical":
                    # 垂直線: ±1ビン幅でマーク（壁の実在を示す）
                    for dx in range(-1, 2):
                        if 0 <= xi + dx < n_x_bins:
                            grid[yi][xi + dx] = 1
                else:
                    # 水平線: 中央1点のみマーク（窓上端/下端）
                    grid[yi][xi] = 1

    # ── ステップ2: 建物外壁・境界は常に「壁あり」でマスク ──────────────────
    # 左端・右端3列 → 外壁
    for yi in range(n_y_strips):
        for xi in range(3):
            grid[yi][xi] = 1
        for xi in range(n_x_bins - 3, n_x_bins):
            grid[yi][xi] = 1
    # 軒上部5% / 地盤下部18% → 対象外（屋根・基礎・地面）
    for yi in range(int(n_y_strips * 0.05)):
        for xi in range(n_x_bins):
            grid[yi][xi] = 1
    for yi in range(int(n_y_strips * 0.82), n_y_strips):
        for xi in range(n_x_bins):
            grid[yi][xi] = 1

    # ── ステップ3: 各y-スライスのx方向空白ラン（=窓候補帯）を抽出 ─────────
    def _find_gaps_in_row(row):
        """row内の連続した0のランを返す: [(xi_start, xi_end), ...]"""
        gaps = []
        in_gap = False
        gs = 0
        for xi, v in enumerate(row):
            if not in_gap and v == 0:
                in_gap = True
                gs = xi
            elif in_gap and v != 0:
                gaps.append((gs, xi - 1))
                in_gap = False
        if in_gap:
            gaps.append((gs, len(row) - 1))
        return gaps

    slice_gaps = [_find_gaps_in_row(grid[yi]) for yi in range(n_y_strips)]

    # ── ステップ4: y方向に連続するギャップを統合 → 窓矩形を生成 ───────────
    MIN_WIN_W_FRAC = 0.04   # 建物幅の4%以上
    MAX_WIN_W_FRAC = 0.40   # 建物幅の40%以下
    MIN_WIN_H_FRAC = 0.06   # 建物高さの6%以上
    MAX_WIN_H_FRAC = 0.48   # 建物高さの48%以下
    MAX_WINS = 8

    windows = []
    used_cells = set()  # 処理済みセルを追跡

    for yi_start in range(n_y_strips):
        for gap in slice_gaps[yi_start]:
            gx0, gx1 = gap
            cell_key = (yi_start, gx0, gx1)
            if cell_key in used_cells:
                continue

            # このギャップをy方向に追跡（下方向に同じギャップが続くか）
            cur_gx0, cur_gx1 = gx0, gx1
            yi_end = yi_start
            for yi_next in range(yi_start + 1, n_y_strips):
                # yi_nextで現在のx範囲と重なるギャップを探す
                best_overlap = 0
                best_gap = None
                for g in slice_gaps[yi_next]:
                    overlap = min(cur_gx1, g[1]) - max(cur_gx0, g[0])
                    if overlap > best_overlap:
                        best_overlap = overlap
                        best_gap = g
                if best_gap is None or best_overlap <= 0:
                    break
                # x範囲を共通部分に絞る（精度向上）
                new_gx0 = max(cur_gx0, best_gap[0])
                new_gx1 = min(cur_gx1, best_gap[1])
                # x幅が急激に縮んだら追跡終了
                if (cur_gx1 - cur_gx0) > 0 and (new_gx1 - new_gx0) < (cur_gx1 - cur_gx0) * 0.5:
                    break
                cur_gx0, cur_gx1 = new_gx0, new_gx1
                yi_end = yi_next

            # 処理済みとしてマーク
            for yi in range(yi_start, yi_end + 1):
                used_cells.add((yi, gx0, gx1))

            # サイズチェック
            w_frac = (cur_gx1 - cur_gx0 + 1) / n_x_bins
            h_frac = (yi_end - yi_start + 1) / n_y_strips
            if not (MIN_WIN_W_FRAC <= w_frac <= MAX_WIN_W_FRAC):
                continue
            if not (MIN_WIN_H_FRAC <= h_frac <= MAX_WIN_H_FRAC):
                continue

            # ピクセル座標→メートル変換
            x_px   = left_x + cur_gx0 / n_x_bins * W
            y_top_px = eave_y + yi_start / n_y_strips * H
            y_bot_px = eave_y + (yi_end + 1) / n_y_strips * H

            w_m = round((cur_gx1 - cur_gx0 + 1) / n_x_bins * W * m_per_px, 2)
            h_m = round((yi_end - yi_start + 1) / n_y_strips * H * m_per_px, 2)
            x_m = round((x_px - left_x) * m_per_px, 2)
            z_m = round((ground_y - y_bot_px) * m_per_px, 2)

            windows.append({
                "x_m": max(0.0, x_m),
                "z_m": max(0.0, z_m),
                "w_m": max(0.3, w_m),
                "h_m": max(0.3, h_m),
            })
            if len(windows) >= MAX_WINS:
                return windows

    return windows


# ─────────────────────────────────────────────
#  Stage D: 屋根タイプ判定（GPT 1回）
# ─────────────────────────────────────────────

def detect_roof_type(south_img: bytes, api_key: str) -> str:
    """南立面の画像から屋根タイプを1回のGPT呼び出しで判定。"""
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    b64 = base64.b64encode(south_img).decode()
    prompt = """この建物の南立面図の屋根タイプを答えてください。
選択肢: 寄棟 / 切妻 / 片流れ / 陸屋根
1単語でJSONで返してください。
```json
{"roof_type": "寄棟"}
```"""
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role":"user","content":[
            {"type":"text","text":prompt},
            {"type":"image_url","image_url":{"url":f"data:image/png;base64,{b64}","detail":"low"}},
        ]}],
        max_tokens=30, temperature=0.0,
    )
    raw = resp.choices[0].message.content.strip()
    try:
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"): raw = raw[4:]
        if not raw.startswith("{"): raw = raw[raw.find("{"):]
        return json.loads(raw).get("roof_type","寄棟")
    except Exception:
        return "寄棟"


# ─────────────────────────────────────────────
#  Stage E: 3Dデータ組み立て
# ─────────────────────────────────────────────

def assemble_3d(face_geometries: dict, roof_type: str, annotations_dims: dict = None) -> dict:
    """
    各面のジオメトリデータを3D building dict に変換。

    face_geometries: {"south": {...}, "north": {...}, ...}
    annotations_dims: DrawingAnalyzer から取得した寸法（信頼度高）があれば上書き
    """
    # 南面→幅, 東/西面→奥行き を優先
    s = face_geometries.get("south") or {}
    n = face_geometries.get("north") or {}
    e = face_geometries.get("east")  or {}
    w = face_geometries.get("west")  or {}

    # 寸法の決定（南面・北面の幅が建物幅, 東面・西面の幅が建物奥行き）
    total_width = s.get("width_m") or n.get("width_m") or 10.0
    total_depth = e.get("width_m") or w.get("width_m") or round(total_width * 0.72, 2)
    eave_height_raw = s.get("height_m") or n.get("height_m") or e.get("height_m") or 6.0
    floor1_h_raw    = s.get("floor1_h_m") or n.get("floor1_h_m") or round(eave_height_raw * 0.45, 2)
    eave_height = eave_height_raw
    floor1_h    = floor1_h_raw

    # DrawingAnalyzerの値で上書き（最も信頼度が高い）
    ridge_height = round(eave_height + total_width * 0.15, 2)  # デフォルト（必ず定義）
    if annotations_dims:
        if annotations_dims.get("total_width"):  total_width  = float(annotations_dims["total_width"])
        if annotations_dims.get("total_depth"):  total_depth  = float(annotations_dims["total_depth"])
        if annotations_dims.get("eave_height"):  eave_height  = float(annotations_dims["eave_height"])
        if annotations_dims.get("ridge_height"): ridge_height = float(annotations_dims["ridge_height"])
        else: ridge_height = round(eave_height + total_width * 0.15, 2)
    # ── 1F高さ計算（改善版）──────────────────────────────────────────────────
    # annotations_dimsがeave_heightを提供した場合: 線検出値は縮尺誤差が大きいため使わず
    # eave_heightを基準に再計算。日本の2階建て標準比率 1F:2F ≈ 46:54 を使用。
    if annotations_dims and annotations_dims.get("eave_height"):
        floor1_h = round(float(eave_height) * 0.46, 2)
    else:
        # 線検出値を使う場合: 比例スケール（eave_heightが変わった場合のみ）
        if eave_height_raw > 0 and abs(eave_height - eave_height_raw) > 0.1:
            floor1_h = round(floor1_h_raw * eave_height / eave_height_raw, 2)
    # 絶対保証サニティ: floor1_h は必ず eave_height の [30%, 65%] に収める
    floor1_h = max(round(float(eave_height) * 0.30, 2),
                   min(round(float(eave_height) * 0.65, 2), floor1_h))

    # openings 生成（各面の窓を3D座標に変換）
    openings = []
    face_span = {"south": total_width, "north": total_width, "east": total_depth, "west": total_depth}
    for face_name, geom in face_geometries.items():
        if not geom or "windows" not in geom:
            continue
        span = face_span.get(face_name, total_width)
        for win in geom["windows"]:
            x_m = win["x_m"]
            # 幅スケール補正（検出幅 vs 実際幅）
            detected_w = geom.get("width_m", span)
            if detected_w and detected_w > 0:
                x_m = round(x_m * span / detected_w, 2)
            openings.append({
                "face":   face_name,
                "x":      max(0.0, x_m),
                "z":      win["z_m"],
                "width":  win["w_m"],
                "height": win["h_m"],
                "type":   "窓",
            })

    note = (f"線解析v3-slice: 幅{total_width}m / 軒高{eave_height}m / "
            f"棟高{ridge_height}m / 奥行{total_depth}m / "
            f"1F高{floor1_h}m / 窓{len(openings)}個")

    return {
        "building_type": "立面図（線解析）",
        "note": note,
        "_pipeline": "line_analysis_v1",
        "dimensions": {
            "total_width":  total_width,
            "total_depth":  total_depth,
            "eave_height":  eave_height,
            "ridge_height": ridge_height,
        },
        "walls": [],
        "roof": {
            "type":         roof_type,
            "eave_height":  eave_height,
            "ridge_height": ridge_height,
        },
        "openings":        openings,
        "floor_footprints": [],
        "stories": [
            {"floor": 1, "height": floor1_h},
            {"floor": 2, "height": round(eave_height - floor1_h, 2)},
        ],
    }


# ─────────────────────────────────────────────
#  メインAPI
# ─────────────────────────────────────────────

def build_3d_from_line_analysis(
    img_bytes: bytes,
    scale: int,
    api_key: str,
    face_regions: dict = None,
    roof_type: str = None,
    annotations_dims: dict = None,
    faces_data: dict = None,
    progress_callback=None,
) -> dict:
    """
    メインエントリーポイント。

    img_bytes       : 図面画像（PNG bytes）※ 4面が1枚に収まったもの
    scale           : 縮尺分母（S=1/100 なら 100）
    api_key         : OpenAI API key
    face_regions    : {"south":(x1r,y1r,x2r,y2r),...} ユーザーが指定した場合はこれを使う
    roof_type       : 屋根タイプ文字列（指定なければGPTで判定）
    annotations_dims: DrawingAnalyzerの寸法dict（あれば最優先）
    faces_data      : DrawingAnalyzerのfaces dict（あればGPT窓検出をスキップ）
                      例: {"south": {"openings": [{"x_from_left":1.0,"z_from_ground":0.9,"width":1.6,"height":1.2}]}}
    progress_callback: fn(stage_name, message) → UIへの進捗通知

    Returns: building 3D dict (building_3d_generator.py と互換)
    """
    def _cb(stage, msg):
        if progress_callback:
            progress_callback(stage, msg)

    # --- Stage A: 面ラベル検出 ---
    _FALLBACK_REGIONS = {
        "west":  (0.0, 0.0, 0.5, 0.5),
        "south": (0.5, 0.0, 1.0, 0.5),
        "north": (0.0, 0.5, 0.5, 1.0),
        "east":  (0.5, 0.5, 1.0, 1.0),
    }
    _cb("A", "各立面図の位置を特定中（GPT 1回）…")
    if face_regions is None:
        try:
            face_regions = detect_face_labels(img_bytes, api_key)
            _cb("A", f"面検出: {list(face_regions.keys())}")
        except Exception as ex:
            face_regions = {}
            _cb("A", f"面検出例外: {ex}")
        # GPTが全unknownを返した等で面が2未満の場合もフォールバック
        if len(face_regions) < 2:
            face_regions = _FALLBACK_REGIONS
            _cb("A", "面検出数不足→標準2×2レイアウト使用（西/南/北/東）")

    # --- Stage B: 線検出 ---
    _cb("B", "全線分を検出中（Canny+Hough）…")
    from core.line_detector import detect_lines_with_lengths
    from PIL import Image
    img_pil = Image.open(io.BytesIO(img_bytes))
    img_w, img_h = img_pil.size
    ld = detect_lines_with_lengths(img_bytes, scale_denominator=scale)
    all_lines = ld.get("lines", [])
    m_per_px  = ld.get("scale_m_per_px", 0.001)
    _cb("B", f"線検出完了: {len(all_lines)}本 / m_per_px={m_per_px:.5f}")

    # --- Stage C: 面ごとに外形抽出 + 窓検出（DrawingAnalyzerデータ優先、なければGPT）---
    _JP = {"south":"南","north":"北","east":"東","west":"西"}
    face_geometries = {}
    for face, (x1r, y1r, x2r, y2r) in face_regions.items():
        _cb("C", f"{face}面: 線座標から外形を計算中…")
        region_lines = _lines_in_region(all_lines, x1r, y1r, x2r, y2r, img_w, img_h)
        face_h_px = int((y2r - y1r) * img_h)
        geom = extract_face_geometry(region_lines, m_per_px, face_h_px)
        if "error" not in geom:
            # DrawingAnalyzerのfacesデータがあればGPT呼び出しをスキップ
            da_face = (faces_data or {}).get(face, {})
            da_openings = da_face.get("openings", []) if isinstance(da_face, dict) else []
            if da_openings:
                wins = [
                    {"x_m": float(o.get("x_from_left", 0)),
                     "z_m": float(o.get("z_from_ground", o.get("z_from_floor", 0))),
                     "w_m": float(o.get("width", 1.2)),
                     "h_m": float(o.get("height", 1.0))}
                    for o in da_openings
                ]
                geom["windows"] = wins
                _cb("C", f"  {face}: DrawingAnalyzerデータ使用 → 窓{len(wins)}個")
            else:
                # DrawingAnalyzerデータなし → スライス方式（輪切り）で検出
                _cb("C", f"  {face}: 幅{geom['width_m']}m / 高{geom['height_m']}m → スライス方式で窓検出中…")
                try:
                    slice_wins = scan_face_profile_windows(
                        region_lines,
                        geom["left_x_px"], geom["right_x_px"],
                        geom["eave_y_px"],  geom["ground_y_px"],
                        m_per_px,
                    )
                    geom["windows"] = slice_wins
                    _cb("C", f"  {face}: スライス検出={len(slice_wins)}個")
                    # スライス方式でも0個ならGPTを試みる（フォールバック）
                    if len(slice_wins) == 0:
                        _cb("C", f"  {face}: スライス0個 → GPTフォールバック…")
                        try:
                            face_crop = _crop_region(img_bytes, x1r, y1r, x2r, y2r)
                            wins, _dbg_raw, _dbg_total = detect_face_windows_gpt(
                                face_crop, _JP.get(face, face),
                                geom["width_m"], geom["height_m"], api_key
                            )
                            geom["windows"] = wins
                            _cb("C", f"  {face}: GPT応答(先頭)={_dbg_raw[:120]}")
                            _cb("C", f"  {face}: GPT={_dbg_total}個→OK={len(wins)}個")
                        except Exception as _gpt_ex:
                            _cb("C", f"  {face}: GPTも失敗({_gpt_ex})→0個")
                except Exception as ex:
                    _cb("C", f"  {face}: スライス窓検出失敗({ex})")
        else:
            _cb("C", f"  {face}: {geom['error']}")
        face_geometries[face] = geom

    # --- Stage D: 屋根タイプ ---
    if roof_type is None:
        south_region = face_regions.get("south")
        if south_region:
            _cb("D", "屋根タイプを判定中（GPT 1回）…")
            try:
                s_img = _crop_region(img_bytes, *south_region)
                roof_type = detect_roof_type(s_img, api_key)
                _cb("D", f"屋根タイプ: {roof_type}")
            except Exception:
                roof_type = "寄棟"
        else:
            roof_type = "寄棟"

    # --- Stage E: 3D組み立て ---
    _cb("E", "3Dデータを組み立て中…")
    result = assemble_3d(face_geometries, roof_type, annotations_dims)
    result["_face_regions"] = face_regions       # UIで再利用できるよう保存
    result["_face_geometries"] = face_geometries # デバッグ用
    _cb("E", f"完了: {result['note']}")
    return result

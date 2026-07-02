"""
line_detector.py
図面画像から線分を全て検出し、縮尺で実寸換算してラベル付き画像を生成する

使い方:
    result = detect_lines_with_lengths(img_bytes, scale_denominator=100)
    result["annotated_bytes"]  # ラベル付き画像バイト
    result["lines"]            # 線情報リスト
    result["stats"]            # 集計
"""

import io
import math

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# PyMuPDF Matrix(2.0, 2.0) → 72 DPI × 2 = 144 DPI
DEFAULT_RENDER_DPI = 144

# 色マップ（実寸長による）
def _line_color(real_m: float) -> tuple:
    if real_m >= 8.0:
        return (0, 180, 50, 220)      # 緑：長い（外壁幅クラス）
    elif real_m >= 3.0:
        return (220, 120, 0, 220)     # 橙：中（破風・雨樋クラス）
    elif real_m >= 1.0:
        return (50, 100, 255, 220)    # 青：短め（窓・ドアクラス）
    else:
        return (180, 50, 180, 160)    # 紫：細かい


def assign_block_names(lines: list, img_w: int, img_h: int, cols: int = 5) -> None:
    """
    各線分の中点座標に基づいて空間ブロック名（A1, B2, C3 …）を付与する。
    左→右の列を A, B, C, D, E … とし、各列内で実寸長降順に 1, 2, 3 … と番号付け。
    lines リストを in-place で更新する（"id" フィールドに書き込む）。
    """
    import math as _math
    if not lines:
        return
    col_w = img_w / cols
    # 各線に列インデックスを割り当て
    for ln in lines:
        mx = (ln["x1"] + ln["x2"]) / 2
        col_idx = min(int(mx / col_w), cols - 1)
        ln["_col_idx"] = col_idx
    # 列ごとに実寸長降順でナンバリング
    from collections import defaultdict
    col_groups = defaultdict(list)
    for ln in lines:
        col_groups[ln["_col_idx"]].append(ln)
    for col_idx in range(cols):
        letter = chr(65 + col_idx)  # 0→A, 1→B, ...
        group = col_groups[col_idx]
        # 実寸長降順（すでに全体ソート済みなのでそのまま）
        for num, ln in enumerate(group, 1):
            ln["id"] = f"{letter}{num}"
    # 一時フィールド削除
    for ln in lines:
        ln.pop("_col_idx", None)


def detect_lines_with_lengths(
    img_bytes: bytes,
    scale_denominator: int = 100,
    render_dpi: int = DEFAULT_RENDER_DPI,
    min_length_m: float = 0.2,
    max_length_m: float = 50.0,
    merge_gap_px: int = 10,
) -> dict:
    """
    図面画像から全線分を検出し、実寸ラベル付き画像を返す。

    Parameters
    ----------
    img_bytes          : 図面画像（PNG/JPEGバイト）
    scale_denominator  : 縮尺の分母（S=1/100なら100）
    render_dpi         : PDF→画像変換時のDPI（PyMuPDF Matrix(2,2)=144）
    min_length_m       : 検出最小長（m）。これ未満は無視
    max_length_m       : 検出最大長（m）。超過は無視（枠線等）
    merge_gap_px       : 同一線とみなすギャップ（px）

    Returns
    -------
    dict:
        annotated_bytes : ラベル付き画像バイト
        lines           : [{"x1","y1","x2","y2","px_length","real_m","angle_deg","orientation"}, ...]
        scale_m_per_px  : float
        stats           : {"total","horizontal","vertical","diagonal"}
    """
    # スケール係数
    mm_per_px = (25.4 / render_dpi) * scale_denominator
    m_per_px  = mm_per_px / 1000.0

    # 画像デコード
    nparr   = np.frombuffer(img_bytes, np.uint8)
    img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img_bgr is None:
        return {"error": "画像デコード失敗", "lines": [], "stats": {}}

    h, w = img_bgr.shape[:2]

    # グレースケール → 前処理
    gray  = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    # 線が薄い場合に強調（CLAHEで局所コントラスト）
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray  = clahe.apply(gray)
    blur  = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(blur, 30, 90, apertureSize=3)

    # 最小ピクセル長を計算
    min_px = max(10, int(min_length_m / m_per_px))

    # HoughLinesP で線分検出
    raw = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=35,
        minLineLength=min_px,
        maxLineGap=merge_gap_px,
    )

    lines_info = []
    if raw is not None:
        for seg in raw:
            x1, y1, x2, y2 = seg[0]
            px_len = math.hypot(x2 - x1, y2 - y1)
            real_m = px_len * m_per_px

            if real_m > max_length_m:
                continue

            angle = math.degrees(math.atan2(abs(y2 - y1), abs(x2 - x1)))
            if angle < 10:
                orientation = "horizontal"
            elif angle > 80:
                orientation = "vertical"
            else:
                orientation = "diagonal"

            lines_info.append({
                "x1": int(x1), "y1": int(y1),
                "x2": int(x2), "y2": int(y2),
                "px_length": round(px_len, 1),
                "real_m":    round(real_m, 3),
                "angle_deg": round(angle, 1),
                "orientation": orientation,
            })

    # 実寸長で降順ソート → 空間ブロック名（A1, B2...）付与
    lines_info.sort(key=lambda x: x["real_m"], reverse=True)
    h, w = img_bgr.shape[:2]
    assign_block_names(lines_info, img_w=w, img_h=h)

    # ── ラベル付き画像生成 ──────────────────────────────────
    img_pil = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
    overlay = Image.new("RGBA", img_pil.size, (0, 0, 0, 0))
    draw    = ImageDraw.Draw(overlay)

    try:
        font    = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 13)
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
    except Exception:
        font = font_sm = ImageFont.load_default()

    # 上位200本まで描画（それ以上は表示が煩雑）
    for ln in lines_info[:200]:
        col  = _line_color(ln["real_m"])
        x1, y1, x2, y2 = ln["x1"], ln["y1"], ln["x2"], ln["y2"]
        ln_id = ln.get("id", "?")

        # 線
        draw.line([(x1, y1), (x2, y2)], fill=col, width=2)

        # 端点マーカー
        r = 3
        draw.ellipse([(x1-r, y1-r), (x1+r, y1+r)], fill=col)
        draw.ellipse([(x2-r, y2-r), (x2+r, y2+r)], fill=col)

        # 中点ラベル: #番号 + 実寸（0.5m以上）
        if ln["real_m"] >= 0.5:
            mx = (x1 + x2) // 2
            my = (y1 + y2) // 2
            label = f"{ln_id} {ln['real_m']:.2f}m"
            try:
                bbox = draw.textbbox((mx, my), label, font=font_sm)
                pad = 2
                draw.rectangle(
                    [bbox[0]-pad, bbox[1]-pad, bbox[2]+pad, bbox[3]+pad],
                    fill=(255, 255, 255, 200)
                )
            except Exception:
                pass
            draw.text((mx, my), label, fill=(col[0], col[1], col[2], 255), font=font_sm)

    result_img = Image.alpha_composite(img_pil.convert("RGBA"), overlay).convert("RGB")
    buf = io.BytesIO()
    result_img.save(buf, format="PNG")

    stats = {
        "total":      len(lines_info),
        "horizontal": sum(1 for l in lines_info if l["orientation"] == "horizontal"),
        "vertical":   sum(1 for l in lines_info if l["orientation"] == "vertical"),
        "diagonal":   sum(1 for l in lines_info if l["orientation"] == "diagonal"),
    }

    return {
        "annotated_bytes": buf.getvalue(),
        "lines":           lines_info,
        "scale_m_per_px":  round(m_per_px, 6),
        "stats":           stats,
    }


def find_nearest_line(click_x: float, click_y: float, lines: list, max_dist_px: float = 40.0) -> dict | None:
    """
    クリック座標に最も近い検出済み線分を返す。

    Parameters
    ----------
    click_x, click_y : クリック座標（元画像ピクセル空間）
    lines            : detect_lines_with_lengths() の lines リスト
    max_dist_px      : この距離（px）以内にある線のみ対象

    Returns
    -------
    最近傍の線dict、または None（範囲内に線なし）
    """
    best = None
    best_dist = max_dist_px

    for ln in lines:
        x1, y1, x2, y2 = ln["x1"], ln["y1"], ln["x2"], ln["y2"]
        # 点から線分への最短距離
        dx, dy = x2 - x1, y2 - y1
        if dx == 0 and dy == 0:
            dist = math.hypot(click_x - x1, click_y - y1)
        else:
            t = max(0.0, min(1.0, ((click_x - x1) * dx + (click_y - y1) * dy) / (dx*dx + dy*dy)))
            nx, ny = x1 + t * dx, y1 + t * dy
            dist = math.hypot(click_x - nx, click_y - ny)

        if dist < best_dist:
            best_dist = dist
            best = {**ln, "_dist_px": round(dist, 1)}

    return best


def highlight_line(img_bytes: bytes, line: dict, color: tuple = (255, 50, 50, 255)) -> bytes:
    """
    指定した線を太く赤でハイライトした画像バイトを返す。
    """
    nparr   = np.frombuffer(img_bytes, np.uint8)
    img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    img_pil = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
    overlay = Image.new("RGBA", img_pil.size, (0, 0, 0, 0))
    draw    = ImageDraw.Draw(overlay)

    x1, y1, x2, y2 = line["x1"], line["y1"], line["x2"], line["y2"]
    draw.line([(x1, y1), (x2, y2)], fill=color, width=5)
    r = 6
    draw.ellipse([(x1-r, y1-r), (x1+r, y1+r)], fill=color)
    draw.ellipse([(x2-r, y2-r), (x2+r, y2+r)], fill=color)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
    except Exception:
        font = ImageFont.load_default()

    label = f"★ {line['real_m']:.3f}m"
    mx, my = (x1+x2)//2, (y1+y2)//2
    try:
        bbox = draw.textbbox((mx-2, my-20), label, font=font)
        draw.rectangle([bbox[0]-3, bbox[1]-3, bbox[2]+3, bbox[3]+3], fill=(255,255,0,220))
    except Exception:
        pass
    draw.text((mx-2, my-20), label, fill=(180, 0, 0, 255), font=font)

    result = Image.alpha_composite(img_pil.convert("RGBA"), overlay).convert("RGB")
    buf = io.BytesIO()
    result.save(buf, format="PNG")
    return buf.getvalue()


def generate_trace_svg(
    lines: list,
    scale_m_per_px: float,
    svg_width: int = 900,
    min_length_m: float = 0.5,
    group_by_block: bool = True,
    show_grid: bool = True,
    show_diagonal: bool = True,
) -> str:
    """
    検出した線分から、実寸比率で再現したSVGトレースを生成する。

    Parameters
    ----------
    lines          : detect_lines_with_lengths() の lines
    scale_m_per_px : 1ピクセルあたりの実寸(m)
    svg_width      : SVGの幅(px)
    min_length_m   : この長さ未満の線は描画しない
    group_by_block : True のとき同ブロック（A/B/C…）内で最長1本のみ描画

    Returns
    -------
    SVG文字列
    """
    if not lines:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="100"><text x="10" y="50" font-size="16">検出線なし</text></svg>'

    # 描画対象フィルタ
    draw_lines = [l for l in lines if l["real_m"] >= min_length_m and (show_diagonal or l["orientation"] != "diagonal")]

    # ブロックごとに最長1本だけ残す
    if group_by_block:
        from collections import defaultdict
        block_best = {}
        for ln in draw_lines:
            blk = str(ln.get("id", "?"))[0]  # 先頭文字 A/B/C...
            if blk not in block_best or ln["real_m"] > block_best[blk]["real_m"]:
                block_best[blk] = ln
        draw_lines = sorted(block_best.values(), key=lambda x: str(x.get("id", "")))

    if not draw_lines:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="100"><text x="10" y="50" font-size="16">表示可能な線なし</text></svg>'

    # バウンディングボックス計算（原画像ピクセル座標）
    xs = [l["x1"] for l in draw_lines] + [l["x2"] for l in draw_lines]
    ys = [l["y1"] for l in draw_lines] + [l["y2"] for l in draw_lines]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    orig_w = max_x - min_x or 1
    orig_h = max_y - min_y or 1

    # スケーリング（SVG幅に合わせる）
    margin = 40
    draw_w = svg_width - margin * 2
    draw_h = int(draw_w * orig_h / orig_w)
    svg_h  = draw_h + margin * 2 + 60  # 下部にラベル分を追加

    def tx(x): return margin + (x - min_x) * draw_w / orig_w
    def ty(y): return margin + (y - min_y) * draw_h / orig_h

    # 色マップ
    def _col(real_m):
        if real_m >= 8.0:  return "#00aa33"  # 緑
        if real_m >= 3.0:  return "#ff8800"  # 橙
        if real_m >= 1.0:  return "#2266ff"  # 青
        return "#aa44aa"                      # 紫

    # 向き別グループ（角度）
    def _orient_label(angle_deg):
        if angle_deg < 5:
            return "H"   # 水平
        elif angle_deg > 85:
            return "V"   # 垂直
        else:
            return f"{angle_deg:.0f}°"

    lines_svg = []
    labels_svg = []

    for ln in draw_lines:
        x1s, y1s = tx(ln["x1"]), ty(ln["y1"])
        x2s, y2s = tx(ln["x2"]), ty(ln["y2"])
        col  = _col(ln["real_m"])
        # 真角度（始点→終点の方向、0-360°）
        true_angle = math.degrees(math.atan2(-(ln["y2"]-ln["y1"]), ln["x2"]-ln["x1"])) % 360

        lines_svg.append(
            f'<line x1="{x1s:.1f}" y1="{y1s:.1f}" x2="{x2s:.1f}" y2="{y2s:.1f}" '
            f'stroke="{col}" stroke-width="2" stroke-linecap="round"/>'
        )
        # 端点
        for cx, cy in [(x1s,y1s),(x2s,y2s)]:
            lines_svg.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3" fill="{col}"/>')

        # 中点ラベル（ブロック名 + 寸法 + 向き）
        line_id = str(ln.get("id", ""))
        mx = (x1s + x2s) / 2
        my = (y1s + y2s) / 2
        orient = _orient_label(ln["angle_deg"])
        lbl = f"{line_id} {ln['real_m']:.2f}m {orient}"
        lbl_w = max(len(lbl) * 7, 50)
        labels_svg.append(
            f'<rect x="{mx-2:.1f}" y="{my-13:.1f}" width="{lbl_w}" height="15" fill="white" opacity="0.85" rx="2"/>'
            f'<text x="{mx+1:.1f}" y="{my:.1f}" font-size="11" fill="{col}" font-weight="bold">{lbl}</text>'
        )

    # グリッド（実寸1m単位）
    grid_svg = ""
    if show_grid:
        real_xs = [l["x1"] for l in draw_lines] + [l["x2"] for l in draw_lines]
        real_ys = [l["y1"] for l in draw_lines] + [l["y2"] for l in draw_lines]
        if real_xs and real_ys:
            gx0, gx1 = min(real_xs), max(real_xs)
            gy0, gy1 = min(real_ys), max(real_ys)
            # 1m刻みの間隔(px)
            step_px = 1.0 / scale_m_per_px if scale_m_per_px > 0 else 0
            if 0 < step_px < (max(orig_w, orig_h) / 2):
                # 垂直グリッド線
                x = gx0
                while x <= gx1 + step_px:
                    sx = tx(x)
                    grid_svg += f'<line x1="{sx:.1f}" y1="{margin}" x2="{sx:.1f}" y2="{margin+draw_h}" stroke="#ccc" stroke-width="0.4" stroke-dasharray="3,3" opacity="0.5"/>'
                    x += step_px
                # 水平グリッド線
                y = gy0
                while y <= gy1 + step_px:
                    sy = ty(y)
                    grid_svg += f'<line x1="{margin}" y1="{sy:.1f}" x2="{margin+draw_w}" y2="{sy:.1f}" stroke="#ccc" stroke-width="0.4" stroke-dasharray="3,3" opacity="0.5"/>'
                    y += step_px

    # 凡例
    legend = (
        f'<text x="{margin}" y="{svg_h-35}" font-size="11" fill="#00aa33">■ 8m以上</text>'
        f'<text x="{margin+80}" y="{svg_h-35}" font-size="11" fill="#ff8800">■ 3m以上</text>'
        f'<text x="{margin+160}" y="{svg_h-35}" font-size="11" fill="#2266ff">■ 1m以上</text>'
        f'<text x="{margin+240}" y="{svg_h-35}" font-size="11" fill="#aa44aa">■ 1m未満</text>'
        f'<text x="{margin}" y="{svg_h-18}" font-size="10" fill="#666">'
        f'H=水平  V=垂直  数字=傾き角度  計{len(draw_lines)}本</text>'
    )

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_width}" height="{svg_h}" '
        f'style="background:#f8f8f8;border:1px solid #ddd">'
        f'{grid_svg}'
        f'{"".join(lines_svg)}'
        f'{"".join(labels_svg)}'
        f'{legend}'
        f'</svg>'
    )
    return svg


def generate_3d_html(
    lines: list,
    scale_m_per_px: float,
    min_length_m: float = 0.5,
    group_by_block: bool = True,
    canvas_height: int = 600,
) -> str:
    """
    Three.js を使った3Dインタラクティブビューを返す。
    - マウスドラッグ: 回転
    - スクロール: ズーム
    - 線クリック: 線名・実寸をポップアップ表示

    Returns
    -------
    st.components.v1.html() に渡すHTML文字列
    """
    import json as _json

    draw = [l for l in lines if l["real_m"] >= min_length_m]

    if group_by_block:
        block_best: dict = {}
        for ln in draw:
            blk = str(ln.get("id", "?"))[0]
            if blk not in block_best or ln["real_m"] > block_best[blk]["real_m"]:
                block_best[blk] = ln
        draw = list(block_best.values())

    if not draw:
        return "<p>表示できる線がありません</p>"

    # 座標をメートル空間に変換（中心を原点に）
    xs = [(l["x1"] + l["x2"]) / 2 for l in draw]
    ys = [(l["y1"] + l["y2"]) / 2 for l in draw]
    cx = sum(xs) / len(xs) if xs else 0
    cy = sum(ys) / len(ys) if ys else 0

    def _color(real_m: float) -> str:
        if real_m >= 8.0: return "0x00cc44"
        if real_m >= 3.0: return "0xff8800"
        if real_m >= 1.0: return "0x2266ff"
        return "0xaa44aa"

    # JavaScriptに渡す線データ
    js_lines = []
    for ln in draw:
        x1m = (ln["x1"] - cx) * scale_m_per_px
        y1m = -(ln["y1"] - cy) * scale_m_per_px  # Y軸反転
        x2m = (ln["x2"] - cx) * scale_m_per_px
        y2m = -(ln["y2"] - cy) * scale_m_per_px
        js_lines.append({
            "x1": round(x1m, 3), "y1": round(y1m, 3),
            "x2": round(x2m, 3), "y2": round(y2m, 3),
            "id": str(ln.get("id", "")),
            "real_m": ln["real_m"],
            "orientation": ln["orientation"],
            "color": _color(ln["real_m"]),
        })

    lines_json = _json.dumps(js_lines, ensure_ascii=False)
    orient_map = {"horizontal": "水平", "vertical": "垂直", "diagonal": "斜め"}

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ margin:0; background:#1a1a2e; overflow:hidden; font-family:sans-serif; }}
  canvas {{ display:block; }}
  #info {{
    position:absolute; top:10px; left:50%; transform:translateX(-50%);
    background:rgba(0,0,0,0.75); color:#fff; padding:8px 16px;
    border-radius:20px; font-size:13px; pointer-events:none;
    border:1px solid rgba(255,255,255,0.2);
  }}
  #popup {{
    position:absolute; display:none;
    background:rgba(20,20,40,0.95); color:#fff;
    padding:12px 18px; border-radius:10px; font-size:14px;
    border:1px solid #4af; pointer-events:none; min-width:180px;
  }}
  #popup .name  {{ font-size:22px; font-weight:bold; color:#4af; }}
  #popup .meter {{ font-size:18px; color:#afa; margin:4px 0; }}
  #popup .ori   {{ font-size:13px; color:#aaa; }}
  #legend {{
    position:absolute; bottom:14px; left:14px;
    background:rgba(0,0,0,0.6); color:#fff;
    padding:8px 14px; border-radius:8px; font-size:12px;
  }}
  #legend span {{ display:inline-block; width:12px; height:12px;
    border-radius:2px; margin-right:5px; vertical-align:middle; }}
</style>
</head>
<body>
<div id="info">🖱 ドラッグ: 回転　ホイール: ズーム　線クリック: 詳細表示</div>
<div id="popup"><div class="name" id="p-name"></div><div class="meter" id="p-m"></div><div class="ori" id="p-ori"></div></div>
<div id="legend">
  <span style="background:#00cc44"></span>8m以上 &nbsp;
  <span style="background:#ff8800"></span>3m以上 &nbsp;
  <span style="background:#2266ff"></span>1m以上 &nbsp;
  <span style="background:#aa44aa"></span>1m未満
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script>
const LINES = {lines_json};

// Scene setup
const W = window.innerWidth, H = {canvas_height};
const renderer = new THREE.WebGLRenderer({{ antialias: true }});
renderer.setSize(W, H);
renderer.setPixelRatio(window.devicePixelRatio);
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1a1a2e);

const camera = new THREE.PerspectiveCamera(45, W / H, 0.01, 1000);
camera.position.set(0, 0, 30);

// Grid helper
const grid = new THREE.GridHelper(40, 20, 0x333355, 0x222244);
grid.rotation.x = 0;
scene.add(grid);

// Add lines
const lineObjs = [];
LINES.forEach(ln => {{
  const mat = new THREE.LineBasicMaterial({{
    color: parseInt(ln.color), linewidth: 3,
  }});
  const geo = new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(ln.x1, ln.y1, 0),
    new THREE.Vector3(ln.x2, ln.y2, 0),
  ]);
  const line = new THREE.Line(geo, mat);
  line.computeLineDistances();
  line.userData = {{ id: ln.id, real_m: ln.real_m, orientation: ln.orientation }};
  scene.add(line);
  lineObjs.push(line);

  // ラベル（スプライト風テキストはCanvasで）
  const canvas2 = document.createElement("canvas");
  canvas2.width = 256; canvas2.height = 64;
  const ctx = canvas2.getContext("2d");
  ctx.fillStyle = "rgba(0,0,0,0.7)";
  ctx.roundRect(2,2,252,60,10); ctx.fill();
  ctx.fillStyle = "#" + parseInt(ln.color).toString(16).padStart(6,"0");
  ctx.font = "bold 28px sans-serif";
  ctx.fillText(ln.id + " " + ln.real_m.toFixed(2) + "m", 12, 40);
  const tex = new THREE.CanvasTexture(canvas2);
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({{ map: tex, transparent: true }}));
  const mx = (ln.x1 + ln.x2) / 2;
  const my = (ln.y1 + ln.y2) / 2;
  sprite.position.set(mx, my + 0.6, 0.1);
  sprite.scale.set(3.5, 0.9, 1);
  scene.add(sprite);
}});

// Raycaster
const raycaster = new THREE.Raycaster();
raycaster.params.Line.threshold = 0.3;
const mouse = new THREE.Vector2();
const popup = document.getElementById("popup");

renderer.domElement.addEventListener("click", e => {{
  const rect = renderer.domElement.getBoundingClientRect();
  mouse.x =  ((e.clientX - rect.left) / rect.width)  * 2 - 1;
  mouse.y = -((e.clientY - rect.top)  / rect.height) * 2 + 1;
  raycaster.setFromCamera(mouse, camera);
  const hits = raycaster.intersectObjects(lineObjs);
  if (hits.length > 0) {{
    const d = hits[0].object.userData;
    const oriMap = {{horizontal:"水平",vertical:"垂直",diagonal:"斜め"}};
    document.getElementById("p-name").textContent = d.id;
    document.getElementById("p-m").textContent   = d.real_m.toFixed(3) + " m";
    document.getElementById("p-ori").textContent = oriMap[d.orientation] || d.orientation;
    popup.style.display = "block";
    popup.style.left = (e.clientX + 12) + "px";
    popup.style.top  = (e.clientY - 10) + "px";
  }} else {{
    popup.style.display = "none";
  }}
}});

// Manual orbit (drag to rotate)
let isDragging = false, prevX = 0, prevY = 0;
let theta = 0, phi = Math.PI / 4, radius = 30;
const target = new THREE.Vector3(0, 0, 0);

function updateCamera() {{
  camera.position.x = target.x + radius * Math.sin(phi) * Math.sin(theta);
  camera.position.y = target.y + radius * Math.cos(phi);
  camera.position.z = target.z + radius * Math.sin(phi) * Math.cos(theta);
  camera.lookAt(target);
}}
updateCamera();

renderer.domElement.addEventListener("mousedown", e => {{ isDragging = true; prevX = e.clientX; prevY = e.clientY; }});
window.addEventListener("mouseup", () => isDragging = false);
window.addEventListener("mousemove", e => {{
  if (!isDragging) return;
  theta -= (e.clientX - prevX) * 0.01;
  phi    = Math.max(0.1, Math.min(Math.PI - 0.1, phi - (e.clientY - prevY) * 0.01));
  prevX = e.clientX; prevY = e.clientY;
  updateCamera();
}});
renderer.domElement.addEventListener("wheel", e => {{
  radius = Math.max(2, Math.min(100, radius + e.deltaY * 0.05));
  updateCamera();
  e.preventDefault();
}}, {{ passive: false }});

// Animate
function animate() {{
  requestAnimationFrame(animate);
  renderer.render(scene, camera);
}}
animate();
</script>
</body>
</html>"""
    return html

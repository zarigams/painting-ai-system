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

    # 実寸長で降順ソートして番号付与
    lines_info.sort(key=lambda x: x["real_m"], reverse=True)
    for _i, _ln in enumerate(lines_info, 1):
        _ln["id"] = _i

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
            label = f"#{ln_id} {ln['real_m']:.2f}m"
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
) -> str:
    """
    検出した線分から、実寸比率で再現したSVGトレースを生成する。

    Parameters
    ----------
    lines         : detect_lines_with_lengths() の lines
    scale_m_per_px: 1ピクセルあたりの実寸(m)
    svg_width     : SVGの幅(px)
    min_length_m  : この長さ未満の線は描画しない

    Returns
    -------
    SVG文字列
    """
    if not lines:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="100"><text x="10" y="50" font-size="16">検出線なし</text></svg>'

    # 描画対象フィルタ
    draw_lines = [l for l in lines if l["real_m"] >= min_length_m]

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

        # 中点ラベル（1m以上のみ）
        if ln["real_m"] >= 1.0:
            mx = (x1s + x2s) / 2
            my = (y1s + y2s) / 2
            orient = _orient_label(ln["angle_deg"])
            lbl = f"{ln['real_m']:.2f}m {orient}"
            labels_svg.append(
                f'<rect x="{mx-2:.1f}" y="{my-10:.1f}" width="{len(lbl)*7}" height="13" fill="white" opacity="0.8"/>'
                f'<text x="{mx:.1f}" y="{my:.1f}" font-size="10" fill="{col}" font-weight="bold">{lbl}</text>'
            )

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
        f'{"".join(lines_svg)}'
        f'{"".join(labels_svg)}'
        f'{legend}'
        f'</svg>'
    )
    return svg

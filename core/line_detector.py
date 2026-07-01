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

    # 実寸長で降順ソート
    lines_info.sort(key=lambda x: x["real_m"], reverse=True)

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

        # 線
        draw.line([(x1, y1), (x2, y2)], fill=col, width=2)

        # 端点マーカー
        r = 3
        draw.ellipse([(x1-r, y1-r), (x1+r, y1+r)], fill=col)
        draw.ellipse([(x2-r, y2-r), (x2+r, y2+r)], fill=col)

        # 中点ラベル（1m以上のみ）
        if ln["real_m"] >= 1.0:
            mx = (x1 + x2) // 2
            my = (y1 + y2) // 2
            label = f"{ln['real_m']:.2f}m"
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

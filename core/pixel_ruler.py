"""
pixel_ruler.py — 図面クリック計測ユーティリティ
streamlit-drawable-canvas で描いた線オブジェクトを
ピクセル距離 → 実寸（m）に変換する。

Fabric.js Line オブジェクトの形式:
  {
    "type": "line",
    "left": <center_x>,  "top": <center_y>,
    "width": <abs_dx>,   "height": <abs_dy>,
    "x1": ..., "y1": ..., "x2": ..., "y2": ...
  }
ピクセル長 = sqrt(width^2 + height^2)
"""

import math


def line_px_length(obj: dict) -> float:
    """Fabric.js Line オブジェクトからピクセル距離を算出する"""
    w = abs(obj.get("width",  0))
    h = abs(obj.get("height", 0))
    return math.sqrt(w * w + h * h)


def scale_factor(ref_obj: dict, ref_real_m: float) -> float:
    """
    基準線（既知の実寸を持つ線）からスケールファクターを求める
    Returns: meters_per_pixel
    """
    px = line_px_length(ref_obj)
    if px <= 0 or ref_real_m <= 0:
        return 0.0
    return ref_real_m / px


def px_to_m(obj: dict, mpp: float) -> float:
    """meters_per_pixel (mpp) を使ってオブジェクトを実寸（m）に変換する"""
    return round(line_px_length(obj) * mpp, 3)


LABELS = ["縮尺基準線", "南面幅", "北面幅", "東面幅", "西面幅"]
COLORS = {
    "縮尺基準線": "#9B59B6",   # 紫
    "南面幅":     "#27AE60",   # 緑
    "北面幅":     "#2980B9",   # 青
    "東面幅":     "#E67E22",   # オレンジ
    "西面幅":     "#E74C3C",   # 赤
}
STROKE_ORDER_HINT = (
    "①まず【縮尺基準線】を引いてください（図面の寸法線に合わせる）。\n"
    "②次に南面・東面の幅を引いてください（北面・西面は異なる場合のみ）。"
)

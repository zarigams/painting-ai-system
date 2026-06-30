"""
幾何学計算モジュール
立面図から読み取った高さ＋1辺の幅から、外壁・屋根面積を正確に算出する
"""

import math


def calc_geometry(
    south_width_m: float,
    east_width_m: float,
    ridge_height_m: float,
    eave_height_m: float,
    opening_deduction_rate: float = 0.85,
) -> dict:
    """主要寸法から外壁・屋根の面積を幾何学的に計算する"""
    if south_width_m <= 0 or east_width_m <= 0:
        return {"error": "幅は正の値を入力してください"}

    rise = ridge_height_m - eave_height_m
    run  = south_width_m / 2.0
    angle_rad = math.atan2(rise, run)
    angle_deg = math.degrees(angle_rad)
    koun = round(rise / run * 10, 1)
    rafter_length = math.sqrt(rise ** 2 + run ** 2)

    wall_south = south_width_m * eave_height_m
    wall_north = south_width_m * eave_height_m
    wall_east  = east_width_m  * eave_height_m
    wall_west  = east_width_m  * eave_height_m
    wall_gross = wall_south + wall_north + wall_east + wall_west
    wall_net   = wall_gross * opening_deduction_rate

    footprint = south_width_m * east_width_m
    roof_area = footprint / math.cos(angle_rad)

    return {
        "south_width_m":          round(south_width_m, 3),
        "east_width_m":           round(east_width_m, 3),
        "ridge_height_m":         round(ridge_height_m, 3),
        "eave_height_m":          round(eave_height_m, 3),
        "rise_m":                 round(rise, 3),
        "run_m":                  round(run, 3),
        "angle_deg":              round(angle_deg, 1),
        "koun":                   koun,
        "rafter_length_m":        round(rafter_length, 3),
        "wall_south_m2":          round(wall_south, 2),
        "wall_north_m2":          round(wall_north, 2),
        "wall_east_m2":           round(wall_east, 2),
        "wall_west_m2":           round(wall_west, 2),
        "wall_gross_m2":          round(wall_gross, 2),
        "opening_deduction_rate": opening_deduction_rate,
        "wall_net_m2":            round(wall_net, 2),
        "footprint_m2":           round(footprint, 2),
        "roof_area_m2":           round(roof_area, 2),
    }


def pixel_to_meter(known_px: float, known_m: float, target_px: float) -> float:
    """ピクセル比から実寸を換算する"""
    if known_px <= 0:
        return 0.0
    return round(known_m / known_px * target_px, 3)

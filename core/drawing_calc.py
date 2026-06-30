"""
幾何学計算モジュール
立面図から読み取った各面の幅・高さから、外壁・屋根面積を正確に算出する
4面個別入力対応（南≠北・東≠西 の非矩形建物にも対応）
"""

import math


def calc_geometry_4face(
    south_width_m: float,
    north_width_m: float,
    east_width_m: float,
    west_width_m: float,
    ridge_height_m: float,
    eave_height_m: float,
    south_opening_m2: float = 0.0,
    north_opening_m2: float = 0.0,
    east_opening_m2: float = 0.0,
    west_opening_m2: float = 0.0,
    opening_deduction_rate: float = 0.15,
    angle_rad_override: float = None,  # 直接指定する場合（勾配直接入力時）
    eave_overhang_m: float = 0.0,      # 軒の出（片側, m）。屋根フットプリントに加算
) -> dict:
    """
    各面の幅を個別に受け取り、外壁・屋根面積を幾何学的に算出する。

    Parameters
    ----------
    south/north/east/west_width_m : 各面の幅（m）。north/west が 0 の場合は south/east と同値とみなす
    ridge_height_m                : 棟高（GL〜棟まで, m）
    eave_height_m                 : 軒高（GL〜軒まで, m）
    *_opening_m2                  : 各面の開口（窓・玄関等）合計面積（㎡）。0 の場合は opening_deduction_rate で一律控除
    opening_deduction_rate        : 一律開口控除率（デフォルト15%）
    """
    if any(w <= 0 for w in [south_width_m, east_width_m]):
        return {"error": "南面・東面の幅は正の値を入力してください"}

    # north/west 未入力の場合は south/east と同値
    n_w = north_width_m if north_width_m > 0 else south_width_m
    w_w = west_width_m  if west_width_m  > 0 else east_width_m

    # --- 高さ・勾配 ---
    eave_h = eave_height_m
    rise   = ridge_height_m - eave_height_m
    run_s  = south_width_m / 2.0
    if angle_rad_override is not None and angle_rad_override > 0:
        angle_rad = angle_rad_override
    else:
        angle_rad = math.atan2(rise, run_s)
    angle_deg = round(math.degrees(angle_rad), 1)
    koun      = round(math.tan(angle_rad) * 10, 1)
    rafter_length = round(run_s / math.cos(angle_rad), 3)

    # --- 外壁（各面の計算） ---
    def _net(gross, opening_m2):
        if opening_m2 > 0:
            return max(gross - opening_m2, 0.0)
        return gross * (1.0 - opening_deduction_rate)

    sg = round(south_width_m * eave_h, 2)
    ng = round(n_w           * eave_h, 2)
    eg = round(east_width_m  * eave_h, 2)
    wg = round(w_w           * eave_h, 2)

    sn = round(_net(sg, south_opening_m2), 2)
    nn = round(_net(ng, north_opening_m2), 2)
    en = round(_net(eg, east_opening_m2),  2)
    wn = round(_net(wg, west_opening_m2),  2)

    wall_gross = round(sg + ng + eg + wg, 2)
    wall_net   = round(sn + nn + en + wn, 2)
    opening_total = round(south_opening_m2 + north_opening_m2 + east_opening_m2 + west_opening_m2, 2)

    # --- 屋根（平均幅で寄棟フットプリントを近似、軒の出を加算） ---
    overhang2 = eave_overhang_m * 2.0   # 両側分
    avg_ns    = (south_width_m + n_w) / 2.0 + overhang2
    avg_ew    = (east_width_m  + w_w) / 2.0 + overhang2
    footprint = round(avg_ns * avg_ew, 2)
    roof_area = round(footprint / math.cos(angle_rad), 2) if angle_rad < math.pi / 2 else 0.0

    return {
        "south_width_m":          round(south_width_m, 3),
        "north_width_m":          round(n_w, 3),
        "east_width_m":           round(east_width_m, 3),
        "west_width_m":           round(w_w, 3),
        "ridge_height_m":         round(ridge_height_m, 3),
        "eave_height_m":          round(eave_h, 3),
        "rise_m":                 round(rise, 3),
        "run_m":                  round(run_s, 3),
        "angle_deg":              angle_deg,
        "koun":                   koun,
        "rafter_length_m":        rafter_length,
        # 外壁
        "wall_south_gross":       sg,
        "wall_north_gross":       ng,
        "wall_east_gross":        eg,
        "wall_west_gross":        wg,
        "wall_gross_total":       wall_gross,
        "wall_south_net":         sn,
        "wall_north_net":         nn,
        "wall_east_net":          en,
        "wall_west_net":          wn,
        "wall_net_total":         wall_net,
        "opening_total_m2":       opening_total,
        "opening_deduction_rate": opening_deduction_rate,
        # 屋根
        "avg_ns_m":               round(avg_ns, 3),
        "avg_ew_m":               round(avg_ew, 3),
        "eave_overhang_m":        eave_overhang_m,
        "footprint_m2":           footprint,
        "roof_area_m2":           roof_area,
        # 後方互換
        "wall_net_m2":            wall_net,
        "wall_gross_m2":          wall_gross,
    }


def calc_geometry(
    south_width_m: float,
    east_width_m: float,
    ridge_height_m: float,
    eave_height_m: float,
    opening_deduction_rate: float = 0.85,
) -> dict:
    """後方互換ラッパー（南=北、東=西 の矩形建物を仮定）"""
    return calc_geometry_4face(
        south_width_m=south_width_m,
        north_width_m=south_width_m,
        east_width_m=east_width_m,
        west_width_m=east_width_m,
        ridge_height_m=ridge_height_m,
        eave_height_m=eave_height_m,
        opening_deduction_rate=1.0 - opening_deduction_rate,
    )


def pixel_to_meter(known_px: float, known_m: float, target_px: float) -> float:
    if known_px <= 0:
        return 0.0
    return round(known_m / known_px * target_px, 3)

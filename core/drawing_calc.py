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


def distribute_roof_area(
    roof_area_m2: float,
    geo: dict,
    roof_shape: str = "寄棟",
) -> dict:
    """
    屋根総面積を各面に分配する。

    Parameters
    ----------
    roof_area_m2 : calc_geometry_4face() の roof_area_m2
    geo          : calc_geometry_4face() の戻り値
    roof_shape   : "切妻（南北棟）" / "切妻（東西棟）" / "寄棟"
                   / "片流れ（南）" / "片流れ（北）" / "片流れ（東）" / "片流れ（西）"

    Returns
    -------
    dict : {"east": float, "west": float, "south": float, "north": float}
    """
    s_w = geo.get("south_width_m", 1.0)
    n_w = geo.get("north_width_m", s_w)
    e_w = geo.get("east_width_m",  1.0)
    w_w = geo.get("west_width_m",  e_w)

    angle_deg = geo.get("angle_deg", 20.0)
    cos_a = max(math.cos(math.radians(angle_deg)), 0.001)

    if roof_shape == "切妻（南北棟）":
        # 棟がEW方向 → 南・北 2 面だけ
        avg_ew = geo.get("avg_ew_m", (e_w + w_w) / 2)
        s_area = round(avg_ew * (s_w / 2) / cos_a, 2)
        n_area = round(avg_ew * (n_w / 2) / cos_a, 2)
        return {"south": s_area, "north": n_area, "east": 0.0, "west": 0.0}

    elif roof_shape == "切妻（東西棟）":
        # 棟がNS方向 → 東・西 2 面だけ
        avg_ns = geo.get("avg_ns_m", (s_w + n_w) / 2)
        e_area = round(avg_ns * (e_w / 2) / cos_a, 2)
        w_area = round(avg_ns * (w_w / 2) / cos_a, 2)
        return {"south": 0.0, "north": 0.0, "east": e_area, "west": w_area}

    elif roof_shape.startswith("片流れ"):
        # 1 面に全量
        face_map = {"南": "south", "北": "north", "東": "east", "西": "west"}
        face_char = roof_shape.split("（")[-1].rstrip("）") if "（" in roof_shape else "南"
        f = face_map.get(face_char, "south")
        result = {"south": 0.0, "north": 0.0, "east": 0.0, "west": 0.0}
        result[f] = round(roof_area_m2, 2)
        return result

    else:
        # 寄棟 or その他 → 全 4 面に外周幅の比で分配
        total_w = s_w + n_w + e_w + w_w
        if total_w <= 0:
            each = round(roof_area_m2 / 4, 2)
            return {"south": each, "north": each, "east": each, "west": each}
        return {
            "south": round(roof_area_m2 * s_w / total_w, 2),
            "north": round(roof_area_m2 * n_w / total_w, 2),
            "east":  round(roof_area_m2 * e_w / total_w, 2),
            "west":  round(roof_area_m2 * w_w / total_w, 2),
        }

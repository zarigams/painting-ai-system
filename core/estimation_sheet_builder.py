"""
積算集計表ビルダー
4面（東西南北）別の寸法データを受け取り、積算集計表の全項目を算出する
"""

from __future__ import annotations

FACES = ["east", "west", "south", "north"]
FACE_LABEL = {"east": "東面", "west": "西面", "south": "南面", "north": "北面"}

# Excelの列マッピング（面ごとの: 数量列, 開口部列, 計列, 単位列）
FACE_COLS = {
    "east":  (4, 5, 6, 7),    # D, E, F, G
    "west":  (8, 9, 10, 11),  # H, I, J, K
    "south": (12, 13, 14, 15),# L, M, N, O
    "north": (16, 17, 18, 19),# P, Q, R, S
}

# Excelの行マッピング（項目key: 行番号）
ROW_MAP = {
    "scaffold":         5,
    "roof":             6,
    "toplight_seal":    7,
    "roof_iron":        8,
    "fascia":           9,
    "soffit":          10,
    "entrance_soffit": 12,
    "veranda_soffit":  13,
    "soffit_total":    14,
    "wall_mortar":     16,
    "wall_siding":     17,
    "sb":              19,
    "base_cut":        21,
    "mid_cut":         22,
    "veranda_cut":     23,
    "cut_total":       24,
    "foundation":      26,
    "window_top":      27,
    "beam":            29,
    "deco_frame":      30,
    "hisashi":         32,
    "gutter":          34,
    "kirigoshi":       35,
    "shutter_large":   37,
    "shutter_small":   38,
    "opening_seal":    40,
    "joint_seal":      41,
}


def _r(v):
    return round(float(v or 0), 3)


def build_estimation_data(geo: dict, face_inputs: dict, project: dict) -> dict:
    """
    幾何計算結果と面別付帯部入力から積算集計表の全データを生成する。

    Parameters
    ----------
    geo : calc_geometry_4face() の戻り値
    face_inputs : dict  face -> dict of per-face values
    project : dict with client_name, site_address, etc.
    """
    face_data = {}
    for f in FACES:
        fi = dict(face_inputs.get(f, {}))
        # 外壁は geo から
        fi["wall_siding_gross_m2"]   = _r(geo.get(f"wall_{f}_gross", 0))
        fi["wall_siding_opening_m2"] = _r(geo.get(f"wall_{f}_gross", 0) - geo.get(f"wall_{f}_net", 0))
        fi["wall_siding_net_m2"]     = _r(geo.get(f"wall_{f}_net", 0))
        # 屋根
        roof_g = _r(fi.get("roof_m2", 0))
        roof_o = _r(fi.get("roof_opening_m2", 0))
        fi["roof_gross_m2"] = roof_g
        fi["roof_net_m2"]   = max(_r(roof_g - roof_o), 0.0)
        # 合計項目
        fi["soffit_total_m2"] = _r(fi.get("entrance_soffit_m2", 0) + fi.get("veranda_soffit_m2", 0))
        fi["cut_total_m"]     = _r(fi.get("base_cut_m", 0) + fi.get("mid_cut_m", 0) + fi.get("veranda_cut_m", 0))
        face_data[f] = fi

    def _row(key, label, unit, gross_key, net_key=None, opening_key=None):
        r = {"key": key, "label": label, "unit": unit, "total": 0.0, "faces": {}}
        for f in FACES:
            g = _r(face_data[f].get(gross_key, 0))
            o = _r(face_data[f].get(opening_key, 0)) if opening_key else 0.0
            n = _r(face_data[f].get(net_key, 0)) if net_key else g
            r["faces"][f] = {"gross": g, "opening": o, "net": n}
        r["total"] = _r(sum(r["faces"][f]["net" if net_key else "gross"] for f in FACES))
        return r

    rows = [
        _row("scaffold",        "足場",               "㎡", "scaffold_m2"),
        _row("roof",            "屋根",               "㎡", "roof_gross_m2", "roof_net_m2", "roof_opening_m2"),
        _row("toplight_seal",   "トップライト廻りシール","m",  "toplight_seal_m"),
        _row("roof_iron",       "屋根取合鉄部",       "m",  "roof_iron_m"),
        _row("fascia",          "破風・鼻隠",         "m",  "fascia_m"),
        _row("soffit",          "軒天",               "㎡", "soffit_m2"),
        _row("entrance_soffit", "玄関庇軒天",         "㎡", "entrance_soffit_m2"),
        _row("veranda_soffit",  "ベランダ軒天",       "㎡", "veranda_soffit_m2"),
        _row("soffit_total",    "軒天合計",           "㎡", "soffit_total_m2"),
        _row("wall_mortar",     "外壁モルタル部",     "㎡", "wall_mortar_m2"),
        _row("wall_siding",     "外壁サイディング部", "㎡",
             "wall_siding_gross_m2", "wall_siding_net_m2", "wall_siding_opening_m2"),
        _row("sb",              "SB",                "m",  "sb_m"),
        _row("base_cut",        "土台水切",           "m",  "base_cut_m"),
        _row("mid_cut",         "中間水切",           "m",  "mid_cut_m"),
        _row("veranda_cut",     "ベランダ水切",       "m",  "veranda_cut_m"),
        _row("cut_total",       "水切合計",           "m",  "cut_total_m"),
        _row("foundation",      "基礎",               "㎡", "foundation_m2"),
        _row("window_top",      "出窓天端鉄部",       "m",  "window_top_m"),
        _row("beam",            "付梁",               "m",  "beam_m"),
        _row("deco_frame",      "化粧窓枠",           "m",  "deco_frame_m"),
        _row("hisashi",         "庇",                "m",  "hisashi_m"),
        _row("gutter",          "雨樋",               "m",  "gutter_m"),
        _row("kirigoshi",       "霧除",               "m",  "kirigoshi_m"),
        _row("shutter_large",   "雨戸・戸袋（大）",   "枚", "shutter_large"),
        _row("shutter_small",   "雨戸・戸袋（小）",   "枚", "shutter_small"),
        _row("opening_seal",    "開口部廻りシール",   "m",  "opening_seal_m"),
        _row("joint_seal",      "目地シール",         "m",  "joint_seal_m"),
    ]

    return {
        "header": {
            "client_name":   project.get("client_name", ""),
            "site_address":  project.get("site_address", ""),
            "building_type": project.get("building_type", ""),
            "roof_type":     project.get("roof_type", ""),
            "company":       project.get("company_name", ""),
            "sales_rep":     project.get("sales_rep", ""),
        },
        "rows": rows,
        "face_data": face_data,
    }


def make_empty_face_inputs() -> dict:
    """入力フォームの初期値（全0）を返す"""
    template = {
        "roof_m2": 0.0, "roof_opening_m2": 0.0,
        "toplight_seal_m": 0.0, "roof_iron_m": 0.0,
        "fascia_m": 0.0, "soffit_m2": 0.0,
        "entrance_soffit_m2": 0.0, "veranda_soffit_m2": 0.0,
        "wall_mortar_m2": 0.0, "scaffold_m2": 0.0,
        "sb_m": 0.0, "base_cut_m": 0.0, "mid_cut_m": 0.0, "veranda_cut_m": 0.0,
        "foundation_m2": 0.0, "window_top_m": 0.0, "beam_m": 0.0,
        "deco_frame_m": 0.0, "hisashi_m": 0.0,
        "gutter_m": 0.0, "kirigoshi_m": 0.0,
        "shutter_large": 0, "shutter_small": 0,
        "opening_seal_m": 0.0, "joint_seal_m": 0.0,
    }
    return {f: dict(template) for f in FACES}

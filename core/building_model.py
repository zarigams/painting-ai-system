"""
Building Model ビルダー v1.0

drawing_analyzer.analyze_with_annotations() の出力から
Building_Model_v1.0.md スキーマに準拠した dict を生成する。

制約(Building_Model_v1.0.md Section 4-1 準拠):
- v1.0スコープ: 現在の analyze_with_annotations() で取得できるフィールドのみ実装
- 値が取得できない項目は推測値で埋めず null にする
- デフォルト高さ(6.5, 8.693)は Building Model の確定値として入れない
- GPT自己申告confidence は _meta に保持するだけでフィールドには使わない
- フォールバック値を使う場合は source と basis でフォールバックと分かるようにする

面幅の取得優先順位 (4面共通):
  1. annotations[label='<面>面幅']  → source='GPT読取(annotations)',  confidence=annotationの値
  2. raw_gpt_json.faces.<face>.width → source='GPT読取(faces.width)', confidence='中'
  3. 対向面の対称仮定              → source='計算(対称仮定フォールバック)', confidence='低'
  4. null                          → confidence='不明'
  0・負数・数値変換不能は採用しない。annotationsがあればfaces.widthで上書きしない。
"""

from __future__ import annotations
import re


def _field(value, confidence, source, basis, position=None):
    d = {"value": value, "confidence": confidence, "source": source, "basis": basis}
    if position is not None:
        d["position"] = position
    return d


def _null_field(basis=None):
    return _field(None, "不明", None, basis)


def _conf_jp(raw):
    return {"high": "高", "medium": "中", "low": "低"}.get(raw, "不明")


def _extract_annotation(label_keyword, annotations, category=None):
    if not annotations:
        return None
    for ann in annotations:
        if label_keyword in ann.get("label", ""):
            if category is None or ann.get("category") == category:
                return ann
    if category:
        for ann in annotations:
            if label_keyword in ann.get("label", ""):
                return ann
    return None


def _ann_to_field(label_keyword, annotations, category=None, include_position=True):
    """annotations から指定キーワードのフィールドを生成。取得できなければ None を返す。"""
    ann = _extract_annotation(label_keyword, annotations, category)
    if ann is None:
        return None
    raw_conf   = ann.get("confidence", "")
    confidence = _conf_jp(raw_conf)
    label      = ann.get("label", label_keyword)
    unit       = ann.get("unit", "")
    try:
        value = float(ann["value"])
    except (KeyError, TypeError, ValueError):
        return None
    if value <= 0:
        return None
    position = None
    if include_position:
        pos_keys = ["x_pct", "y_pct", "x1_pct", "x2_pct"]
        pos = {k: ann[k] for k in pos_keys if k in ann}
        if pos:
            position = pos
    basis = "図面 annotations label='{}' value={}{}".format(label, ann.get("value"), unit)
    return _field(value, confidence, "GPT読取(annotations)", basis, position)


def _faces_width_field(face_key, faces_dict):
    """raw_gpt_json.faces.<face_key>.width からフィールドを生成。取得できなければ None。"""
    if not faces_dict or face_key not in faces_dict:
        return None
    raw_w = faces_dict[face_key].get("width") if isinstance(faces_dict.get(face_key), dict) else None
    if raw_w is None:
        return None
    try:
        value = float(raw_w)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return _field(value, "中", "GPT読取(faces.width)",
                  "GPT faces.{}.width = {}m".format(face_key, raw_w))


def _symmetric_width_field(opposite_field, opposite_face_label):
    """対向面から対称仮定フィールドを生成。対向面が null なら None。"""
    if opposite_field is None or opposite_field.get("value") is None:
        return None
    val = opposite_field["value"]
    return _field(val, "低", "計算(対称仮定フォールバック)",
                  "{}={}m から対称仮定。L字・凹凸建物では誤差あり".format(opposite_face_label, val))


def _resolve_face_width(face_key, label_jp, annotations, faces_dict,
                         opposite_field=None, opposite_label=None):
    """4面共通の面幅取得ロジック: annotations → faces.width → 対称仮定 → null"""
    field = _ann_to_field(label_jp, annotations, category="width")
    if field is not None:
        return field
    field = _faces_width_field(face_key, faces_dict)
    if field is not None:
        return field
    if opposite_field is not None and opposite_label is not None:
        field = _symmetric_width_field(opposite_field, opposite_label)
        if field is not None:
            return field
    reasons = ["annotations に '{}' が存在しない".format(label_jp),
               "faces.{}.width が取得できない or 0以下".format(face_key)]
    if opposite_field is not None and opposite_field.get("value") is None:
        reasons.append("対向面（{}）も null のため対称仮定不可".format(opposite_label))
    return _null_field(" / ".join(reasons))


def _detect_roof_shape(notes):
    if not notes:
        return _null_field("notesが空またはnull。専用フィールドなし")
    for shape in ["寄棟", "切妻", "片流れ", "陸屋根", "入母屋"]:
        if shape in notes:
            excerpt = notes[:80] + ("..." if len(notes) > 80 else "")
            return _field(shape, "中", "GPT読取(notes解析)",
                          "notesに '{}' を検出: '{}'".format(shape, excerpt))
    excerpt = notes[:80] + ("..." if len(notes) > 80 else "")
    return _null_field("notesに屋根形状キーワードなし: '{}'".format(excerpt))


def build_building_model(raw_gpt_json, annotations):
    """
    drawing_analyzer.analyze_with_annotations() の出力から
    Building Model v1.0 スキーマに準拠した dict を生成する。
    """
    if annotations is None:
        annotations = []

    faces_dict = raw_gpt_json.get("faces") or {}

    # ── 1. building_info ─────────────────────────────────────────────────────
    bt_raw = raw_gpt_json.get("building_type")
    building_type_field = (
        _field(str(bt_raw), "中", "GPT読取(top-level)", "building_type={!r}".format(bt_raw))
        if bt_raw else _null_field("building_type フィールドなし or null")
    )
    st_raw = raw_gpt_json.get("structure")
    structure_field = (
        _field(str(st_raw), "中", "GPT読取(top-level)", "structure={!r}".format(st_raw))
        if st_raw else _null_field("structure フィールドなし or null")
    )
    fl_raw = raw_gpt_json.get("floors")
    try:
        fl_val = int(fl_raw) if fl_raw is not None else None
    except (TypeError, ValueError):
        fl_val = None
    floors_field = (
        _field(fl_val, "高", "GPT読取(top-level)", "floors={!r}".format(fl_raw))
        if fl_val is not None else _null_field("floors フィールドなし or null")
    )
    building_info = {
        "building_type": building_type_field,
        "structure":     structure_field,
        "floors":        floors_field,
        "wall_material": _null_field("プロンプトに項目なし。立面図にも記載なし"),
    }

    # ── 2. faces(南北東西) ───────────────────────────────────────────────────
    south_width_field = _resolve_face_width("south", "南面幅", annotations, faces_dict)
    east_width_field  = _resolve_face_width("east",  "東面幅", annotations, faces_dict)
    north_width_field = _resolve_face_width("north", "北面幅", annotations, faces_dict,
                                             opposite_field=south_width_field, opposite_label="南面幅")
    west_width_field  = _resolve_face_width("west",  "西面幅", annotations, faces_dict,
                                             opposite_field=east_width_field,  opposite_label="東面幅")

    eave_h_ann = _extract_annotation("軒高", annotations, category="height")
    if eave_h_ann:
        try:
            eave_h_val = float(eave_h_ann["value"])
        except (KeyError, TypeError, ValueError):
            eave_h_val = None
        eave_height_field = _field(
            eave_h_val, _conf_jp(eave_h_ann.get("confidence", "")),
            "GPT読取(annotations)",
            "図面 annotations label='{}' value={}{}".format(
                eave_h_ann.get("label", "軒高"), eave_h_ann.get("value"), eave_h_ann.get("unit", "")),
        )
    else:
        eave_height_field = _null_field("annotations に '軒高' が存在しない")

    _eave_overhang_tmpl  = _null_field("プロンプトに項目なし。v1.0ではデフォルト値を入れない")
    _has_lower_roof_tmpl = _null_field("プロンプトに項目なし。v1.0では人入力で対応")

    def _make_face(width_field):
        return {
            "width":          width_field,
            "eave_height":    dict(eave_height_field),
            "eave_overhang":  dict(_eave_overhang_tmpl),
            "has_lower_roof": dict(_has_lower_roof_tmpl),
        }

    faces = {
        "south": _make_face(south_width_field),
        "north": _make_face(north_width_field),
        "east":  _make_face(east_width_field),
        "west":  _make_face(west_width_field),
    }

    # ── 3. roof ──────────────────────────────────────────────────────────────
    ridge_height_field = _ann_to_field("棟高", annotations, category="height", include_position=True)
    if ridge_height_field is None:
        ridge_height_field = _null_field("annotations に '棟高' が存在しない")

    roof = {
        "ridge_height": ridge_height_field,
        "shape":        _detect_roof_shape(raw_gpt_json.get("notes")),
        "slope_sun":    _null_field("立面図に勾配数値なし。v1.0では固定係数で代替"),
        "material":     _null_field("プロンプトに項目なし。v1.0では取得しない"),
        "ridge_length": _null_field("立面図に記載なし。平面図から計算可能性あり(将来)"),
    }

    # ── 4. openings ──────────────────────────────────────────────────────────
    openings = {
        "summary": {
            face: {"total_area_sqm": _null_field("取得不可。現在は15%一律控除で代替。建具表が必要")}
            for face in ["south", "north", "east", "west"]
        },
        "items": [],
    }

    # ── 5. soffit ────────────────────────────────────────────────────────────
    soffit = {
        "present":                  _null_field("プロンプトに項目なし。v1.0では取得しない"),
        "standard_area_sqm":        _null_field("v1.0対象外(not_applicable)。積算集計表 行10対応はv2.0以降"),
        "entrance_canopy_area_sqm": _null_field("v1.0では人入力必須。玄関庇軒天面積(㎡)。積算集計表 行12対応"),
        "balcony_area_sqm":         _null_field("v1.0では人入力必須。ベランダ軒天面積(㎡)。積算集計表 行13対応"),
        "estimate_length_m":        _null_field("v1.0では人入力必須。見積書内訳 行30対応。単位m"),
        "calculation_basis":        None,
    }

    # ── 6. fascia ────────────────────────────────────────────────────────────
    fascia = {
        "present":           _null_field("プロンプトに項目なし。v1.0では取得しない"),
        "length_m":          _null_field("立面図に数値なし。v1.0では人入力必須"),
        "calculation_basis": None,
    }

    # ── 7. gutter ────────────────────────────────────────────────────────────
    gutter = {
        "present":           _null_field("プロンプトに項目なし。立面図に明確な描画なし"),
        "tate_length_m":     _null_field("v1.0では人入力必須"),
        "noki_length_m":     _null_field("住吉屋邸データでも分離できていない。将来追加"),
        "calculation_basis": None,
    }

    # ── 8. water_cutoff ──────────────────────────────────────────────────────
    s_w = south_width_field.get("value")
    n_w = north_width_field.get("value")
    e_w = east_width_field.get("value")
    w_w = west_width_field.get("value")

    def _src_abbr(field):
        src = field.get("source") or ""
        if "annotations" in src: return "ann"
        if "faces.width"  in src: return "faces"
        if "対称仮定"      in src: return "sym"
        return "?"

    if s_w is not None and e_w is not None:
        n_calc = n_w if n_w is not None else s_w
        w_calc = w_w if w_w is not None else e_w
        n_src  = _src_abbr(north_width_field) if n_w is not None else "null→sym"
        w_src  = _src_abbr(west_width_field)  if w_w is not None else "null→sym"
        perimeter = round(s_w + n_calc + e_w + w_calc, 2)
        wc_basis = "south[{s}]({sw}) + north[{n}]({nw}) + east[{e}]({ew}) + west[{w}]({ww}) = {p}m".format(
            s=_src_abbr(south_width_field), sw=s_w,
            n=n_src, nw=n_calc,
            e=_src_abbr(east_width_field),  ew=e_w,
            w=w_src, ww=w_calc, p=perimeter,
        )
        perimeter_field = _field(perimeter, "低", "計算(faces幅から)", wc_basis)
    else:
        perimeter_field = _null_field("south または east の面幅が取得できないため計算不可")

    water_cutoff = {
        "perimeter_m":       perimeter_field,
        "exclusion_m":       _null_field("玄関・勝手口等の除外長さ。算出ルール未確認"),
        "calculation_basis": None,
    }

    # ── 9. special_parts ─────────────────────────────────────────────────────
    notes = raw_gpt_json.get("notes") or ""
    if notes and re.search(r"バルコニー|ベランダ", notes):
        excerpt = notes[:60] + ("..." if len(notes) > 60 else "")
        balcony_present_field = _field(True, "中", "GPT読取(notes解析)",
                                       "notesに 'バルコニー/ベランダ' を検出: '{}'".format(excerpt))
    else:
        balcony_present_field = _field(None, "不明", None,
                                       "notesにバルコニー/ベランダキーワードなし" if notes else "notesが空またはnull")

    special_parts = {
        "balcony": {
            "present": balcony_present_field,
            "face":    _null_field("専用フィールドなし。v1.0では取得しない"),
            "width_m": _null_field("立面図に寸法なし"),
            "depth_m": _null_field("立面図に寸法なし"),
        }
    }

    # ── _meta ────────────────────────────────────────────────────────────────
    # 1F天井高はBuilding Model v1.0本体に専用フィールドなし。
    # Step Bで幾何計算に必要と確定するまで raw_annotations に全件保持する。
    _meta = {
        "gpt_overall_confidence":       raw_gpt_json.get("confidence"),
        "annotation_count":             len(annotations),
        "raw_gpt_keys":                 list(raw_gpt_json.keys()),
        "gpt_reported_total_wall_area": (
            raw_gpt_json.get("total_wall_area")
            or (raw_gpt_json.get("faces") or {}).get("total_wall_area")
            or raw_gpt_json.get("exterior_wall_area")
        ),
        "gpt_reported_roof_area":       raw_gpt_json.get("roof_area"),
        "raw_annotations":              [dict(a) for a in annotations],
    }

    return {
        "_schema":       "Building_Model_v1.0",
        "_meta":         _meta,
        "building_info": building_info,
        "faces":         faces,
        "roof":          roof,
        "openings":      openings,
        "soffit":        soffit,
        "fascia":        fascia,
        "gutter":        gutter,
        "water_cutoff":  water_cutoff,
        "special_parts": special_parts,
    }

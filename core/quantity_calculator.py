"""
数量計算モジュール
数量フォームデータ × 単価表 → 積算明細を生成（AI不要）
サンプル（住吉屋邸）の単価を基準にしています
"""

# ─── 標準単価表（サンプル実績値）────────────────────────────
UNIT_PRICES = {
    # 仮設工事
    "外部足場":           1050,   # ㎡
    "屋根足場":           850,    # ㎡
    "昇降設備":           15000,  # 式
    "運搬費":             35000,  # 式
    "道路使用許可":       15000,  # 式
    "ガードマン":         24000,  # 人
    "防護管":             80000,  # 式
    # 屋根塗装
    "屋根高圧洗浄":       200,    # ㎡
    "屋根板金塗装":       38000,  # 式
    "屋根塗装":           2200,   # ㎡
    "縁切り":             250,    # ㎡
    # 外壁塗装
    "外壁高圧洗浄":       150,    # ㎡
    "外壁塗装":           4200,   # ㎡
    # 付帯部
    "土台水切塗装":       650,    # m
    "出窓天端塗装":       1700,   # m
    "化粧梁付梁塗装":     750,    # m
    "破風鼻隠し塗装":     750,    # m
    "軒天塗装_m":         950,    # m（破風m合わせ）
    "軒天塗装_sqm":       950,    # ㎡（玄関・バルコニー）
    "雨樋塗装":           650,    # m
    "シャッターボックス": 1700,   # m
    "基礎塗装":           60000,  # 式
    # シーリング
    "目地シーリング":     1150,   # m
    "雑シーリング":       30000,  # 式
    "トップライト":       5000,   # 箇所
    # 諸経費
    "諸経費":             200000, # 式（デフォルト）
}


def _item(category, name, qty, unit, unit_price, notes=""):
    """積算明細アイテムを生成するヘルパー"""
    amount = round(float(qty) * float(unit_price))
    return {
        "category": category,
        "item_name": name,
        "quantity": float(qty),
        "unit": unit,
        "unit_price": int(unit_price),
        "amount": amount,
        "estimated": False,
        "needs_confirmation": False,
        "notes": notes,
    }


def calculate_from_quantities(
    quantities: dict,
    client_name: str = "",
    site_address: str = "",
    sales_rep: str = "",
) -> dict:
    """
    数量フォームデータから積算明細を計算する

    Args:
        quantities: 数量フォームデータ（app.pyのsession_state.quantities）
        client_name: お客様名
        site_address: 現場住所
        sales_rep: 担当者名

    Returns:
        estimation dict（estimation_items, subtotal, tax_amount, total 等）
    """
    q = quantities
    items = []
    UP = UNIT_PRICES

    # ─── 仮設工事 ──────────────────────────────────────────
    if q.get("scaffold_area", 0) > 0:
        items.append(_item(
            "仮設工事", "外部足場",
            q["scaffold_area"], "㎡", UP["外部足場"],
            "くさび緊結式足場本足場　手摺２段",
        ))
    if q.get("roof_scaffold_area", 0) > 0:
        items.append(_item(
            "仮設工事", "屋根足場",
            q["roof_scaffold_area"], "㎡", UP["屋根足場"],
            q.get("roof_type", "スレート"),
        ))
    if q.get("do_lifting", True):
        items.append(_item("仮設工事", "昇降設備", 1, "式", UP["昇降設備"]))
    if q.get("do_transport", True):
        items.append(_item(
            "仮設工事", "運搬費", 1, "式", UP["運搬費"], "場内小運搬込み"
        ))
    if q.get("do_road_permit", True):
        items.append(_item("仮設工事", "道路使用許可申請費", 1, "式", UP["道路使用許可"]))
    if q.get("guardman_count", 0) > 0:
        items.append(_item(
            "仮設工事", "ガードマン",
            q["guardman_count"], "人", UP["ガードマン"],
        ))
    if q.get("do_protection_pipe", False):
        items.append(_item("仮設工事", "防護管設置費用", 1, "式", UP["防護管"]))

    # ─── 塗装工事（屋根） ──────────────────────────────────
    if q.get("do_roof", True) and q.get("roof_area", 0) > 0:
        roof_area = q["roof_area"]
        roof_spec = q.get("roof_paint_spec", "クールタイトSi")
        items.append(_item(
            "塗装工事", "屋根高圧洗浄",
            roof_area, "㎡", UP["屋根高圧洗浄"],
        ))
        items.append(_item(
            "塗装工事", "屋根板金塗装",
            1, "式", UP["屋根板金塗装"],
            f"ケレン+錆止め　{q.get('sub_paint_spec', 'クリーンマイルドシリコン')}",
        ))
        items.append(_item(
            "塗装工事", "屋根塗装",
            roof_area, "㎡", UP["屋根塗装"],
            f"マイルドシーラーエポ　{roof_spec}",
        ))
        items.append(_item(
            "塗装工事", "縁切り",
            roof_area, "㎡", UP["縁切り"],
        ))

    # ─── 塗装工事（外壁） ──────────────────────────────────
    if q.get("wall_area", 0) > 0:
        wall_area = q["wall_area"]
        wall_spec = q.get("wall_paint_spec", "ラジカル塗料")
        sub_spec  = q.get("sub_paint_spec", "クリーンマイルドシリコン")
        items.append(_item(
            "塗装工事", "外壁高圧洗浄",
            wall_area, "㎡", UP["外壁高圧洗浄"],
        ))
        items.append(_item(
            "塗装工事", "外壁塗装",
            wall_area, "㎡", UP["外壁塗装"],
            f"ミラクシーラーエコ　{wall_spec}",
        ))

    # ─── 塗装工事（付帯部） ────────────────────────────────
    sub = q.get("sub_paint_spec", "クリーンマイルドシリコン")
    ケレン錆止め = f"ケレン+錆止め　{sub}"

    if q.get("water_cutoff_length", 0) > 0:
        items.append(_item(
            "塗装工事", "土台水切塗装",
            q["water_cutoff_length"], "ｍ", UP["土台水切塗装"], ケレン錆止め,
        ))
    if q.get("window_top_length", 0) > 0:
        items.append(_item(
            "塗装工事", "出窓天端塗装",
            q["window_top_length"], "ｍ", UP["出窓天端塗装"], ケレン錆止め,
        ))
    if q.get("beam_length", 0) > 0:
        items.append(_item(
            "塗装工事", "化粧梁・付梁塗装",
            q["beam_length"], "ｍ", UP["化粧梁付梁塗装"], sub,
        ))
    if q.get("fascia_length", 0) > 0:
        items.append(_item(
            "塗装工事", "破風・鼻隠し塗装",
            q["fascia_length"], "ｍ", UP["破風鼻隠し塗装"], sub,
        ))
    # 軒天（m換算）
    soffit_len = q.get("soffit_length", 0) or q.get("fascia_length", 0)
    if soffit_len > 0:
        items.append(_item(
            "塗装工事", "軒天塗装",
            soffit_len, "ｍ", UP["軒天塗装_m"], sub,
        ))
    # 軒天（玄関・バルコニー）
    if q.get("soffit_sqm", 0) > 0:
        items.append(_item(
            "塗装工事", "軒天塗装（玄関・バルコニー）",
            q["soffit_sqm"], "㎡", UP["軒天塗装_sqm"], sub,
        ))
    if q.get("gutter_length", 0) > 0:
        items.append(_item(
            "塗装工事", "雨樋塗装",
            q["gutter_length"], "ｍ", UP["雨樋塗装"], sub,
        ))
    if q.get("shutter_box_length", 0) > 0:
        items.append(_item(
            "塗装工事", "シャッターボックス塗装",
            q["shutter_box_length"], "ｍ", UP["シャッターボックス"], ケレン錆止め,
        ))
    if q.get("do_foundation", False):
        items.append(_item(
            "塗装工事", "基礎塗装",
            1, "式", UP["基礎塗装"], "ベースプロテクト",
        ))

    # ─── シーリング工事 ────────────────────────────────────
    if q.get("joint_seal_length", 0) > 0:
        items.append(_item(
            "シーリング工事", "目地シーリング",
            q["joint_seal_length"], "ｍ", UP["目地シーリング"],
            "オートンイクシード　打ち替え",
        ))
    if q.get("do_misc_seal", True):
        items.append(_item(
            "シーリング工事", "雑シーリング",
            1, "式", UP["雑シーリング"], "開口部等",
        ))
    if q.get("skylight_count", 0) > 0:
        items.append(_item(
            "シーリング工事", "トップライトシーリング",
            q["skylight_count"], "箇所", UP["トップライト"], "シリコン",
        ))

    # ─── 諸経費 ────────────────────────────────────────────
    misc = q.get("misc_cost", UP["諸経費"])
    if misc and misc > 0:
        items.append(_item("諸経費", "諸経費", 1, "式", misc))

    # ─── 合計計算 ──────────────────────────────────────────
    subtotal_before_discount = sum(i["amount"] for i in items)
    discount = int(q.get("discount", 0))
    subtotal = subtotal_before_discount - discount

    tax_rate   = 0.10
    tax_amount = round(subtotal * tax_rate)
    total      = subtotal + tax_amount

    return {
        "estimation_items": items,
        "subtotal": subtotal,
        "tax_rate": tax_rate,
        "tax_amount": tax_amount,
        "total": total,
        "discount": discount,
        "subtotal_before_discount": subtotal_before_discount,
        "notes": "",
        "summary": {
            "wall_area":     q.get("wall_area", 0),
            "roof_area":     q.get("roof_area", 0),
            "scaffold_area": q.get("scaffold_area", 0),
        },
    }

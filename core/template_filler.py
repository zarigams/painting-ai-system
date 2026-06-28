"""
テンプレート流し込みモジュール
AIの積算結果をExcelテンプレートの特定セルに書き込む。
計算式（数量×単価=金額 等）はテンプレートのままで保持する。
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

import openpyxl


STANDARD_NAIYAKU_MAPPING = {
    # ── 仮設工事（行3〜10）──
    "外部足場":             (3,  True, True, False),
    "屋根足場":             (4,  True, True, False),
    "昇降設備":             (5,  True, True, False),
    "運搬費":               (6,  True, True, False),
    "道路使用":             (7,  True, True, False),
    "ガードマン":           (8,  True, True, False),
    "カーポート":           (9,  True, True, False),
    "防護管":               (10, True, True, False),
    # ── 塗装工事（行20〜34）──
    "屋根高圧洗浄":         (20, True, True, False),
    "屋根板金":             (21, True, True, True),
    "屋根塗装":             (22, True, True, True),
    "縁切り":               (23, True, True, False),
    "外壁高圧洗浄":         (24, True, True, False),
    "外壁塗装":             (25, True, True, True),
    "土台水切":             (26, True, True, True),
    "中間水切":             (26, True, True, True),
    "出窓天端":             (27, True, True, True),
    "化粧梁":               (28, True, True, True),
    "付梁":                 (28, True, True, True),
    "破風":                 (29, True, True, True),
    "鼻隠":                 (29, True, True, True),
    "軒天塗装":             (30, True, True, True),
    "軒天（玄関":           (31, True, True, True),
    "軒天（バルコニー":     (31, True, True, True),
    "雨樋塗装":             (32, True, True, True),
    "シャッターボックス":   (33, True, True, True),
    "基礎塗装":             (34, True, True, False),
    # ── シーリング工事（行37〜39）──
    "目地シーリング":       (37, True, True, True),
    "サイディング目地":     (37, True, True, True),
    "雑シーリング":         (38, True, True, False),
    "開口部廻りシーリング": (38, True, True, False),
    "トップライト":         (39, True, True, False),
    # ── 諸経費（行42）──
    "諸経費":               (42, False, True, False),
}

# 書き込み前にD列をゼロクリアする行（テンプレートの古いデータを消す）
_ROWS_TO_CLEAR = set(
    mapping[0] for mapping in STANDARD_NAIYAKU_MAPPING.values()
    if mapping[1]  # has_qty=True の行のみ
)


def _find_row_for_item(item_name: str) -> Optional[tuple]:
    for keyword, mapping in STANDARD_NAIYAKU_MAPPING.items():
        if keyword in item_name:
            return mapping
    return None


def fill_standard_template(
    template_path: Path,
    output_path: Path,
    estimation: dict,
    project_data: dict,
    client_name: str = "",
    site_address: str = "",
    sales_rep: str = "",
    company_name: str = "",
    discount: int = 0,
) -> Path:
    import shutil
    shutil.copy2(template_path, output_path)

    wb = openpyxl.load_workbook(output_path)

    # ── 見積書シートへの書き込み ──
    ws_quote = wb["見積書"]

    today = datetime.now()
    ws_quote["H1"] = today
    ws_quote["H1"].number_format = "yyyy年m月d日"

    if client_name:
        ws_quote["A4"] = client_name
    ws_quote["B5"] = ""  # サンプル残骸「吉田」をクリア
    if site_address:
        ws_quote["H4"] = site_address
    if client_name:
        ws_quote["H5"] = f"{client_name}邸 外壁塗装工事"
    if sales_rep:
        ws_quote["H8"] = sales_rep

    if discount:
        ws_quote["G18"] = discount if discount <= 0 else -abs(discount)

    # ── 内訳シートへの書き込み ──
    ws_naiyaku = wb["内訳"]

    # ★ まず管理対象の全行のD列（数量）を0にクリア ★
    # テンプレートの古い数値（住吉屋実績等）が残らないようにする
    for row_num in _ROWS_TO_CLEAR:
        ws_naiyaku.cell(row=row_num, column=4).value = 0

    # AI積算items → 内訳セルに書き込み
    items = estimation.get("estimation_items", [])
    written_rows = set()

    for item in items:
        item_name = item.get("item_name", "")
        mapping = _find_row_for_item(item_name) or _find_row_for_item(item.get("category", ""))
        if mapping is None:
            continue

        row_num, has_qty, has_price, has_spec = mapping
        if row_num in written_rows:
            continue
        written_rows.add(row_num)

        qty = item.get("quantity", 0) or 0
        unit_price = item.get("unit_price", 0) or 0
        spec = item.get("notes", "") or item.get("basis", "") or ""

        if has_qty:
            ws_naiyaku.cell(row=row_num, column=4).value = qty      # 0でも書く
        if has_price and unit_price:
            ws_naiyaku.cell(row=row_num, column=6).value = unit_price
        if has_spec and spec:
            existing_spec = ws_naiyaku.cell(row=row_num, column=3).value
            if not existing_spec:
                ws_naiyaku.cell(row=row_num, column=3).value = spec

    wb.save(output_path)
    return output_path


def fill_template(
    template_id: str,
    template_path: Path,
    output_path: Path,
    estimation: dict,
    project_data: dict,
    client_name: str = "",
    site_address: str = "",
    sales_rep: str = "",
    company_name: str = "",
    discount: int = 0,
) -> Path:
    return fill_standard_template(
        template_path=template_path,
        output_path=output_path,
        estimation=estimation,
        project_data=project_data,
        client_name=client_name,
        site_address=site_address,
        sales_rep=sales_rep,
        company_name=company_name,
        discount=discount,
    )

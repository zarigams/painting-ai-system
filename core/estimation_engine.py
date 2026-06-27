"""
積算エンジン
案件情報と単価表から数量・金額を計算する
"""

import json
import re
from pathlib import Path
from typing import Optional

from modules.llm_client import LLMClient

ESTIMATION_SYSTEM_PROMPT = """
あなたは塗装工事の積算専門AIです。
案件情報と単価表をもとに、詳細な積算明細をJSON形式で出力してください。

## 積算ルール
1. 各工種の数量・単価・金額を明記する
2. 推定値には estimated: true を設定する
3. 根拠を basis フィールドに記載する
4. 要確認項目には needs_confirmation: true を設定する
5. 数量は小数点1位まで記載する

## item_nameは必ず以下の名称を使うこと（見積テンプレートのセルと対応しています）
### 仮設工事
- 外部足場（単位: ㎡）
- 屋根足場（単位: ㎡）
- 昇降設備（単位: 式）
- 運搬費（単位: 式）
- 道路使用許可申請費（単位: 式）
- ガードマン（単位: 人）
- 防護管設置費用（単位: 式）

### 塗装工事
- 屋根高圧洗浄（単位: ㎡）
- 屋根板金塗装（単位: 式）
- 屋根塗装（単位: ㎡）
- 縁切り（単位: ㎡）
- 外壁高圧洗浄（単位: ㎡）
- 外壁塗装（単位: ㎡）
- 土台水切塗装（単位: m）
- 出窓天端塗装（単位: m）
- 化粧梁・付梁塗装（単位: m）
- 破風・鼻隠し塗装（単位: m）
- 軒天塗装（単位: m）
- 軒天塗装（玄関・バルコニー）（単位: ㎡）
- 雨樋塗装（単位: m）
- シャッターボックス塗装（単位: m）
- 基礎塗装（単位: 式）

### シーリング工事
- 目地シーリング（単位: m）
- 雑シーリング（単位: 式）
- トップライトシーリング（単位: 箇所）

### 諸経費
- 諸経費（単位: 式）

存在しない工種は出力しなくてよい。

## 出力JSONフォーマット
{
  "estimation_items": [
    {
      "category": "仮設工事/塗装工事/シーリング工事/諸経費のいずれか",
      "item_name": "上記リストの名称を使うこと",
      "quantity": 数値,
      "unit": "㎡/m/箇所/枚/式/人",
      "unit_price": 単価（円）,
      "amount": 合計金額（円）,
      "estimated": true/false,
      "needs_confirmation": true/false,
      "basis": "数量の根拠説明",
      "notes": "塗料仕様など（例: クリーンマイルドシリコン）"
    }
  ],
  "subtotal": 小計（円）,
  "tax_rate": 0.10,
  "tax_amount": 消費税額（円）,
  "total": 税込合計（円）,
  "summary": {
    "exterior_wall_area": 外壁面積,
    "roof_area": 屋根面積,
    "scaffold_area": 足場面積,
    "main_paint_spec": "主要塗料仕様"
  },
  "confirmation_items": ["要確認事項のリスト"],
  "notes": "積算全体に関するメモ"
}
"""


class EstimationEngine:
    """
    積算エンジン：数量と単価から見積明細を計算する
    """

    def __init__(self, llm_client: LLMClient, unit_prices_path: Optional[str] = None):
        self.llm = llm_client
        self.unit_prices = self._load_unit_prices(unit_prices_path)

    def _load_unit_prices(self, path: Optional[str]) -> dict:
        """単価表JSONを読み込む"""
        if path is None:
            path = Path(__file__).parent.parent / "data" / "unit_prices" / "default_prices.json"
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def calculate(self, project_data: dict) -> dict:
        """
        案件情報から積算明細を生成する

        Args:
            project_data: image_analyzerが返した案件情報dict（質問回答済み）

        Returns:
            dict: 積算明細（estimation_items, subtotal, total等）
        """
        # まずルールベースで計算できる部分は計算する
        rule_based = self._rule_based_calculation(project_data)

        # LLMで最終積算を実行
        raw = self.llm.generate_final_estimation(
            project_data={**project_data, "rule_based_pre_calc": rule_based},
            unit_prices=self.unit_prices,
            system_prompt=ESTIMATION_SYSTEM_PROMPT,
        )

        result = self._parse_json_response(raw)

        # 合計金額の再計算（LLMのミス防止）
        result = self._recalculate_totals(result)

        return result

    def _rule_based_calculation(self, project_data: dict) -> dict:
        """
        ルールベースで計算できる数量を事前算出（LLMの補助情報として渡す）
        """
        quantities = project_data.get("quantities", {})
        scope = project_data.get("scope", {})
        rules = self.unit_prices.get("estimation_rules", {})
        pre_calc = {}

        ext_wall = quantities.get("exterior_wall_area", {}).get("value")

        if ext_wall:
            # 養生面積の推定
            pre_calc["養生面積（推定）"] = round(ext_wall * 0.15, 1)

            # シーリング延長の推定（未入力の場合）
            if not quantities.get("sealing_length", {}).get("value") and scope.get("sealing"):
                pre_calc["シーリング延長（推定）"] = round(ext_wall * 0.3, 1)

        # 足場面積（外壁面積から推定、未入力の場合）
        if not quantities.get("scaffold_area", {}).get("value") and scope.get("scaffold"):
            if ext_wall:
                # 外壁面積から足場面積を逆算（外壁面積 ≒ 足場面積 × 0.85）
                pre_calc["足場面積（推定）"] = round(ext_wall / 0.85, 1)

        return pre_calc

    def _recalculate_totals(self, result: dict) -> dict:
        """LLMが出力した明細から合計を再計算する（数値の整合性確保）"""
        items = result.get("estimation_items", [])
        subtotal = 0

        for item in items:
            qty = item.get("quantity", 0) or 0
            unit_price = item.get("unit_price", 0) or 0
            amount = round(qty * unit_price)
            item["amount"] = amount
            subtotal += amount

        tax_rate = result.get("tax_rate", 0.10)
        tax_amount = round(subtotal * tax_rate)
        total = subtotal + tax_amount

        result["subtotal"] = subtotal
        result["tax_rate"] = tax_rate
        result["tax_amount"] = tax_amount
        result["total"] = total

        return result

    def _parse_json_response(self, raw: str) -> dict:
        cleaned = re.sub(r"```(?:json)?\n?", "", raw).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {
                "parse_error": True,
                "raw_response": raw,
                "estimation_items": [],
                "subtotal": 0,
                "tax_amount": 0,
                "total": 0,
            }

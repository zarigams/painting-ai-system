"""
不足情報質問エンジン
画像解析結果から不足している情報を特定し、必要最小限の質問を生成する
"""

import json
import re
from .llm_client import LLMClient

QUESTION_SYSTEM_PROMPT = """
あなたは塗装工事の積算専門AIアシスタントです。
案件情報の不足している部分について、積算に必要な情報を過不足なく質問します。

## ルール
- 質問は1〜5個に絞ること（多すぎは禁止）
- 積算に必須の情報だけを質問すること
- YES/NO または数値で答えられる簡潔な質問にすること
- すでに判明している情報は再度質問しないこと

## 出力フォーマット（必ずJSON）
{
  "has_enough_info": true/false,
  "questions": [
    {
      "id": "q1",
      "question": "質問文",
      "type": "yes_no / number / text / select",
      "options": ["選択肢1", "選択肢2"],  // typeがselectの場合のみ
      "field_key": "対応するデータフィールド名",
      "priority": "required / optional"
    }
  ],
  "ready_to_estimate": true/false
}
"""


class QuestionEngine:
    """
    不足情報を特定し、最小限の質問を生成するエンジン
    """

    # 積算に必須のフィールドと日本語ラベルのマッピング
    REQUIRED_FIELDS = {
        "exterior_wall_area": "外壁面積",
        "scaffold_area":      "足場面積",
    }

    # 施工範囲に応じて必要になる追加フィールド
    CONDITIONAL_FIELDS = {
        "roof":           "roof_area",
        "gutters":        "gutter_length",
        "sealing":        "sealing_length",
        "waterproof_balcony": "balcony_area",
        "rain_shutters":  "rain_shutter_count",
        "repair_cracks":  "crack_count",
    }

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def generate_questions(self, project_data: dict) -> dict:
        """
        案件データを分析して不足情報の質問リストを生成する

        Args:
            project_data: image_analyzerが返した案件情報dict

        Returns:
            dict: {has_enough_info, questions, ready_to_estimate}
        """
        missing = self._detect_missing_fields(project_data)

        if not missing:
            return {
                "has_enough_info": True,
                "questions": [],
                "ready_to_estimate": True
            }

        # LLMに質問生成を依頼
        prompt = f"""
以下の案件情報から、積算に必要な不足情報を特定し、必要最小限の質問を生成してください。

【現在の案件情報】
{json.dumps(project_data, ensure_ascii=False, indent=2)}

【不足が検出されたフィールド】
{json.dumps(missing, ensure_ascii=False)}

上記の不足情報を補うための質問を、優先度の高い順に最大5個生成してください。
"""
        raw = self.llm.ask_followup(
            conversation_history=[],
            new_message=prompt,
            system_prompt=QUESTION_SYSTEM_PROMPT,
        )

        result = self._parse_json_response(raw)

        # 不足フィールドがある場合はready_to_estimateをFalseに
        if missing.get("required"):
            result["ready_to_estimate"] = False

        return result

    def _detect_missing_fields(self, project_data: dict) -> dict:
        """必須・任意フィールドの不足を検出"""
        missing = {"required": [], "optional": []}
        quantities = project_data.get("quantities", {})
        scope = project_data.get("scope", {})

        # 必須フィールドチェック
        for field, label in self.REQUIRED_FIELDS.items():
            q = quantities.get(field, {})
            if q.get("value") is None:
                missing["required"].append({"field": field, "label": label})

        # 施工範囲に応じた追加チェック
        for scope_key, qty_key in self.CONDITIONAL_FIELDS.items():
            if scope.get(scope_key):
                q = quantities.get(qty_key, {})
                if q.get("value") is None:
                    missing["optional"].append({
                        "field": qty_key,
                        "label": f"{scope_key}の数量"
                    })

        return missing

    def apply_answers(self, project_data: dict, answers: dict) -> dict:
        """
        ユーザーの回答を案件データに反映する

        Args:
            project_data: 現在の案件データ
            answers: {field_key: value} の辞書

        Returns:
            更新された案件データ
        """
        quantities = project_data.setdefault("quantities", {})

        field_map = {
            "exterior_wall_area":  ("exterior_wall_area", "㎡"),
            "roof_area":           ("roof_area", "㎡"),
            "scaffold_area":       ("scaffold_area", "㎡"),
            "gutter_length":       ("gutter_length", "m"),
            "sealing_length":      ("sealing_length", "m"),
            "crack_count":         ("crack_count", "箇所"),
            "balcony_area":        ("balcony_area", "㎡"),
            "rain_shutter_count":  ("rain_shutter_count", "枚"),
        }

        for field_key, value in answers.items():
            if field_key in field_map:
                qty_key, unit = field_map[field_key]
                quantities[qty_key] = {
                    "value": value,
                    "unit": unit,
                    "estimated": False,
                    "basis": "営業担当確認済み"
                }

            # スコープのyes/no回答
            scope = project_data.setdefault("scope", {})
            scope_keys = ["roof", "gutters", "sealing", "waterproof_balcony",
                          "rain_shutters", "repair_cracks", "soffit", "fascia",
                          "scaffold", "high_pressure_wash"]
            if field_key in scope_keys:
                scope[field_key] = bool(value)

        return project_data

    def _parse_json_response(self, raw: str) -> dict:
        cleaned = re.sub(r"```(?:json)?\n?", "", raw).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {
                "has_enough_info": False,
                "questions": [],
                "ready_to_estimate": False,
                "parse_error": True
            }

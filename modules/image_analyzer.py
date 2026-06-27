"""
画像解析モジュール
現場写真から建物の各部位・状態を識別してプロジェクト情報を抽出する
"""

import json
import re
from typing import Optional

from .llm_client import LLMClient

# 画像解析用システムプロンプト
IMAGE_ANALYSIS_SYSTEM_PROMPT = """
あなたは塗装工事の積算専門AIアシスタントです。
現場写真と営業担当の説明から、塗装工事に必要な情報を整理・分析します。

## あなたの役割
1. 写真から建物各部位（外壁・屋根・軒天・雨樋・破風・鉄部・木部）を識別する
2. 劣化状況（クラック・チョーキング・剥離・サビ・コケ等）を確認する
3. 施工範囲・施工内容を整理する
4. 面積・数量の推定値を算出する（推定値には必ず「推定」と明記）

## 出力ルール
- 必ずJSON形式で出力すること
- 推定値には "estimated": true を設定すること
- 根拠を "basis" フィールドに記載すること
- 不明・要確認の項目は "needs_confirmation": true を設定すること
- 断定せず、確認が必要な点は明示すること

## 出力JSONフォーマット
{
  "building_overview": {
    "type": "戸建て/マンション/アパート/工場等",
    "structure": "木造/鉄骨/RC等",
    "floors": 階数（数値または null）,
    "estimated_area": 外壁面積推定値（㎡、不明なら null）,
    "estimated": true/false,
    "notes": "概要メモ"
  },
  "scope": {
    "exterior_wall": true/false,
    "roof": true/false,
    "soffit": true/false,
    "fascia": true/false,
    "gutters": true/false,
    "iron_parts": true/false,
    "wood_parts": true/false,
    "sealing": true/false,
    "high_pressure_wash": true/false,
    "scaffold": true/false,
    "waterproof_balcony": true/false,
    "rain_shutters": true/false,
    "repair_cracks": true/false
  },
  "quantities": {
    "exterior_wall_area": { "value": 数値またはnull, "unit": "㎡", "estimated": true/false, "basis": "根拠説明" },
    "roof_area":          { "value": 数値またはnull, "unit": "㎡", "estimated": true/false, "basis": "根拠説明" },
    "soffit_area":        { "value": 数値またはnull, "unit": "㎡", "estimated": true/false, "basis": "根拠説明" },
    "fascia_length":      { "value": 数値またはnull, "unit": "m",  "estimated": true/false, "basis": "根拠説明" },
    "gutter_length":      { "value": 数値またはnull, "unit": "m",  "estimated": true/false, "basis": "根拠説明" },
    "sealing_length":     { "value": 数値またはnull, "unit": "m",  "estimated": true/false, "basis": "根拠説明" },
    "scaffold_area":      { "value": 数値またはnull, "unit": "㎡", "estimated": true/false, "basis": "根拠説明" },
    "crack_count":        { "value": 数値またはnull, "unit": "箇所","estimated": true/false, "basis": "根拠説明" },
    "balcony_area":       { "value": 数値またはnull, "unit": "㎡", "estimated": true/false, "basis": "根拠説明" },
    "rain_shutter_count": { "value": 数値またはnull, "unit": "枚", "estimated": true/false, "basis": "根拠説明" }
  },
  "paint_spec": {
    "exterior_wall_paint": "塗料名または null（例：ラジカル塗料）",
    "roof_paint": "塗料名または null",
    "notes": "塗装仕様に関するメモ"
  },
  "conditions": {
    "deterioration_level": "良好/普通/劣化/要修繕",
    "cracks_observed": true/false,
    "rust_observed": true/false,
    "moss_observed": true/false,
    "peeling_observed": true/false,
    "chalking_observed": true/false,
    "notes": "劣化状況メモ"
  },
  "missing_info": [
    "確認が必要な項目のリスト（例：雨戸の枚数、ベランダ防水の有無）"
  ]
}
"""


class ImageAnalyzer:
    """
    現場写真＋説明テキストを解析してプロジェクト情報を抽出するクラス
    """

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def analyze(
        self,
        image_bytes_list: list[bytes],
        description: str,
    ) -> dict:
        """
        写真リストと説明テキストから案件情報を抽出する

        Returns:
            dict: 抽出された案件情報（JSON）
        """
        if not image_bytes_list and not description:
            raise ValueError("写真またはテキスト説明のいずれかが必要です")

        raw_response = self.llm.analyze_images_and_description(
            image_data_list=image_bytes_list,
            description=description or "（写真のみ、説明なし）",
            system_prompt=IMAGE_ANALYSIS_SYSTEM_PROMPT,
        )

        return self._parse_json_response(raw_response)

    def _parse_json_response(self, raw: str) -> dict:
        """LLMの応答からJSONを抽出・パース"""
        # マークダウンコードブロックの除去
        cleaned = re.sub(r"```(?:json)?\n?", "", raw).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # JSON抽出失敗時はエラー情報を返す
            return {
                "parse_error": True,
                "raw_response": raw,
                "missing_info": ["解析結果の取得に失敗しました。テキスト説明を追加してください。"]
            }

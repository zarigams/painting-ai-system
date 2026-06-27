"""
図面解析モジュール
PDFの建築図面をGPT-4o Visionで解析して建物情報を抽出する
"""

import base64
import json
import re

DRAWING_SYSTEM_PROMPT = """
あなたは建築図面の読み取り専門AIです。
塗装工事の見積もりに必要な情報を図面から抽出してください。

## 抽出する情報
1. 建物種別（戸建て住宅/集合住宅/店舗/事務所/その他）
2. 構造（木造/鉄骨造/RC造/ALC/その他）
3. 地上階数（数値）
4. 外壁面積（㎡）※各面の幅×高さから計算
5. 屋根面積（㎡）
6. 延床面積（㎡）
7. 建築面積（㎡）
8. 特記事項（バルコニー・ベランダの有無、屋根形状、付帯部の特徴など）

## 面積の計算方法
- 図面に寸法が記載されていれば、各面を計算して合算する
- 記載がない場合は null とする

## 出力形式（JSONのみ出力、説明文不要）
{
  "building_type": "戸建て住宅",
  "structure": "木造",
  "floors": 2,
  "exterior_wall_area": 120.5,
  "roof_area": 65.0,
  "total_floor_area": 100.0,
  "building_area": 55.0,
  "notes": "南面にバルコニーあり、寄棟屋根",
  "estimated_fields": ["exterior_wall_area"],
  "confidence": "medium"
}

読み取れない・計算できない項目はnullとする。
推定した項目名はestimated_fieldsリストに入れる。
confidenceは high/medium/low で記入。
"""


class DrawingAnalyzer:
    """建築図面PDFを解析して建物情報を返す"""

    def __init__(self, api_key: str):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)
        self.model = "gpt-4o"

    def pdf_to_images(self, pdf_bytes: bytes) -> list:
        """PDFの各ページをPNG画像バイト列に変換する"""
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise ImportError("pymupdf が必要です。requirements.txt に追加してください。")

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        images = []
        for page in doc:
            # 2倍解像度でレンダリング（図面の細かい文字を読めるように）
            mat = fitz.Matrix(2.0, 2.0)
            pix = page.get_pixmap(matrix=mat)
            images.append(pix.tobytes("png"))
        doc.close()
        return images

    def analyze(self, pdf_bytes: bytes) -> dict:
        """PDFを解析して建物情報dictを返す"""
        images = self.pdf_to_images(pdf_bytes)
        if not images:
            return {"error": "PDFのページが読み取れませんでした"}

        # 最初の3ページまで送信（A1図面でも十分）
        target_images = images[:3]

        content = [
            {
                "type": "text",
                "text": "以下の建築図面を解析し、塗装工事見積に必要な建物情報をJSONで出力してください。",
            }
        ]
        for img_bytes in target_images:
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{b64}",
                    "detail": "high",
                },
            })

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": DRAWING_SYSTEM_PROMPT},
                {"role": "user",   "content": content},
            ],
            max_tokens=1000,
            temperature=0.1,
        )

        raw = response.choices[0].message.content
        return self._parse_response(raw)

    def _parse_response(self, raw: str) -> dict:
        cleaned = re.sub(r"```(?:json)?\n?", "", raw).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {"parse_error": True, "raw": raw}


def drawing_data_to_text(data: dict) -> str:
    """
    解析結果dictを積算エンジンに渡せるテキストに変換する
    """
    if not data or data.get("error") or data.get("parse_error"):
        return ""

    lines = ["【図面解析結果】"]

    if data.get("building_type"):
        lines.append(f"建物種別: {data['building_type']}")
    if data.get("structure"):
        lines.append(f"構造: {data['structure']}")
    if data.get("floors") is not None:
        lines.append(f"階数: {data['floors']}階")
    if data.get("exterior_wall_area") is not None:
        estimated = "exterior_wall_area" in data.get("estimated_fields", [])
        tag = "（推定）" if estimated else ""
        lines.append(f"外壁面積: {data['exterior_wall_area']} ㎡{tag}")
    if data.get("roof_area") is not None:
        estimated = "roof_area" in data.get("estimated_fields", [])
        tag = "（推定）" if estimated else ""
        lines.append(f"屋根面積: {data['roof_area']} ㎡{tag}")
    if data.get("total_floor_area") is not None:
        lines.append(f"延床面積: {data['total_floor_area']} ㎡")
    if data.get("building_area") is not None:
        lines.append(f"建築面積: {data['building_area']} ㎡")
    if data.get("notes"):
        lines.append(f"特記: {data['notes']}")

    return "\n".join(lines)

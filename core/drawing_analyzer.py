"""
図面解析モジュール
PDFの建築図面をGPT-4o Visionで解析して建物情報を抽出する

対応モード:
  A) 寸法数字が図面に明記されている場合 → そのまま読み取り計算
  B) 縮尺＋元の用紙サイズが指定されている場合 → 実効縮尺を計算して視覚推定
"""

import base64
import json
import re

# 用紙サイズ（mm、長辺）
PAPER_LONG_SIDE_MM = {
    "A1": 841,
    "A2": 594,
    "A3": 420,
    "A4": 297,
}

DRAWING_SYSTEM_PROMPT = """
あなたは建築図面の読み取り専門AIです。
塗装工事の見積もりに必要な情報を図面から抽出してください。

## 読み取り方法

### パターンA：寸法数字が図面に明記されている場合
各面（南・北・東・西）の幅×高さの寸法数字を読み取り、面積を計算して合算してください。

### パターンB：実効縮尺が指定されている場合
ユーザーメッセージに「【実効縮尺】1/XXX」が記載されている場合:
1. 立面図（南立面図・北立面図・東立面図・西立面図）を特定する
2. 各立面図の壁の幅と高さを、図面全体に対する比率で視覚的に推定する
3. 指定された実効縮尺を使って実寸（m）に変換する（例: 1/200なら図面1cmが実寸2m）
4. 各面の面積（幅×高さ）を計算して合算する
※窓・ドアなどの開口部は差し引かず、全面を外壁面積として計上してよい

## 抽出する情報
1. 建物種別（戸建て住宅/集合住宅/店舗/事務所/その他）
2. 構造（木造/鉄骨造/RC造/ALC/その他）
3. 地上階数（数値）
4. 外壁面積（㎡）
5. 屋根面積（㎡）
6. 延床面積（㎡）
7. 建築面積（㎡）
8. 特記事項（バルコニー・ベランダの有無、屋根形状、付帯部の特徴など）

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

    def pdf_to_images(self, pdf_bytes: bytes) -> tuple:
        """PDFの各ページをPNG画像バイト列に変換する。(images, page0_size_mm) を返す"""
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise ImportError("pymupdf が必要です。requirements.txt に追加してください。")

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        images = []
        page0_size_mm = None
        for i, page in enumerate(doc):
            if i == 0:
                # 1ページ目のサイズ取得（points → mm、1pt = 0.3528mm）
                w_mm = page.rect.width * 0.3528
                h_mm = page.rect.height * 0.3528
                page0_size_mm = (w_mm, h_mm)
            mat = fitz.Matrix(2.0, 2.0)
            pix = page.get_pixmap(matrix=mat)
            images.append(pix.tobytes("png"))
        doc.close()
        return images, page0_size_mm

    def calc_effective_scale(
        self,
        stated_scale: str,
        original_paper: str,
        page0_size_mm: tuple,
    ) -> str | None:
        """
        実効縮尺を計算して文字列で返す。
        stated_scale: "1/100" など、"不要" の場合は None を返す
        original_paper: "A2" など
        page0_size_mm: (width_mm, height_mm)
        """
        if not stated_scale or stated_scale == "不要":
            return None
        if original_paper not in PAPER_LONG_SIDE_MM:
            return None

        # 縮尺分母を取得
        try:
            denom = int(stated_scale.split("/")[1])
        except Exception:
            return None

        # 現在のPDFページの長辺（mm）
        w, h = page0_size_mm
        current_long_mm = max(w, h)

        # 元の用紙の長辺（mm）
        original_long_mm = PAPER_LONG_SIDE_MM[original_paper]

        # 縮小率（例: A2→A4なら 297/594 = 0.5）
        reduction_ratio = current_long_mm / original_long_mm

        # 実効縮尺分母（例: 1/100 で 0.5 縮小なら → 1/200）
        effective_denom = round(denom / reduction_ratio)

        return f"1/{effective_denom}"

    def analyze(
        self,
        pdf_bytes: bytes,
        stated_scale: str = "不要",
        original_paper: str = None,
    ) -> dict:
        """PDFを解析して建物情報dictを返す"""
        images, page0_size_mm = self.pdf_to_images(pdf_bytes)
        if not images:
            return {"error": "PDFのページが読み取れませんでした"}

        # 実効縮尺を計算
        effective_scale = None
        if stated_scale and stated_scale != "不要" and original_paper and page0_size_mm:
            effective_scale = self.calc_effective_scale(
                stated_scale, original_paper, page0_size_mm
            )

        # 全ページ送信（最大6ページ）
        target_images = images[:6]

        # ユーザーメッセージ
        user_text = "以下の建築図面を解析し、塗装工事見積に必要な建物情報をJSONで出力してください。"
        if effective_scale:
            user_text += (
                f"\n\n【実効縮尺】{effective_scale}\n"
                f"（元図面: {original_paper} / 縮尺: {stated_scale} → "
                f"スキャン縮小後の実効縮尺として計算済み）\n"
                "立面図の視覚的な比率とこの実効縮尺を使って外壁面積を推定してください。"
            )

        content = [{"type": "text", "text": user_text}]
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
        result = self._parse_response(raw)

        # 実効縮尺情報をメタデータとして付与
        if effective_scale:
            result["_effective_scale"] = effective_scale

        return result

    def _parse_response(self, raw: str) -> dict:
        cleaned = re.sub(r"```(?:json)?\n?", "", raw).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {"parse_error": True, "raw": raw}


def drawing_data_to_text(data: dict) -> str:
    """解析結果dictを積算エンジンに渡せるテキストに変換する"""
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
    if data.get("_effective_scale"):
        lines.append(f"使用した実効縮尺: {data['_effective_scale']}")

    return "\n".join(lines)

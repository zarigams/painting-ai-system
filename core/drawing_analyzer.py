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

# ─────────────────────────────────────────────────────────────────────────────
# アノテーション付き解析用プロンプト
# ─────────────────────────────────────────────────────────────────────────────
DRAWING_SYSTEM_PROMPT_ANNOTATED = """
あなたは建築図面の読み取り専門AIです。
立面図（南・東・西・北）から塗装工事に必要な寸法を読み取り、位置情報付きで返してください。

## 最重要：読み取る寸法の優先順位
1. 各立面の【幅寸法】（南面幅・東面幅・北面幅・西面幅）← 必ず探す
2. 高さ寸法（棟高さ・軒高・1F天井高）
3. 縮尺
4. その他の寸法

## annotations フォーマット
各寸法について以下を返す：
- label: 項目名（"南面幅", "東面幅", "棟高さ", "軒高（2F）", "1F天井高", "縮尺" など）
- value: 数値（文字列）
- unit: 単位（"m", "1/100" など）
- category: "width" / "height" / "scale" / "area" / "other"
- confidence: "high" / "medium" / "low"
- x_pct, y_pct: 寸法が書かれている箇所の中心座標（画像の0〜100%）

【幅寸法の場合は追加で】
- x1_pct: 計測区間の左端X座標（%）
- x2_pct: 計測区間の右端X座標（%）
（これにより図面上に←→矢印を描ける）

## 注意事項
- スキャン図面で数字が読みにくい場合は confidence: "low" にして値を推定で記入すること
- 幅寸法が図面に明記されていない場合は、立面図の外形を視覚的に測定して推定値を返すこと
- 縮尺が1/100なら、図面上で1mmが実寸10cmに相当する
- 全ての立面図（南・東・西・北）を確認し、それぞれの幅を返すこと
- 窓・ドア・玄関などの開口部は各面ごとにリストアップし、幅×高さ（m）を記録すること
- 各面の wall_area = 幅 × 軒高 − Σ(開口部の幅 × 高さ) で計算すること

## 出力形式（JSONのみ。説明文不要）
{
  "building_type": "戸建て住宅",
  "structure": "木造",
  "floors": 2,
  "exterior_wall_area": null,
  "roof_area": null,
  "total_floor_area": null,
  "building_area": null,
  "notes": "寄棟屋根、南面バルコニーあり",
  "estimated_fields": [],
  "confidence": "medium",
  "faces": {
    "south": {
      "width": 9.1,
      "height": 6.5,
      "openings": [
        {"type": "窓", "width": 1.6, "height": 1.2},
        {"type": "窓", "width": 1.6, "height": 1.2},
        {"type": "ドア", "width": 0.9, "height": 2.1}
      ],
      "wall_area": 47.5
    },
    "north": {
      "width": 9.1,
      "height": 6.5,
      "openings": [
        {"type": "窓", "width": 1.6, "height": 1.2}
      ],
      "wall_area": 57.3
    },
    "east": {
      "width": 7.2,
      "height": 6.5,
      "openings": [
        {"type": "窓", "width": 0.9, "height": 1.2}
      ],
      "wall_area": 45.7
    },
    "west": {
      "width": 7.2,
      "height": 6.5,
      "openings": [],
      "wall_area": 46.8
    }
  },
  "total_wall_area": 197.3,
  "annotations": [
    {"label": "南面幅", "value": "9.10", "unit": "m", "x_pct": 25, "y_pct": 82, "x1_pct": 8, "x2_pct": 43, "confidence": "medium", "category": "width"},
    {"label": "東面幅", "value": "7.20", "unit": "m", "x_pct": 73, "y_pct": 82, "x1_pct": 55, "x2_pct": 92, "confidence": "medium", "category": "width"},
    {"label": "棟高さ", "value": "8.693", "unit": "m", "x_pct": 30, "y_pct": 4, "confidence": "high", "category": "height"},
    {"label": "軒高（2F）", "value": "6.500", "unit": "m", "x_pct": 30, "y_pct": 17, "confidence": "high", "category": "height"},
    {"label": "1F天井高", "value": "3.665", "unit": "m", "x_pct": 30, "y_pct": 38, "confidence": "high", "category": "height"},
    {"label": "縮尺", "value": "1/100", "unit": "", "x_pct": 85, "y_pct": 97, "confidence": "high", "category": "scale"}
  ]
}

- faces: 各面の幅・軒高・開口部リスト・wall_area（開口控除済み面積）を返す
- total_wall_area: 4面のwall_area合計（開口控除済み）を返す
- exterior_wall_area は null のまま（別モジュールで幾何学計算するため）
- faces/total_wall_area が取得できない場合はキーごと省略してよい
"""


FLOOR_PLAN_SYSTEM_PROMPT = """
あなたは建築平面図の読み取り専門AIです。
1F・2F（複数階）の平面図から、各階のフットプリント（外形寸法）と開口部を読み取り、JSONで返してください。

## 最重要：各階のフットプリントを個別に取得する
日本の住宅は1階と2階で外壁の位置が異なることが多い（1Fが広く2Fが狭い）。
必ず1F・2Fそれぞれの幅と奥行きを読み取ること。

## 出力形式（JSONのみ）
{
  "drawing_kind": "floor_plan",
  "eave_height": 6.5,
  "ridge_height": 8.7,
  "floor_footprints": [
    {
      "floor": 1,
      "width": 12.9,
      "depth": 8.5,
      "x_offset": 0,
      "z_offset": 0,
      "floor_height": 3.0,
      "openings": {
        "south": [{"type": "窓", "width": 1.6, "height": 1.2, "x_from_left": 1.5}],
        "north": [{"type": "窓", "width": 0.9, "height": 1.2, "x_from_left": 2.0}],
        "east":  [],
        "west":  [{"type": "ドア", "width": 0.9, "height": 2.1, "x_from_left": 1.0}]
      }
    },
    {
      "floor": 2,
      "width": 9.1,
      "depth": 7.2,
      "x_offset": 1.2,
      "z_offset": 0.5,
      "floor_height": 3.0,
      "openings": {
        "south": [{"type": "窓", "width": 1.6, "height": 1.2, "x_from_left": 0.8}],
        "north": [],
        "east":  [{"type": "窓", "width": 0.9, "height": 1.2, "x_from_left": 1.5}],
        "west":  []
      }
    }
  ],
  "notes": "2階が南東に寄っている。1階南面にバルコニーあり"
}

## フィールド説明
- floor_footprints: 各階の情報リスト（1F・2F・3Fなど）
- floor: 階数（1=1F, 2=2F）
- width: その階の東西方向外壁外側寸法（m）
- depth: その階の南北方向外壁外側寸法（m）
- x_offset: 1Fの西端を基準とした、この階の西端のずれ（m、東方向が正）
- z_offset: 1Fの南端を基準とした、この階の南端のずれ（m、北方向が正）
- floor_height: この階の天井高（m、不明なら2.7〜3.0を設定）
- openings: 各面の開口部（x_from_left=その面の左端からの距離m）

## 注意
- 寸法はすべてメートル（mmで記載されている場合は÷1000）
- 平面図が1枚だけの場合はその階のみ返す（floor_footprints に1要素）
- 1F・2Fそれぞれの図面が渡された場合は必ず2要素返す
- 1Fと2Fの幅・奥行きが同じ場合でも両方返す
- 軒高・棟高の記載がなければ null を返す
- JSONのみ返すこと（説明文不要）
"""

# カテゴリ別の色（RGB）
ANNOTATION_COLORS = {
    "height": (24, 95, 165),    # 青：高さ寸法
    "width":  (15, 110, 86),    # 緑：幅寸法
    "roof":   (153, 60, 29),    # 橙：屋根
    "scale":  (83, 74, 183),    # 紫：縮尺・情報
    "area":   (153, 60, 29),    # 橙：面積
    "other":  (95, 94, 90),     # グレー
}

CATEGORY_LABELS = {
    "height": "高さ寸法",
    "width":  "幅寸法",
    "roof":   "屋根",
    "scale":  "縮尺・情報",
    "area":   "面積",
    "other":  "その他",
}

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
    ) -> str:
        """
        実効縮尺を計算して文字列で返す。
        stated_scale: "1/100" など
        original_paper: "A2" など
        page0_size_mm: (width_mm, height_mm)
        """
        if original_paper not in PAPER_LONG_SIDE_MM:
            return None
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
        """PDFを解析して建物情報dictを返す（後方互換）"""
        images, page0_size_mm = self.pdf_to_images(pdf_bytes)
        if not images:
            return {"error": "PDFのページが読み取れませんでした"}

        effective_scale = None
        if stated_scale and stated_scale != "不要" and original_paper and page0_size_mm:
            effective_scale = self.calc_effective_scale(
                stated_scale, original_paper, page0_size_mm
            )

        user_text = "以下の建築図面を解析し、塗装工事見積に必要な建物情報をJSONで出力してください。"
        if effective_scale:
            user_text += (
                f"\n\n【実効縮尺】{effective_scale}\n"
                f"（元図面: {original_paper} / 縮尺: {stated_scale} → "
                f"スキャン縮小後の実効縮尺として計算済み）\n"
                "立面図の視覚的な比率とこの実効縮尺を使って外壁面積を推定してください。"
            )

        target_images = images[:6]
        content = [{"type": "text", "text": user_text}]
        for img_bytes in target_images:
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"},
            })

        from core.logger import log_gpt_call, log_error
        try:
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
            usage = response.usage
            log_gpt_call(
                func_name="DrawingAnalyzer.analyze",
                model=self.model,
                system_prompt=DRAWING_SYSTEM_PROMPT,
                user_message_summary=f"[PDF画像{len(target_images)}枚] 縮尺={stated_scale} 用紙={original_paper}",
                response_text=raw,
                tokens_prompt=usage.prompt_tokens if usage else None,
                tokens_completion=usage.completion_tokens if usage else None,
                tokens_total=usage.total_tokens if usage else None,
            )
        except Exception as e:
            log_error("GPTエラー: DrawingAnalyzer.analyze", e, "GPT")
            raise
        result = self._parse_response(raw)
        if effective_scale:
            result["_effective_scale"] = effective_scale
        return result

    def analyze_floor_plan(self, pdf_bytes: bytes) -> dict:
        """
        平面図PDFを解析して開口部の正確なX座標付きデータを返す。
        戻り値: {drawing_kind, total_width, total_depth, eave_height, ridge_height, faces, notes}
        """
        images, _ = self.pdf_to_images(pdf_bytes)
        if not images:
            return {"error": "PDFのページが読み取れませんでした"}

        target_images = images[:4]
        content = [{"type": "text", "text": "この平面図（間取り図）を解析してください。"}]
        for img_bytes in target_images:
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"},
            })

        from core.logger import log_gpt_call, log_error
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": FLOOR_PLAN_SYSTEM_PROMPT},
                    {"role": "user",   "content": content},
                ],
                max_tokens=2000,
                temperature=0.1,
            )
            raw = response.choices[0].message.content
            usage = response.usage
            log_gpt_call(
                func_name="DrawingAnalyzer.analyze_floor_plan",
                model=self.model,
                system_prompt=FLOOR_PLAN_SYSTEM_PROMPT[:200],
                user_message_summary=f"[平面図PDF {len(target_images)}枚]",
                response_text=raw,
                tokens_prompt=usage.prompt_tokens if usage else None,
                tokens_completion=usage.completion_tokens if usage else None,
                tokens_total=usage.total_tokens if usage else None,
            )
        except Exception as e:
            log_error("GPTエラー: DrawingAnalyzer.analyze_floor_plan", e, "GPT")
            return {"error": str(e)}

        result = self._parse_response(raw)
        result["_raw_gpt_response"] = raw
        return result

    def analyze_with_annotations(
        self,
        pdf_bytes: bytes,
        stated_scale: str = "不要",
        original_paper: str = None,
    ) -> tuple:
        """
        PDFを解析してアノテーション付き結果を返す。
        戻り値: (result_dict, annotated_image_bytes, annotations_list)
          - result_dict: 建物情報 dict
          - annotated_image_bytes: 1ページ目に丸マーカーを描画したPNG bytes
          - annotations_list: [{label, value, unit, x_pct, y_pct, confidence, category}, ...]
        """
        images, page0_size_mm = self.pdf_to_images(pdf_bytes)
        if not images:
            err = {"error": "PDFのページが読み取れませんでした"}
            return err, None, []

        effective_scale = None
        if stated_scale and stated_scale != "不要" and original_paper and page0_size_mm:
            effective_scale = self.calc_effective_scale(
                stated_scale, original_paper, page0_size_mm
            )

        user_text = "以下の建築図面を解析し、塗装工事見積に必要な建物情報と各寸法の位置情報をJSONで出力してください。"
        if effective_scale:
            user_text += (
                f"\n\n【実効縮尺】{effective_scale}\n"
                f"（元図面: {original_paper} / 縮尺: {stated_scale} → "
                f"スキャン縮小後の実効縮尺として計算済み）\n"
                "立面図の視覚的な比率とこの実効縮尺を使って外壁面積を推定してください。"
            )

        target_images = images[:6]
        content = [{"type": "text", "text": user_text}]
        for img_bytes in target_images:
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"},
            })

        from core.logger import log_gpt_call, log_error
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": DRAWING_SYSTEM_PROMPT_ANNOTATED},
                    {"role": "user",   "content": content},
                ],
                max_tokens=4000,
                temperature=0.1,
            )
            raw = response.choices[0].message.content
            usage = response.usage
            log_gpt_call(
                func_name="DrawingAnalyzer.analyze_with_annotations",
                model=self.model,
                system_prompt=DRAWING_SYSTEM_PROMPT_ANNOTATED,
                user_message_summary=f"[PDF画像{len(target_images)}枚] 縮尺={stated_scale} 用紙={original_paper}",
                response_text=raw,
                tokens_prompt=usage.prompt_tokens if usage else None,
                tokens_completion=usage.completion_tokens if usage else None,
                tokens_total=usage.total_tokens if usage else None,
            )
        except Exception as e:
            log_error("GPTエラー: DrawingAnalyzer.analyze_with_annotations", e, "GPT")
            raise
        
        result = self._parse_response(raw)
        if effective_scale:
            result["_effective_scale"] = effective_scale

        annotations = result.pop("annotations", []) or []

        # 1ページ目の画像にマーカーを描画
        annotated_bytes = None
        if images and annotations:
            try:
                annotated_bytes = self._draw_annotations(images[0], annotations)
            except Exception as draw_err:
                result["_draw_error"] = str(draw_err)
                annotated_bytes = images[0]
        elif images:
            annotated_bytes = images[0]

        # デバッグ用: 生の返答を保持
        result["_raw_gpt_response"] = raw
        result["_annotations_count"] = len(annotations)

        return result, annotated_bytes, annotations

    def _draw_annotations(self, img_bytes: bytes, annotations: list) -> bytes:
        """PILで画像に寸法アノテーション（丸マーカー＋幅矢印）を書き込んで返す"""
        from PIL import Image, ImageDraw, ImageFont
        import io

        img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        W, H = img.size
        radius   = max(14, max(W, H) // 80)
        font_size = max(16, radius)

        try:
            font = ImageFont.load_default(size=font_size)
            font_sm = ImageFont.load_default(size=max(14, font_size - 4))
        except TypeError:
            font = font_sm = ImageFont.load_default()

        def draw_label(draw, text, cx, cy, r, g, b, font):
            try:
                bbox = draw.textbbox((0, 0), text, font=font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
            except AttributeError:
                tw, th = len(text) * font_size // 2, font_size
            tx = cx - tw // 2
            ty = cy - th // 2
            pad = 4
            draw.rounded_rectangle(
                [tx - pad, ty - pad, tx + tw + pad, ty + th + pad],
                radius=4, fill=(r, g, b, 210)
            )
            draw.text((tx, ty), text, fill=(255, 255, 255, 255), font=font)

        for ann in annotations:
            cat = ann.get("category", "other")
            r, g, b = ANNOTATION_COLORS.get(cat, ANNOTATION_COLORS["other"])
            val  = ann.get("value", "")
            unit = ann.get("unit", "")
            label = ann.get("label", "")
            text  = f"{label}  {val}{(' ' + unit) if unit else ''}"

            # ── 幅寸法：両端矢印で描画 ────────────────────────
            if cat == "width" and "x1_pct" in ann and "x2_pct" in ann:
                x1 = int(ann["x1_pct"] / 100 * W)
                x2 = int(ann["x2_pct"] / 100 * W)
                y  = int(ann.get("y_pct", 90) / 100 * H)
                lw = max(3, radius // 5)

                # 水平線
                draw.line([(x1, y), (x2, y)], fill=(r, g, b, 220), width=lw)
                # 左矢頭
                aw = max(10, lw * 4)
                draw.polygon([(x1, y), (x1 + aw, y - aw // 2), (x1 + aw, y + aw // 2)],
                              fill=(r, g, b, 220))
                # 右矢頭
                draw.polygon([(x2, y), (x2 - aw, y - aw // 2), (x2 - aw, y + aw // 2)],
                              fill=(r, g, b, 220))
                # 上下の端線
                tl = max(8, lw * 3)
                draw.line([(x1, y - tl), (x1, y + tl)], fill=(r, g, b, 220), width=lw)
                draw.line([(x2, y - tl), (x2, y + tl)], fill=(r, g, b, 220), width=lw)
                # ラベル（中央上）
                mx = (x1 + x2) // 2
                draw_label(draw, text, mx, y - font_size - 8, r, g, b, font)

            # ── その他：丸マーカー ────────────────────────────
            else:
                x = int(ann.get("x_pct", 50) / 100 * W)
                y = int(ann.get("y_pct", 50) / 100 * H)
                border = max(2, radius // 6)
                draw.ellipse(
                    [x - radius, y - radius, x + radius, y + radius],
                    fill=(r, g, b, 220),
                    outline=(255, 255, 255, 255),
                    width=border,
                )
                # ラベル（右横）
                try:
                    bbox = draw.textbbox((0, 0), text, font=font_sm)
                    tw = bbox[2] - bbox[0]
                    th = bbox[3] - bbox[1]
                except AttributeError:
                    tw, th = len(text) * (font_size - 4) // 2, font_size - 4
                tx = x + radius + 8
                ty = y - th // 2
                if tx + tw + 10 > W:
                    tx = x - radius - tw - 12
                pad = 4
                draw.rounded_rectangle(
                    [tx - pad, ty - pad, tx + tw + pad, ty + th + pad],
                    radius=4, fill=(r, g, b, 210)
                )
                draw.text((tx, ty), text, fill=(255, 255, 255, 255), font=font_sm)

        result = Image.alpha_composite(img, overlay).convert("RGB")
        out = io.BytesIO()
        result.save(out, format="PNG")
        return out.getvalue()

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

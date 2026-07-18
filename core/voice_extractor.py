"""
音声メモ→積算数量 抽出モジュール

役割：
  1. 音声文字起こしテキストから数値・単位・項目をGPT-4oで抽出（_extract_raw）
  2. 抽出できなかった項目を「塗装業の経験則」で自動補完（build_quantities）
  3. STEP3フォームと同じ形式の quantities dict を返す
"""

import json
from typing import Optional


# ─── GPTへ渡す抽出指示 ───────────────────────────────────────────
_EXTRACT_SYSTEM_PROMPT = """あなたは外壁・屋根塗装の積算アシスタントです。
営業担当の音声メモ（文字起こし）から、塗装工事の数量を正確に抽出してください。

【重要：日本語の用語とJSONフィールドの対応】
- wall_area       : 外壁面積（「外壁〇〇平米」「外壁〇〇㎡」）
- roof_area       : 屋根面積（「屋根〇〇平米」「屋根〇〇㎡」）
- fascia_length   : 破風・鼻隠し（「破風〇〇メートル」「鼻隠し〇〇m」）
- gutter_length   : 雨樋（「雨樋〇〇メートル」「といm」）
- water_cutoff_length : 土台水切（「土台水切〇〇メートル」「水切り〇〇m」）
- joint_seal_length   : 目地シーリング・コーキング（「シーリング〇〇メートル」「コーキング〇〇m」）
- soffit_length   : 軒天（「軒天〇〇メートル」「軒〇〇m」）
- guardman_count  : ガードマン・交通誘導員（「ガードマン〇人」）
- do_roof         : 屋根塗装あり（デフォルトtrue）
- do_foundation   : 基礎塗装あり（言及があればtrue）
- floors          : 階数（「〇階建て」）
- discount        : 値引き金額（「値引き〇万円」）

ルール：
- 数値が明示されていない項目は必ず null を返す（推測で埋めない）。
- 「平米」「㎡」「平方メートル」は面積、「メートル」「m」は長さ。
- 屋根種別は スレート / 金属 / 瓦 / 不明 のいずれか。
- 外壁種別は サイディング / モルタル / ALC / 不明 のいずれか。
- 必ず指定のJSON形式のみで返す（説明文は不要）。"""

_EXTRACT_SCHEMA_HINT = """以下のJSON形式で返してください：
{
  "wall_area": 数値またはnull,
  "roof_area": 数値またはnull,
  "fascia_length": 数値またはnull,
  "gutter_length": 数値またはnull,
  "water_cutoff_length": 数値またはnull,
  "joint_seal_length": 数値またはnull,
  "soffit_length": 数値またはnull,
  "roof_type": "スレート/金属/瓦/不明",
  "wall_type": "サイディング/モルタル/ALC/不明",
  "floors": 数値またはnull,
  "do_roof": true/false,
  "do_foundation": true/false,
  "do_shutter_box": true/false,
  "guardman_count": 数値またはnull,
  "misc_cost": 数値またはnull,
  "discount": 数値またはnull,
  "client_name": "文字列またはnull",
  "site_address": "文字列またはnull",
  "notes": "その他気になった情報（数量は上記フィールドに入れること）"
}"""

# 抽出結果の既定値
_RAW_DEFAULTS = {
    "wall_area": None, "roof_area": None, "fascia_length": None,
    "gutter_length": None, "water_cutoff_length": None,
    "joint_seal_length": None, "soffit_length": None,
    "roof_type": "不明", "wall_type": "不明", "floors": None,
    "do_roof": True, "do_foundation": False, "do_shutter_box": False,
    "guardman_count": None, "misc_cost": None, "discount": None,
    "client_name": None, "site_address": None, "notes": "",
}

_ROOF_TYPE_MAP = {
    "スレート": "スレート",
    "金属": "金属屋根（ガルバリウム）",
    "瓦": "日本瓦",
    "不明": "スレート",
}


def _to_float(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _extract_raw(voice_text: str, llm, custom_rules: str = "") -> dict:
    system_prompt = _EXTRACT_SYSTEM_PROMPT
    if custom_rules and custom_rules.strip():
        system_prompt += f"\n\n【会社カスタム積算ルール】\n{custom_rules.strip()}"
    user_message = f"{_EXTRACT_SCHEMA_HINT}\n\nテキスト：「{voice_text}」"
    from core.logger import log_gpt_call, log_error
    try:
        resp = llm.client.chat.completions.create(
            model=llm.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            max_tokens=1500,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        text = resp.choices[0].message.content
        usage = resp.usage
        log_gpt_call(
            func_name="voice_extractor._extract_raw",
            model=llm.model,
            system_prompt=system_prompt,
            user_message_summary=f"音声テキスト: {voice_text[:400]}",
            response_text=text,
            tokens_prompt=usage.prompt_tokens if usage else None,
            tokens_completion=usage.completion_tokens if usage else None,
            tokens_total=usage.total_tokens if usage else None,
        )
    except Exception as e:
        log_error("GPTエラー: voice_extractor._extract_raw", e, "GPT")
        raise
    raw = json.loads(text)
    merged = dict(_RAW_DEFAULTS)
    merged.update({k: v for k, v in raw.items() if k in _RAW_DEFAULTS})
    return merged


def build_quantities(raw: dict) -> dict:
    r = {k: raw.get(k) for k in _RAW_DEFAULTS}

    wall_area = _to_float(r.get("wall_area")) or 0.0
    roof_area = _to_float(r.get("roof_area")) or 0.0
    fascia_length = _to_float(r.get("fascia_length")) or 0.0
    gutter_length = _to_float(r.get("gutter_length")) or 0.0
    water_cutoff_length = _to_float(r.get("water_cutoff_length")) or 0.0

    do_roof = bool(r.get("do_roof", True))

    scaffold_area = round(wall_area * 1.1, 1) if wall_area else 0.0
    roof_scaffold_area = roof_area if (do_roof and roof_area) else 0.0
    soffit_length = _to_float(r.get("soffit_length"))
    if not soffit_length:
        soffit_length = fascia_length
    joint_seal_length = _to_float(r.get("joint_seal_length"))
    if not joint_seal_length:
        joint_seal_length = round(wall_area * 0.85, 1) if wall_area else 0.0

    guardman_count = _to_float(r.get("guardman_count")) or 0
    misc_cost = _to_float(r.get("misc_cost"))
    if not misc_cost:
        misc_cost = 200000
    discount = _to_float(r.get("discount")) or 0

    roof_type_raw = r.get("roof_type") or "不明"
    roof_type = _ROOF_TYPE_MAP.get(roof_type_raw, "スレート")

    quantities = {
        "scaffold_area":      scaffold_area,
        "roof_scaffold_area": roof_scaffold_area,
        "guardman_count":     int(guardman_count),
        "do_lifting":         True,
        "do_transport":       True,
        "do_road_permit":     True,
        "do_protection_pipe": False,
        "do_roof":            do_roof,
        "roof_area":          roof_area,
        "roof_type":          roof_type,
        "roof_paint_spec":    "クールタイトSi",
        "wall_area":          wall_area,
        "wall_paint_spec":    "ラジカル塗料",
        "sub_paint_spec":     "クリーンマイルドシリコン",
        "fascia_length":      fascia_length,
        "soffit_estimate_m":   soffit_length,
        "soffit_entrance_sqm": 0.0,
        "soffit_balcony_sqm":  0.0,
        "gutter_length":      gutter_length,
        "water_cutoff_length": water_cutoff_length,
        "window_top_length":  0.0,
        "beam_length":        0.0,
        "shutter_box_length": 0.0,
        "do_foundation":      bool(r.get("do_foundation", False)),
        "joint_seal_length":  joint_seal_length,
        "do_misc_seal":       True,
        "skylight_count":     0,
        "misc_cost":          int(misc_cost),
        "discount":           int(discount),
    }
    return quantities


def extract_quantities(voice_text: str, llm, custom_rules: str = "") -> dict:
    raw = _extract_raw(voice_text, llm, custom_rules=custom_rules)
    quantities = build_quantities(raw)
    extras = {
        "client_name":  raw.get("client_name"),
        "site_address": raw.get("site_address"),
        "notes":        raw.get("notes", ""),
        "floors":       raw.get("floors"),
        "wall_type":    raw.get("wall_type"),
    }
    return {"quantities": quantities, "raw": raw, "extras": extras}

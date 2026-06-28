"""
音声メモ→積算数量 抽出モジュール

役割：
  1. 音声文字起こしテキストから数値・単位・項目をGPT-4oで抽出（_extract_raw）
  2. 抽出できなかった項目を「塗装業の経験則」で自動補完（build_quantities）
  3. STEP3フォームと同じ形式の quantities dict を返す

設計方針：
  - GPT抽出（API必要）と 経験則補完（純Python・APIなしでテスト可能）を分離。
  - build_quantities() はネットワーク不要なので、サンプル値で合計金額を検証できる。
"""

import json
from typing import Optional


# ─── GPTへ渡す抽出指示 ───────────────────────────────────────────
_EXTRACT_SYSTEM_PROMPT = """あなたは外壁・屋根塗装の積算アシスタントです。
営業担当の音声メモ（文字起こし）から、塗装工事の数量を正確に抽出してください。

ルール：
- 数値が明示されていない項目は必ず null を返す（推測で埋めない）。
- 「平米」「㎡」「平方メートル」は面積、「メートル」「m」は長さ。
- 屋根種別は スレート / 金属 / 瓦 / 不明 のいずれか。
- 外壁種別は サイディング / モルタル / ALC / 不明 のいずれか。
- 「道路使用許可が必要」等の発言があれば notes に残す。
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
  "notes": "その他気になった情報"
}"""

# 抽出結果の既定値（GPTが項目を落としても落ちないように）
_RAW_DEFAULTS = {
    "wall_area": None, "roof_area": None, "fascia_length": None,
    "gutter_length": None, "water_cutoff_length": None,
    "joint_seal_length": None, "soffit_length": None,
    "roof_type": "不明", "wall_type": "不明", "floors": None,
    "do_roof": True, "do_foundation": False, "do_shutter_box": False,
    "guardman_count": None, "misc_cost": None, "discount": None,
    "client_name": None, "site_address": None, "notes": "",
}

# 屋根種別（抽出値→塗料・足場メモ用の表示名）
_ROOF_TYPE_MAP = {
    "スレート": "スレート",
    "金属": "金属屋根（ガルバリウム）",
    "瓦": "日本瓦",
    "不明": "スレート",
}


def _to_float(v) -> Optional[float]:
    """数値文字列・数値をfloatへ。None/空/変換不可はNone。"""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _extract_raw(voice_text: str, llm) -> dict:
    """
    GPT-4oで音声メモから数量を抽出して生dictを返す（経験則補完前）。
    llm: modules.llm_client.LLMClient インスタンス
    """
    user_message = f"{_EXTRACT_SCHEMA_HINT}\n\nテキスト：「{voice_text}」"
    resp = llm.client.chat.completions.create(
        model=llm.model,
        messages=[
            {"role": "system", "content": _EXTRACT_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        max_tokens=1500,
        temperature=0.0,  # 抽出は再現性重視
        response_format={"type": "json_object"},
    )
    text = resp.choices[0].message.content
    raw = json.loads(text)
    # 既定値で穴埋め（GPTが落とした項目対策）
    merged = dict(_RAW_DEFAULTS)
    merged.update({k: v for k, v in raw.items() if k in _RAW_DEFAULTS})
    return merged


def build_quantities(raw: dict) -> dict:
    """
    抽出生dict → 経験則で補完した quantities dict（STEP3フォーム形式）。
    ※ ネットワーク不要。サンプル値での金額検証はこの関数で行える。

    経験則（ルールベース補完）：
      scaffold_area      = wall_area * 1.1      # 足場 = 外壁×1.1
      roof_scaffold_area = roof_area            # 屋根足場 = 屋根面積
      soffit_length      = fascia_length        # 軒天m = 破風m（未入力時）
      joint_seal_length  = wall_area * 0.85     # シーリング = 外壁×0.85（未入力時）
      do_lifting/transport/road_permit/misc_seal = True（常にあり）
      misc_cost          = 200000               # 諸経費デフォルト
    """
    r = {k: raw.get(k) for k in _RAW_DEFAULTS}  # 安全に取り出し

    wall_area = _to_float(r.get("wall_area")) or 0.0
    roof_area = _to_float(r.get("roof_area")) or 0.0
    fascia_length = _to_float(r.get("fascia_length")) or 0.0
    gutter_length = _to_float(r.get("gutter_length")) or 0.0
    water_cutoff_length = _to_float(r.get("water_cutoff_length")) or 0.0

    do_roof = bool(r.get("do_roof", True))

    # ── 経験則補完 ──────────────────────────────────────────
    # 足場 = 外壁 × 1.1
    scaffold_area = round(wall_area * 1.1, 1) if wall_area else 0.0
    # 屋根足場 = 屋根面積
    roof_scaffold_area = roof_area if (do_roof and roof_area) else 0.0
    # 軒天 = 破風（音声で軒天が出なければ破風と同じ）
    soffit_length = _to_float(r.get("soffit_length"))
    if not soffit_length:
        soffit_length = fascia_length
    # シーリング = 外壁 × 0.85（音声で出なければ）
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
        # 仮設工事
        "scaffold_area":      scaffold_area,
        "roof_scaffold_area": roof_scaffold_area,
        "guardman_count":     int(guardman_count),
        "do_lifting":         True,
        "do_transport":       True,
        "do_road_permit":     True,
        "do_protection_pipe": False,
        # 屋根
        "do_roof":            do_roof,
        "roof_area":          roof_area,
        "roof_type":          roof_type,
        "roof_paint_spec":    "クールタイトSi",
        # 外壁
        "wall_area":          wall_area,
        "wall_paint_spec":    "ラジカル塗料",
        "sub_paint_spec":     "クリーンマイルドシリコン",
        # 付帯部
        "fascia_length":      fascia_length,
        "soffit_length":      soffit_length,
        "soffit_sqm":         0.0,
        "gutter_length":      gutter_length,
        "water_cutoff_length": water_cutoff_length,
        "window_top_length":  0.0,
        "beam_length":        0.0,
        "shutter_box_length": 0.0,
        "do_foundation":      bool(r.get("do_foundation", False)),
        # シーリング
        "joint_seal_length":  joint_seal_length,
        "do_misc_seal":       True,
        "skylight_count":     0,
        # 金額調整
        "misc_cost":          int(misc_cost),
        "discount":           int(discount),
    }
    return quantities


def extract_quantities(voice_text: str, llm) -> dict:
    """
    音声メモテキスト → 積算quantities dict（GPT抽出＋経験則補完）。
    抽出した補足情報（顧客名・住所・notes等）も併せて返す。

    Returns:
        {
          "quantities": {...},   # STEP3フォーム形式・calculate_from_quantitiesにそのまま渡せる
          "raw":        {...},   # GPTの生抽出（確認・デバッグ用）
          "extras":     {...},   # client_name / site_address / notes / floors / wall_type
        }
    """
    raw = _extract_raw(voice_text, llm)
    quantities = build_quantities(raw)
    extras = {
        "client_name":  raw.get("client_name"),
        "site_address": raw.get("site_address"),
        "notes":        raw.get("notes", ""),
        "floors":       raw.get("floors"),
        "wall_type":    raw.get("wall_type"),
    }
    return {"quantities": quantities, "raw": raw, "extras": extras}

"""
音声修正→積算数量 更新モジュール

役割：
  1. 修正指示テキスト（音声文字起こし or 手入力）をGPT-4oに渡す
  2. 現在のquantitiesと一緒に渡し「何をどう変えるか」のdiffだけ返させる
  3. 変更がない項目はnull → 上書きしない（apply_diff）
  4. 更新後のquantities ＋ 変更内容リストを返す

設計方針（voice_extractor.py と同じ）：
  - GPT抽出（_extract_diff・API必要）と
    マージ処理（apply_diff・純Python・APIなしでテスト可能）を分離。
"""

import json
from typing import Optional


# ─── 調整可能な数量フィールド（表示名・単位）───────────────────
# 数値項目
_NUMERIC_META = {
    "wall_area":           ("外壁面積",       "㎡"),
    "roof_area":           ("屋根面積",       "㎡"),
    "scaffold_area":       ("外部足場",       "㎡"),
    "roof_scaffold_area":  ("屋根足場",       "㎡"),
    "fascia_length":       ("破風・鼻隠し",   "m"),
    "soffit_estimate_m":   ("軒天",           "m"),
    "gutter_length":       ("雨樋",           "m"),
    "water_cutoff_length": ("土台水切",       "m"),
    "joint_seal_length":   ("目地シーリング", "m"),
    "guardman_count":      ("ガードマン",     "人"),
    "skylight_count":      ("トップライト",   "箇所"),
    "discount":            ("値引き",         "円"),
    "misc_cost":           ("諸経費",         "円"),
}
# 整数で扱う項目（人数・箇所・金額）
_INT_FIELDS = {"guardman_count", "skylight_count", "discount", "misc_cost"}

# 真偽項目（実施する/しない）
_BOOL_META = {
    "do_roof":            "屋根塗装",
    "do_foundation":      "基礎塗装",
    "do_misc_seal":       "雑シーリング",
    "do_lifting":         "昇降設備",
    "do_transport":       "運搬費",
    "do_road_permit":     "道路使用許可",
    "do_protection_pipe": "防護管",
}


# ─── GPTへ渡す修正指示プロンプト ─────────────────────────────
_ADJUST_SYSTEM_PROMPT = """あなたは外壁・屋根塗装の積算修正アシスタントです。
営業担当の修正指示を解釈し、変更が必要な項目だけをJSONで返してください。

ルール：
- 変更が不要な項目は必ず null を返す（推測で埋めない）。
- 修正指示で明確に言及された項目だけ数値または真偽を返す。
- 「不要」「やめる」「なし」→ false、「やる」「追加」→ true。
- 「平米」「㎡」は面積、「メートル」「m」は長さ、「人」は人数。
- 値引き・諸経費は円。「5万」は50000、「3万円」は30000。
- 必ず指定のJSON形式のみで返す（説明文はexplanationに入れる）。"""


def _schema_hint() -> str:
    """調整可能フィールドからJSONスキーマのヒント文を生成。"""
    lines = ["以下のJSON形式で返してください（変更しない項目はnull）：", "{"]
    for f in _NUMERIC_META:
        lines.append(f'  "{f}": 数値またはnull,')
    for f in _BOOL_META:
        lines.append(f'  "{f}": true/false/null,')
    lines.append('  "explanation": "変更内容の説明（日本語・簡潔に）"')
    lines.append("}")
    return "\n".join(lines)


def _to_float(v) -> Optional[float]:
    """数値文字列・数値をfloatへ。None/空/変換不可はNone。"""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fmt_value(field: str, value) -> str:
    """変更前後の値を表示用文字列へ整形。"""
    if field in _BOOL_META:
        return "あり" if value else "なし"
    label, unit = _NUMERIC_META.get(field, ("", ""))
    if unit == "円":
        return f"¥{int(value):,}"
    # 末尾の .0 を落として見やすく
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{value}{unit}"


def _extract_diff(current_quantities: dict, correction_text: str, llm) -> dict:
    """
    GPT-4oで修正指示を解釈し、変更diff（生dict）を返す。
    llm: modules.llm_client.LLMClient インスタンス
    """
    # GPTに渡す現在値（調整可能な項目のみ）
    fields = list(_NUMERIC_META) + list(_BOOL_META)
    current_subset = {f: current_quantities.get(f) for f in fields}

    user_message = (
        f"現在の積算数量：\n{json.dumps(current_subset, ensure_ascii=False, indent=2)}\n\n"
        f"修正指示：「{correction_text}」\n\n"
        f"{_schema_hint()}"
    )
    resp = llm.client.chat.completions.create(
        model=llm.model,
        messages=[
            {"role": "system", "content": _ADJUST_SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
        max_tokens=1200,
        temperature=0.0,  # 修正解釈は再現性重視
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content)


def apply_diff(current_quantities: dict, diff: dict) -> dict:
    """
    変更diff → 更新後quantities ＋ 変更内容リスト（純Python・APIなしでテスト可）。

    Returns:
        {
          "quantities":  {...},   # 更新後（変更が無ければ元のまま）
          "changes":     [ {field,label,unit,before,after,text}, ... ],
          "explanation": "...",   # GPTの説明（無ければ自動生成）
        }
    """
    new_q = dict(current_quantities)
    changes = []

    # ── 数値項目 ────────────────────────────────────────────
    for field, (label, unit) in _NUMERIC_META.items():
        raw = diff.get(field)
        if raw is None:
            continue
        nv = _to_float(raw)
        if nv is None:
            continue
        nv = int(round(nv)) if field in _INT_FIELDS else float(nv)
        old = _to_float(current_quantities.get(field)) or 0
        old = int(round(old)) if field in _INT_FIELDS else float(old)
        if old != nv:
            new_q[field] = nv
            changes.append({
                "field":  field,
                "label":  label,
                "unit":   unit,
                "before": old,
                "after":  nv,
                "text":   f"{label}：{_fmt_value(field, old)} → {_fmt_value(field, nv)}",
            })

    # ── 真偽項目 ────────────────────────────────────────────
    for field, label in _BOOL_META.items():
        raw = diff.get(field)
        if raw is None:
            continue
        nv = bool(raw)
        old = bool(current_quantities.get(field, False))
        if old != nv:
            new_q[field] = nv
            changes.append({
                "field":  field,
                "label":  label,
                "unit":   "",
                "before": old,
                "after":  nv,
                "text":   f"{label}：{_fmt_value(field, old)} → {_fmt_value(field, nv)}",
            })

    explanation = diff.get("explanation") or ""
    if not explanation:
        explanation = "、".join(c["text"] for c in changes) if changes else "変更点はありませんでした"

    return {"quantities": new_q, "changes": changes, "explanation": explanation}


def adjust_quantities(current_quantities: dict, correction_text: str, llm) -> dict:
    """
    修正指示テキストからquantitiesを更新して返す。
    変更がない項目は元の値を維持する。

    Returns:
        {
          "quantities":  {...},  # 更新後・calculate_from_quantitiesにそのまま渡せる
          "changes":     [...],  # 変更内容リスト（表示用 text 付き）
          "explanation": "...",  # 変更の要約説明
          "diff":        {...},  # GPTの生diff（デバッグ用）
        }
    """
    diff = _extract_diff(current_quantities, correction_text, llm)
    result = apply_diff(current_quantities, diff)
    result["diff"] = diff
    return result

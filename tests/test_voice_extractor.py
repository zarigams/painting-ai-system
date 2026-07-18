# -*- coding: utf-8 -*-
"""
voice_extractor / quantity_calculator / quantity_adjuster / logger の統合テスト
APIなしで実行可能（build_quantities・calculate_from_quantities・apply_diff・logger）

目標値の根拠（CLAUDE.md 参照）:
  音声抽出パス（soffit_entrance/balcony_sqm = 0）: 合計 ¥3,032,297
  手動入力フル（軒天玄関庇 7.5㎡含む）          : 合計 ¥3,040,135
  旧基準値 ¥3,004,836 は軒天3項目化前の誤記。現コードでは再現不可。
"""
import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.voice_extractor import build_quantities
from core.quantity_calculator import calculate_from_quantities
from core.quantity_adjuster import apply_diff


# ──────────────────────────────────────────────
# 共通テストデータ
# ──────────────────────────────────────────────

# (A) 音声メモ通りの丸め値
RAW_VOICE = {
    "wall_area": 237, "roof_area": 190, "fascia_length": 74,
    "gutter_length": 92, "water_cutoff_length": 49,
    "joint_seal_length": 202, "soffit_length": None,
    "roof_type": "スレート", "wall_type": "サイディング", "floors": 2,
    "do_roof": True, "do_foundation": False, "do_shutter_box": False,
    "guardman_count": None, "misc_cost": None, "discount": None,
    "client_name": "住吉屋", "site_address": None, "notes": "道路使用許可必要",
}

# (B) サンプル実測値（音声パス）— soffit_entrance/balcony_sqm は 0（音声未入力）
RAW_EXACT = dict(RAW_VOICE)
RAW_EXACT.update({
    "wall_area": 237.595, "roof_area": 189.87, "fascia_length": 74.6,
    "gutter_length": 92.4, "water_cutoff_length": 48.9,
    "joint_seal_length": 202.1, "soffit_length": 74.6,
})

# (C) 手動入力フル（玄関庇 7.5㎡ 含む）→ CLAUDE.md 正解値 ¥3,040,135
QUANTITIES_FULL = dict(build_quantities(RAW_EXACT))
QUANTITIES_FULL["soffit_entrance_sqm"] = 7.5   # 手動入力


# ──────────────────────────────────────────────
# 1. soffit_estimate_m の確認
# ──────────────────────────────────────────────

def test_soffit_estimate_m_from_voice():
    """soffit_length = 74.6 のraw → soffit_estimate_m = 74.6"""
    q = build_quantities(RAW_EXACT)
    assert q.get("soffit_estimate_m") == pytest.approx(74.6, abs=0.01)


def test_soffit_fallback_to_fascia():
    """soffit_length = None のとき soffit_estimate_m は fascia_length と同値"""
    q = build_quantities(RAW_VOICE)
    assert q.get("soffit_estimate_m") == pytest.approx(q["fascia_length"], abs=0.01)


# ──────────────────────────────────────────────
# 2. 軒天金額
# ──────────────────────────────────────────────

def test_soffit_amount_70870():
    """74.6m × ¥950 = ¥70,870"""
    q = build_quantities(RAW_EXACT)
    est = calculate_from_quantities(q)
    soffit_items = [i for i in est["estimation_items"] if "軒天" in i["item_name"]]
    soffit_total = sum(i["amount"] for i in soffit_items)
    assert soffit_total == 70870


# ──────────────────────────────────────────────
# 3. 合計金額
# ──────────────────────────────────────────────

def test_total_voice_path():
    """音声パス（soffit_entrance/balcony_sqm = 0）合計 ¥3,032,297"""
    q = build_quantities(RAW_EXACT)
    est = calculate_from_quantities(q)
    assert est["total"] == 3_032_297


def test_total_full_manual():
    """手動入力フル（玄関庇 7.5㎡含む）合計 ¥3,040,135（CLAUDE.md正解値）"""
    est = calculate_from_quantities(QUANTITIES_FULL)
    assert est["total"] == 3_040_135


# ──────────────────────────────────────────────
# 4. 旧キー互換性
# ──────────────────────────────────────────────

def test_compat_old_soffit_length():
    """旧キー soffit_length を持つ quantities でも正常計算される"""
    old_q = dict(build_quantities(RAW_EXACT))
    # 旧キーに差し替え（過去案件JSONを模倣）
    old_q["soffit_length"] = old_q.pop("soffit_estimate_m")
    assert "soffit_estimate_m" not in old_q

    est = calculate_from_quantities(old_q)
    assert est["total"] == 3_032_297  # 音声パスと同じ値になる


def test_compat_old_soffit_sqm():
    """旧キー soffit_sqm を持つ quantities でも正常計算される"""
    old_q = dict(build_quantities(RAW_EXACT))
    old_q["soffit_sqm"] = 5.0  # 旧キー
    # soffit_entrance/balcony_sqm があれば新キー優先
    old_q.pop("soffit_entrance_sqm", None)
    old_q.pop("soffit_balcony_sqm", None)

    est = calculate_from_quantities(old_q)
    soffit_items = [i for i in est["estimation_items"] if "軒天" in i["item_name"]]
    # 74.6m + 5.0㎡ のアイテムが存在する
    assert len(soffit_items) >= 2


def test_compat_new_key_wins_when_both_present():
    """旧キーと新キーが両方ある場合は新キーを優先する"""
    q = dict(build_quantities(RAW_EXACT))
    q["soffit_length"] = 99.9          # 旧キー（ダミー値）
    # 新キーは build_quantities が設定した 74.6 のまま
    assert q.get("soffit_estimate_m") == pytest.approx(74.6, abs=0.01)

    est = calculate_from_quantities(q)
    # 新キー(74.6m)で計算されるはず
    soffit_m_items = [i for i in est["estimation_items"]
                      if "破風m合わせ" in i["item_name"]]
    assert len(soffit_m_items) == 1
    assert soffit_m_items[0]["quantity"] == pytest.approx(74.6, abs=0.01)


def test_compat_input_dict_not_mutated():
    """旧キー互換マイグレーションが元の入力dictを破壊しない"""
    old_q = {
        "wall_area": 237.595, "roof_area": 189.87, "scaffold_area": 261.4,
        "fascia_length": 74.6, "soffit_length": 74.6, "soffit_sqm": 0.0,
        "gutter_length": 92.4, "water_cutoff_length": 48.9,
        "joint_seal_length": 202.1, "do_misc_seal": True,
        "do_road_permit": True, "do_transport": True, "do_lifting": True,
        "do_protection_pipe": False, "do_foundation": False, "do_roof": True,
        "roof_area": 189.87, "misc_cost": 200000, "discount": 0,
        "guardman_count": 0, "skylight_count": 0,
    }
    original_keys = set(old_q.keys())
    calculate_from_quantities(old_q)
    assert set(old_q.keys()) == original_keys, "入力dictのキーが変更されている"
    assert "soffit_length" in old_q, "元dictから旧キーが消えている"


# ──────────────────────────────────────────────
# 5. quantity_adjuster — soffit_estimate_m の音声修正
# ──────────────────────────────────────────────

def test_adjuster_new_key():
    """apply_diff で 'soffit_estimate_m' が更新される"""
    q = build_quantities(RAW_EXACT)
    diff = {"soffit_estimate_m": 80.0, "explanation": "軒天80mに修正"}
    result = apply_diff(q, diff)
    assert result["quantities"]["soffit_estimate_m"] == pytest.approx(80.0, abs=0.01)
    assert any(c["field"] == "soffit_estimate_m" for c in result["changes"])


def test_adjuster_no_soffit_length_key():
    """apply_diff のキーセットに soffit_length は存在しない"""
    from core.quantity_adjuster import _NUMERIC_META
    assert "soffit_length" not in _NUMERIC_META
    assert "soffit_estimate_m" in _NUMERIC_META


# ──────────────────────────────────────────────
# 6. logger — 機密情報が JSONL に保存されないこと
# ──────────────────────────────────────────────

def _read_last_log_entry(log_file: Path) -> dict:
    lines = [l.strip() for l in log_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    return json.loads(lines[-1])


def test_logger_gpt_no_response_text(tmp_path, monkeypatch):
    """log_gpt_call: response_full・system_prompt・user_message_summary が保存されない"""
    monkeypatch.setattr("core.logger.LOG_DIR", tmp_path)
    monkeypatch.setattr("core.logger._get_company_id", lambda: "test")

    from core.logger import log_gpt_call
    log_gpt_call(
        func_name="test_func",
        model="gpt-4o",
        system_prompt="【機密】system prompt全文",
        user_message_summary="【機密】顧客田中様の物件情報",
        response_text="【機密】GPT回答全文：顧客名住所電話番号",
        tokens_prompt=100, tokens_completion=50, tokens_total=150,
    )

    log_file = tmp_path / "test" / f"{__import__('datetime').date.today()}.jsonl"
    entry = _read_last_log_entry(log_file)
    text = json.dumps(entry, ensure_ascii=False)

    assert "機密" not in text, "機密文字列がログに保存されている"
    assert "顧客" not in text, "顧客情報がログに保存されている"
    assert "system prompt全文" not in text
    assert "GPT回答全文" not in text
    # 保存されるべき項目が存在する
    assert entry["data"]["func"] == "test_func"
    assert entry["data"]["model"] == "gpt-4o"
    assert entry["data"]["response_length"] > 0
    assert entry["data"]["tokens_total"] == 150


def test_logger_whisper_no_transcript(tmp_path, monkeypatch):
    """log_whisper: transcript本文が保存されない。文字数のみ記録される"""
    monkeypatch.setattr("core.logger.LOG_DIR", tmp_path)
    monkeypatch.setattr("core.logger._get_company_id", lambda: "test")

    from core.logger import log_whisper
    log_whisper(
        transcript="【機密】顧客様のご住所は東京都渋谷区〇〇1-2-3です",
        audio_size_bytes=512000,
    )

    log_file = tmp_path / "test" / f"{__import__('datetime').date.today()}.jsonl"
    entry = _read_last_log_entry(log_file)
    text = json.dumps(entry, ensure_ascii=False)

    assert "機密" not in text
    assert "渋谷区" not in text
    assert entry["data"]["transcript_len"] > 0
    assert entry["data"]["audio_size_bytes"] == 512000


def test_logger_error_no_traceback(tmp_path, monkeypatch):
    """log_error: traceback・error_msg全文が保存されない"""
    monkeypatch.setattr("core.logger.LOG_DIR", tmp_path)
    monkeypatch.setattr("core.logger._get_company_id", lambda: "test")

    from core.logger import log_error
    try:
        raise ValueError("【機密】APIキー sk-secret-xxxxx")
    except ValueError as e:
        log_error("テストエラー", e)

    log_file = tmp_path / "test" / f"{__import__('datetime').date.today()}.jsonl"
    entry = _read_last_log_entry(log_file)
    text = json.dumps(entry, ensure_ascii=False)

    assert "sk-secret" not in text, "APIキーがログに保存されている"
    assert "機密" not in text
    # error_type は保存される
    assert entry["data"]["error_type"] == "ValueError"


def test_logger_file_no_filename(tmp_path, monkeypatch):
    """log_file: filenameが保存されない（拡張子のみ記録）"""
    monkeypatch.setattr("core.logger.LOG_DIR", tmp_path)
    monkeypatch.setattr("core.logger._get_company_id", lambda: "test")

    from core.logger import log_file
    log_file("Excel生成成功", "田中様_住吉屋邸_見積書_2026.xlsx", size_bytes=45000)

    log_file_path = tmp_path / "test" / f"{__import__('datetime').date.today()}.jsonl"
    entry = _read_last_log_entry(log_file_path)
    text = json.dumps(entry, ensure_ascii=False)

    assert "田中" not in text, "顧客名を含むファイル名がログに保存されている"
    assert "住吉屋" not in text
    assert entry["data"]["file_ext"] == ".xlsx"
    assert entry["data"]["size_bytes"] == 45000


def test_logger_admin_no_rules_content(tmp_path, monkeypatch):
    """log_admin: 会社独自積算ルール本文が保存されない（文字数のみ）"""
    monkeypatch.setattr("core.logger.LOG_DIR", tmp_path)
    monkeypatch.setattr("core.logger._get_company_id", lambda: "test")

    from core.logger import log_admin
    secret_rule = "【機密】当社独自ルール：軒天は必ず3割増で計上。顧客の田中様専用割引あり。"
    log_admin("積算ルール保存", {"rules_length": len(secret_rule)})

    log_file_path = tmp_path / "test" / f"{__import__('datetime').date.today()}.jsonl"
    entry = _read_last_log_entry(log_file_path)
    text = json.dumps(entry, ensure_ascii=False)

    assert "機密" not in text, "機密文字列がログに保存されている"
    assert "独自ルール" not in text, "積算ルール本文がログに保存されている"
    assert "田中" not in text, "顧客名がログに保存されている"
    assert entry["data"]["rules_length"] == len(secret_rule)


def test_logger_comprehensive_no_pii(tmp_path, monkeypatch):
    """機密情報カテゴリ横断チェック: 顧客名・住所・GPT回答・文字起こし・ルール本文が
    いずれもJSONLに保存されないことをまとめて確認する"""
    monkeypatch.setattr("core.logger.LOG_DIR", tmp_path)
    monkeypatch.setattr("core.logger._get_company_id", lambda: "test")

    from core.logger import log_gpt_call, log_whisper, log_error, log_file, log_admin

    # 1. GPT呼び出し（system prompt + user message + response 全文）
    log_gpt_call(
        func_name="test",
        model="gpt-4o",
        system_prompt="顧客住所：東京都新宿区XXX / 会社ルール：外壁は5割増",
        user_message_summary="田中様 / 東京都渋谷区代々木1-1 / TEL 03-XXXX-XXXX",
        response_text="GPT応答：山田太郎様のご住所は〒150-0001 渋谷区神宮前X-X-X",
        tokens_prompt=200, tokens_completion=100, tokens_total=300,
    )

    # 2. Whisper文字起こし
    log_whisper(
        transcript="お客様の佐藤様、東京都港区赤坂2-2-2、電話03-5555-6666",
        audio_size_bytes=1024000,
    )

    # 3. エラー（APIキー露出の可能性）
    try:
        raise RuntimeError("openai.AuthenticationError: sk-proj-AbCdEf123456 is invalid")
    except RuntimeError as e:
        log_error("APIエラー", e)

    # 4. ファイル名（顧客名入り）
    log_file("ファイル生成", "鈴木様_渋谷区_2026年見積書.xlsx", size_bytes=32000)

    # 5. 積算ルール本文
    log_admin("ルール保存", {"rules_length": 100})

    log_file_path = tmp_path / "test" / f"{__import__('datetime').date.today()}.jsonl"
    all_text = log_file_path.read_text(encoding="utf-8")

    # 顧客名・住所
    assert "田中" not in all_text, "顧客名(田中)がJSONLに保存されている"
    assert "佐藤" not in all_text, "顧客名(佐藤)がJSONLに保存されている"
    assert "鈴木" not in all_text, "顧客名(鈴木)がJSONLに保存されている"
    assert "渋谷区" not in all_text, "住所がJSONLに保存されている"
    assert "赤坂" not in all_text, "住所がJSONLに保存されている"
    assert "新宿区" not in all_text, "住所がJSONLに保存されている"
    # 電話番号
    assert "03-5555" not in all_text, "電話番号がJSONLに保存されている"
    # GPT回答全文
    assert "GPT応答" not in all_text, "GPT回答全文がJSONLに保存されている"
    assert "神宮前" not in all_text, "GPT回答内の住所がJSONLに保存されている"
    # system prompt本文
    assert "外壁は5割増" not in all_text, "system prompt本文（会社ルール）がJSONLに保存されている"
    assert "顧客住所" not in all_text, "system prompt本文がJSONLに保存されている"
    # Whisper文字起こし本文
    assert "赤坂2-2-2" not in all_text, "Whisper文字起こしがJSONLに保存されている"
    assert "お客様の佐藤様" not in all_text, "Whisper文字起こしがJSONLに保存されている"
    # APIキー
    assert "sk-proj" not in all_text, "APIキーがJSONLに保存されている"
    # ファイル名
    assert "鈴木様_渋谷区" not in all_text, "顧客名入りファイル名がJSONLに保存されている"


# ──────────────────────────────────────────────
# 手動実行時の表示（pytest外）
# ──────────────────────────────────────────────

if __name__ == "__main__":
    q_voice = build_quantities(RAW_VOICE)
    est_voice = calculate_from_quantities(q_voice)
    print("\n=== (A) 音声メモ（丸め値） ===")
    print(f"  外壁{q_voice['wall_area']} 屋根{q_voice['roof_area']} "
          f"足場{q_voice['scaffold_area']} "
          f"軒天{q_voice.get('soffit_estimate_m', 0.0):.1f}m "
          f"目地{q_voice['joint_seal_length']}")
    print(f"  合計(税込): \\{est_voice['total']:,}")

    q_exact = build_quantities(RAW_EXACT)
    est_exact = calculate_from_quantities(q_exact)
    print("\n=== (B) サンプル実測値（音声パス） ===")
    print(f"  外壁{q_exact['wall_area']} 屋根{q_exact['roof_area']} "
          f"足場{q_exact['scaffold_area']} "
          f"軒天{q_exact.get('soffit_estimate_m', 0.0):.1f}m "
          f"目地{q_exact['joint_seal_length']}")
    print(f"  合計(税込): \\{est_exact['total']:,}  (目標: ¥3,032,297)")

    est_full = calculate_from_quantities(QUANTITIES_FULL)
    print("\n=== (C) 手動入力フル（玄関庇7.5㎡含む） ===")
    print(f"  合計(税込): \\{est_full['total']:,}  (目標: ¥3,040,135 / CLAUDE.md正解値)")

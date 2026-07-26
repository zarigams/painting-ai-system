# -*- coding: utf-8 -*-
"""
test_baseline機能のうち、Streamlitへ依存しない純粋関数
（should_create_test_baseline / get_app_commit）の検証。

core/estimate_storage.py 自体がStreamlitをimportしていないため、
このファイルはStreamlitを起動せず通常のpytestで実行できる。
"""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import estimate_storage as es


# ═══════════════════════════════════════════════════════════════
# should_create_test_baseline()
# ═══════════════════════════════════════════════════════════════

def test_should_create_when_new_case_and_no_baseline_and_ai_used():
    """新規案件（current_case_id=None）かつbaseline未設定・AI解析成功時だけ生成する"""
    assert es.should_create_test_baseline(
        current_case_id=None, test_baseline=None, ai_analysis_used=True,
    ) is True


def test_should_not_create_when_new_case_but_baseline_already_set():
    """新規案件でもbaseline設定済みなら再生成しない（同一セッション内の再実行対策）"""
    existing = {"ai_initial_quantities": {}, "input_sources": []}
    assert es.should_create_test_baseline(
        current_case_id=None, test_baseline=existing, ai_analysis_used=True,
    ) is False


def test_should_not_create_when_existing_case_has_baseline():
    """baseline付き既存案件（current_case_idあり）では生成しない"""
    existing = {"ai_initial_quantities": {}, "input_sources": []}
    assert es.should_create_test_baseline(
        current_case_id="abc123", test_baseline=existing, ai_analysis_used=True,
    ) is False


def test_should_not_create_when_existing_case_has_no_baseline():
    """baselineなし旧案件（current_case_idあり・test_baseline=None）でも生成しない
    （＝旧案件への後付け禁止。既存案件読込後にSTEP2へ戻ったケースもこれに該当する）"""
    assert es.should_create_test_baseline(
        current_case_id="abc123", test_baseline=None, ai_analysis_used=True,
    ) is False


def test_should_not_create_when_ai_analysis_not_used():
    """AI解析を使っていない（＝手動経路）場合は、新規案件・baseline未設定でも生成しない"""
    assert es.should_create_test_baseline(
        current_case_id=None, test_baseline=None, ai_analysis_used=False,
    ) is False


@pytest.mark.parametrize("falsy_value", [False, 0, "", [], None])
def test_should_not_create_with_various_falsy_ai_analysis_used(falsy_value):
    """ai_analysis_used に bool(successful_input_sources) の結果として
    渡りうる偽値（空リストのbool化を含む）のいずれでもFalseになること"""
    assert es.should_create_test_baseline(
        current_case_id=None, test_baseline=None, ai_analysis_used=falsy_value,
    ) is False


# ═══════════════════════════════════════════════════════════════
# get_app_commit() / _normalize_commit_candidate()
# ═══════════════════════════════════════════════════════════════

VALID_HASH_40 = "0123456789abcdef0123456789abcdef01234567"
VALID_HASH_7 = "0123abc"


def test_get_app_commit_prefers_secret_value_when_valid():
    result = es.get_app_commit(
        secret_value=VALID_HASH_40, env_value=VALID_HASH_7, repo_root=Path("/tmp"),
    )
    assert result == VALID_HASH_40


def test_get_app_commit_falls_back_to_env_value_when_secret_invalid():
    result = es.get_app_commit(
        secret_value="not-a-valid-hash!!", env_value=VALID_HASH_7, repo_root=Path("/tmp"),
    )
    assert result == VALID_HASH_7


def test_get_app_commit_normalizes_case_and_whitespace():
    result = es.get_app_commit(
        secret_value=f"  {VALID_HASH_40.upper()}  ", env_value=None,
    )
    assert result == VALID_HASH_40


@pytest.mark.parametrize("invalid_secret", ["", "zz", "not-hex", 12345, True, None])
def test_get_app_commit_ignores_invalid_secret_and_proceeds(invalid_secret):
    """不正なAPP_COMMIT_SHA（Secrets由来）を無視して次の取得方法（環境変数）へ進む"""
    result = es.get_app_commit(
        secret_value=invalid_secret, env_value=VALID_HASH_7, repo_root=Path("/tmp"),
    )
    assert result == VALID_HASH_7


@pytest.mark.parametrize("invalid_env", ["", "zz", "not-hex", 12345, True, None])
def test_get_app_commit_ignores_invalid_env_and_falls_back_to_git(invalid_env, tmp_path):
    """不正なAPP_COMMIT_SHA（環境変数由来）を無視して次の取得方法（git）へ進む"""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
    (repo / "f.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    expected = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()

    result = es.get_app_commit(secret_value=None, env_value=invalid_env, repo_root=repo)
    assert result == expected


def test_get_app_commit_uses_git_when_no_secret_or_env(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
    (repo / "f.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    expected = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()

    result = es.get_app_commit(secret_value=None, env_value=None, repo_root=repo)
    assert result == expected


def test_get_app_commit_returns_unknown_when_all_unavailable(tmp_path):
    """secret/env/gitのいずれも取得できない場合はunknownになる（gitリポジトリでない空ディレクトリ）"""
    empty_dir = tmp_path / "not_a_repo"
    empty_dir.mkdir()
    result = es.get_app_commit(secret_value=None, env_value=None, repo_root=empty_dir)
    assert result == "unknown"


def test_get_app_commit_does_not_raise_when_git_missing(tmp_path, monkeypatch):
    """git実行自体が失敗する環境でも例外を送出せず unknown を返す"""
    monkeypatch.setattr(
        es.subprocess, "run",
        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("git not found")),
    )
    result = es.get_app_commit(secret_value=None, env_value=None, repo_root=tmp_path)
    assert result == "unknown"


# ═══════════════════════════════════════════════════════════════
# build_test_baseline()
#
# app.pyはSTEP2の自動積算成功直後にこの関数を呼び出し、戻り値をそのまま
# st.session_state.test_baseline へ代入する。ここでの最重要検証は、
# 「本関数呼び出し後に呼び出し元がai_initial_quantitiesの元dictを
# in-place変更しても、戻り値（＝session_stateに格納された値）は
# 一切影響を受けない」という、write-once実現の核心部分である。
# ═══════════════════════════════════════════════════════════════

_UNSET = object()


def _valid_build_kwargs(
    ai_initial_quantities=_UNSET,
    input_sources=("voice", "drawing_pdf"),
    app_commit="0123456789abcdef0123456789abcdef01234567",
    analysis_started_at="2026-07-25T10:00:00+09:00",
    analysis_completed_at="2026-07-25T10:00:30+09:00",
):
    """build_test_baseline() へ渡す正常なkwargsを組み立てる。
    引数を明示的に渡した場合はそのまま使う（Noneや非list値をテストするため、
    Noneをデフォルト値扱いにしない。list/tuple以外はそのまま通す）。"""
    if ai_initial_quantities is _UNSET:
        ai_initial_quantities = {"wall_area": 100.0}
    if isinstance(input_sources, (list, tuple)):
        input_sources = list(input_sources)
    return dict(
        ai_initial_quantities=ai_initial_quantities,
        input_sources=input_sources,
        app_commit=app_commit,
        analysis_started_at=analysis_started_at,
        analysis_completed_at=analysis_completed_at,
    )


def test_build_test_baseline_happy_path_derives_models_and_prompt_versions():
    result = es.build_test_baseline(**_valid_build_kwargs(
        input_sources=["voice", "drawing_pdf", "floor_plan", "photos"],
    ))
    assert result["ai_initial_quantities"] == {"wall_area": 100.0}
    assert result["app_commit"] == "0123456789abcdef0123456789abcdef01234567"
    assert result["input_sources"] == ["voice", "drawing_pdf", "floor_plan", "photos"]
    assert result["models"] == {
        "voice": "gpt-4o", "drawing": "gpt-4o", "floor_plan": "gpt-4o", "photo": "gpt-4o",
    }
    assert result["prompt_versions"] == {
        "voice": "voice_extractor_v1",
        "drawing": "drawing_analyzer_v1",
        "floor_plan": "floor_plan_analyzer_v1",
        "photo": "image_analyzer_v1",
    }
    assert result["pipeline_version"] == "legacy_analysis_v1"
    assert result["rule_version"] == "NESESTYLE_rule_v1.0"
    assert result["analysis_started_at"] == "2026-07-25T10:00:00+09:00"
    assert result["analysis_completed_at"] == "2026-07-25T10:00:30+09:00"
    assert set(result.keys()) == es._TEST_BASELINE_NORMALIZED_KEYS


# ── 【重要・回帰テスト】呼び出し後に元のai_initial_quantities dictを
# in-place変更しても、build_test_baseline()の戻り値は一切影響を受けない ──
def test_build_test_baseline_result_is_independent_of_later_mutation_of_original_quantities():
    original_quantities = {"wall_area": 100.0, "nested": {"a": 1}, "list": [1, 2, 3]}
    result = es.build_test_baseline(**_valid_build_kwargs(
        ai_initial_quantities=original_quantities,
    ))

    # build_test_baseline() 呼び出し「後」に、呼び出し元が保持している
    # 元のdict（app.py側のquantities/st.session_state.quantities相当）を
    # in-place変更する（再計算・幾何学計算値の反映・数量確認フォーム編集を模擬）。
    original_quantities["wall_area"] = 999.0
    original_quantities["nested"]["a"] = 999
    original_quantities["list"].append(4)
    original_quantities["new_key"] = "should not appear"

    assert result["ai_initial_quantities"] == {
        "wall_area": 100.0, "nested": {"a": 1}, "list": [1, 2, 3],
    }


def test_build_test_baseline_returns_dict_not_referencing_input_object():
    """戻り値のai_initial_quantitiesが、入力dictそのもの（同一オブジェクト）ではないこと。"""
    original_quantities = {"wall_area": 100.0}
    result = es.build_test_baseline(**_valid_build_kwargs(
        ai_initial_quantities=original_quantities,
    ))
    assert result["ai_initial_quantities"] is not original_quantities


# ── 異常系: ai_initial_quantities が dict でない ──
@pytest.mark.parametrize("bad_quantities", ["not a dict", 123, None, []])
def test_build_test_baseline_rejects_non_dict_quantities(bad_quantities):
    with pytest.raises(ValueError):
        es.build_test_baseline(**_valid_build_kwargs(ai_initial_quantities=bad_quantities))


# ── 異常系: app_commit の形式不正を拒否する ──
@pytest.mark.parametrize("bad_commit", ["", "not-hex-zzz", "123", 12345, None, True])
def test_build_test_baseline_rejects_invalid_app_commit(bad_commit):
    with pytest.raises(ValueError):
        es.build_test_baseline(**_valid_build_kwargs(app_commit=bad_commit))


def test_build_test_baseline_accepts_unknown_app_commit():
    result = es.build_test_baseline(**_valid_build_kwargs(app_commit="unknown"))
    assert result["app_commit"] == "unknown"


# ── 異常系: 許可外のinput_sources値を拒否する ──
def test_build_test_baseline_rejects_unknown_input_source():
    with pytest.raises(ValueError):
        es.build_test_baseline(**_valid_build_kwargs(input_sources=["voice", "unknown_source"]))


# ── 異常系: input_sourcesの重複を拒否する ──
def test_build_test_baseline_rejects_duplicate_input_sources():
    with pytest.raises(ValueError):
        es.build_test_baseline(**_valid_build_kwargs(input_sources=["voice", "voice"]))


# ── 異常系: input_sources が list[str] でない ──
@pytest.mark.parametrize("bad_sources", ["voice", 123, None, ["voice", 123]])
def test_build_test_baseline_rejects_non_list_of_str_input_sources(bad_sources):
    with pytest.raises(ValueError):
        es.build_test_baseline(**_valid_build_kwargs(input_sources=bad_sources))


# ── 正常系: input_sources が空リスト（記録対象ソースなし）でも受理される ──
def test_build_test_baseline_accepts_empty_input_sources():
    result = es.build_test_baseline(**_valid_build_kwargs(input_sources=[]))
    assert result["input_sources"] == []
    assert result["models"] == {}
    assert result["prompt_versions"] == {}


# ── 異常系: 時刻形式の不正を拒否する ──
@pytest.mark.parametrize("bad_time", [
    "2026-07-25 10:00:00+09:00",     # Tが無い
    "2026-07-25T10:00:00",           # タイムゾーンが無い
    "2026-07-25T10:00:00+00:00",     # JSTではない
    "not-a-timestamp",
    12345,
    None,
])
def test_build_test_baseline_rejects_invalid_started_at_format(bad_time):
    with pytest.raises(ValueError):
        es.build_test_baseline(**_valid_build_kwargs(analysis_started_at=bad_time))


@pytest.mark.parametrize("bad_time", [
    "2026-07-25 10:00:00+09:00",
    "2026-07-25T10:00:00",
    "2026-07-25T10:00:00+00:00",
    "not-a-timestamp",
    12345,
    None,
])
def test_build_test_baseline_rejects_invalid_completed_at_format(bad_time):
    with pytest.raises(ValueError):
        es.build_test_baseline(**_valid_build_kwargs(analysis_completed_at=bad_time))


# ── 異常系: analysis_completed_at が analysis_started_at より前の場合を拒否する ──
def test_build_test_baseline_rejects_completed_before_started():
    with pytest.raises(ValueError):
        es.build_test_baseline(**_valid_build_kwargs(
            analysis_started_at="2026-07-25T10:00:30+09:00",
            analysis_completed_at="2026-07-25T10:00:00+09:00",
        ))


def test_build_test_baseline_accepts_completed_equal_to_started():
    result = es.build_test_baseline(**_valid_build_kwargs(
        analysis_started_at="2026-07-25T10:00:00+09:00",
        analysis_completed_at="2026-07-25T10:00:00+09:00",
    ))
    assert result["analysis_started_at"] == result["analysis_completed_at"]

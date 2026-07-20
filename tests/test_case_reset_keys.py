# -*- coding: utf-8 -*-
"""
A3-0a: 案件リセット漏れ修正の検証。

app.py はモジュールレベルで st.set_page_config() やログイン画面表示を行うため
そのまま import/実行することができない。そのため ast でソースを静的解析し、
1) CASE_RESET_KEYS 定数が期待通りの内容で定義されていること
2) サイドバー「🔄 最初からやり直す」と STEP5「🆕 新しい案件を作成」の
   両方が、個別のキー列挙ではなく共通定数 CASE_RESET_KEYS を参照していること
を検証する。
"""
import ast
from pathlib import Path

APP_PY = Path(__file__).resolve().parent.parent / "app.py"
SOURCE = APP_PY.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)

# 会社設定など「案件をまたいで保持すべきキー」＝ CASE_RESET_KEYS に含めてはいけないもの
COMPANY_LEVEL_KEYS = {
    "logged_in", "company_id", "company_name",
    "estimation_rules", "unit_prices", "theme",
    "show_price_settings", "show_account_settings",
}

# 修正前は2箇所の reset 処理から漏れていた既知の重要キー
EXPECTED_NEW_KEYS = {
    "estimation_sheet_data", "extra_options", "floor_plan_bytes",
    "drawing_annotated_img", "drawing_annotations", "drawing_page1_raw",
    "canvas_states", "drawing_page_selector", "drawing_upload_step3",
    "_voice_gpt_raw", "_3d_gpt_raw", "_3d_trace_png",
}

# A3-0b-1で新規追加されたキー（STEP3追加図面のsession_stateコピー）
EXPECTED_A3_0B_1_KEYS = {
    "step3_drawing_files",
}


def _get_case_reset_keys():
    """モジュールレベルの `CASE_RESET_KEYS = [...]` 代入から文字列リストを抽出する"""
    for node in ast.walk(TREE):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == "CASE_RESET_KEYS":
                assert isinstance(node.value, ast.List), \
                    "CASE_RESET_KEYS はリストリテラルで定義されている必要があります"
                keys = []
                for elt in node.value.elts:
                    assert isinstance(elt, ast.Constant) and isinstance(elt.value, str), \
                        "CASE_RESET_KEYS の要素はすべて文字列リテラルである必要があります"
                    keys.append(elt.value)
                return keys
    raise AssertionError("app.py に CASE_RESET_KEYS の定義が見つかりません")


def _for_loops_iterating_over(name: str):
    """`for k in <name>:` の形のループを全て返す（ボタン処理ブロック特定に使用）"""
    result = []
    for node in ast.walk(TREE):
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Name) and node.iter.id == name:
            result.append(node)
    return result


def _button_blocks():
    """`if st.button("ラベル", ...):` の If ノードを {ラベル: Ifノード} で返す"""
    blocks = {}
    for node in ast.walk(TREE):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (isinstance(test, ast.Call) and isinstance(test.func, ast.Attribute)
                and test.func.attr == "button"):
            continue
        if not test.args:
            continue
        first_arg = test.args[0]
        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
            blocks[first_arg.value] = node
    return blocks


def test_case_reset_keys_defined_with_28_keys():
    """CASE_RESET_KEYS が定義されており、重複なく28キーであること
    （27キー＝A3-0a時点 + step3_drawing_files＝A3-0b-1で追加）"""
    keys = _get_case_reset_keys()
    assert len(keys) == 28, f"CASE_RESET_KEYS は28キーである想定ですが {len(keys)} 件でした: {keys}"
    assert len(set(keys)) == len(keys), "CASE_RESET_KEYS に重複キーがあります"


def test_case_reset_keys_excludes_company_level_settings():
    """会社設定（ログイン状態・単価設定・テーマ等）はリセット対象に含めない"""
    keys = set(_get_case_reset_keys())
    leaked = keys & COMPANY_LEVEL_KEYS
    assert not leaked, f"会社設定キーが誤ってリセット対象に含まれています: {leaked}"


def test_case_reset_keys_includes_previously_missing_keys():
    """コードベース精査で見つかった、従来の2箇所から漏れていたキーが含まれていること
    （canvas_states 漏れ＝既存バグの解消を含む）"""
    keys = set(_get_case_reset_keys())
    missing = EXPECTED_NEW_KEYS - keys
    assert not missing, f"CASE_RESET_KEYS に含まれるべきキーが不足しています: {missing}"


def test_case_reset_keys_includes_a3_0b_1_step3_drawing_files():
    """A3-0b-1で追加したSTEP3追加図面のsession_stateキーがリセット対象に含まれること
    （current_case_idはA3-0b-1では追加しない）"""
    keys = set(_get_case_reset_keys())
    missing = EXPECTED_A3_0B_1_KEYS - keys
    assert not missing, f"CASE_RESET_KEYS に含まれるべきキーが不足しています: {missing}"
    assert "current_case_id" not in keys, \
        "current_case_id はA3-0b-3で追加する想定であり、A3-0b-1時点では含まれてはいけません"


def test_sidebar_reset_button_uses_shared_constant():
    """サイドバー「🔄 最初からやり直す」が個別列挙ではなく CASE_RESET_KEYS を参照していること"""
    blocks = _button_blocks()
    assert "🔄 最初からやり直す" in blocks, "サイドバーの「最初からやり直す」ボタンが見つかりません"
    loops = [
        n for n in ast.walk(blocks["🔄 最初からやり直す"])
        if isinstance(n, ast.For) and isinstance(n.iter, ast.Name) and n.iter.id == "CASE_RESET_KEYS"
    ]
    assert loops, "「最初からやり直す」ブロック内に `for k in CASE_RESET_KEYS:` が見つかりません"


def test_step5_new_case_button_uses_shared_constant():
    """STEP5「🆕 新しい案件を作成」が個別列挙ではなく CASE_RESET_KEYS を参照していること"""
    blocks = _button_blocks()
    assert "🆕 新しい案件を作成" in blocks, "STEP5の「新しい案件を作成」ボタンが見つかりません"
    loops = [
        n for n in ast.walk(blocks["🆕 新しい案件を作成"])
        if isinstance(n, ast.For) and isinstance(n.iter, ast.Name) and n.iter.id == "CASE_RESET_KEYS"
    ]
    assert loops, "「新しい案件を作成」ブロック内に `for k in CASE_RESET_KEYS:` が見つかりません"


def test_save_estimate_button_passes_drawing_materials_kwarg():
    """STEP5「💾 この見積りを案件履歴に保存」が save_estimate() へ
    drawing_materials キーワード引数を渡していること（A3-0b-1）"""
    blocks = _button_blocks()
    label = "💾 この見積りを案件履歴に保存"
    assert label in blocks, "STEP5の保存ボタンが見つかりません"

    calls = [
        n for n in ast.walk(blocks[label])
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id in ("_save_est", "save_estimate")
    ]
    assert calls, "保存ボタンブロック内に save_estimate() 呼び出しが見つかりません"
    kwarg_names = {kw.arg for call in calls for kw in call.keywords}
    assert "drawing_materials" in kwarg_names, \
        "save_estimate() 呼び出しに drawing_materials キーワード引数が渡されていません"


def test_save_estimate_button_passes_canvas_states_kwarg():
    """STEP5「💾 この見積りを案件履歴に保存」が save_estimate() へ
    canvas_states キーワード引数を渡していること（A3-0b-2）"""
    blocks = _button_blocks()
    label = "💾 この見積りを案件履歴に保存"
    assert label in blocks, "STEP5の保存ボタンが見つかりません"

    calls = [
        n for n in ast.walk(blocks[label])
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id in ("_save_est", "save_estimate")
    ]
    assert calls, "保存ボタンブロック内に save_estimate() 呼び出しが見つかりません"
    kwarg_names = {kw.arg for call in calls for kw in call.keywords}
    assert "canvas_states" in kwarg_names, \
        "save_estimate() 呼び出しに canvas_states キーワード引数が渡されていません"

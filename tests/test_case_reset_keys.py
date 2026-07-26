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

# test_baseline機能で新規追加されたキー
EXPECTED_TEST_BASELINE_KEYS = {
    "test_baseline",
}

# test_baseline構築失敗時の警告表示フラグ（バグ修正ラウンドで追加）
EXPECTED_TEST_BASELINE_UNAVAILABLE_KEYS = {
    "test_baseline_unavailable",
}

# test_baseline: 実際に解析が成功した場合にのみ successful_input_sources へ
# 追加されるべき文字列（順不同・過不足なくこの集合と一致することを確認する）
EXPECTED_SUCCESSFUL_INPUT_SOURCE_VALUES = {"voice", "drawing_pdf", "floor_plan", "photos"}


_PARENT_MAP = {}
for _node in ast.walk(TREE):
    for _child in ast.iter_child_nodes(_node):
        _PARENT_MAP[_child] = _node


def _ancestors(node):
    """node から見て、ast上の全ての親ノードを列挙する（node自身は含まない）。"""
    current = node
    while current in _PARENT_MAP:
        current = _PARENT_MAP[current]
        yield current


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


def _get_defaults_dict():
    """モジュールレベルの `DEFAULTS = {...}` 代入から {キー: 値ASTノード} を抽出する"""
    for node in ast.walk(TREE):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == "DEFAULTS":
                assert isinstance(node.value, ast.Dict), \
                    "DEFAULTS は辞書リテラルで定義されている必要があります"
                result = {}
                for k_node, v_node in zip(node.value.keys, node.value.values):
                    assert isinstance(k_node, ast.Constant) and isinstance(k_node.value, str), \
                        "DEFAULTS のキーはすべて文字列リテラルである必要があります"
                    result[k_node.value] = v_node
                return result
    raise AssertionError("app.py に DEFAULTS の定義が見つかりません")


def _is_session_state_get_call(node, key: str) -> bool:
    """node が `st.session_state.get("<key>")` 形式の呼び出しであるかを判定する"""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "session_state"
        and bool(node.args)
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == key
    )


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


def test_case_reset_keys_defined_with_30_keys():
    """CASE_RESET_KEYS が定義されており、重複なく30キーであること
    （28キー＝A3-0b-1時点 + test_baseline・test_baseline_unavailable
    ＝test_baseline機能とその後のバグ修正ラウンドで追加）"""
    keys = _get_case_reset_keys()
    assert len(keys) == 30, f"CASE_RESET_KEYS は30キーである想定ですが {len(keys)} 件でした: {keys}"
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


# ─────────────────────────────────────────────────────────────
# test_baseline: app.py配線の静的構造テスト
# ─────────────────────────────────────────────────────────────

def test_case_reset_keys_includes_test_baseline():
    """test_baseline機能で追加したキーがCASE_RESET_KEYSに含まれること
    （＝新規案件開始時の未設定初期化・最初からやり直す時の削除の両方を、
    既存の仕組み1箇所への追加だけで満たす設計になっていること）"""
    keys = set(_get_case_reset_keys())
    missing = EXPECTED_TEST_BASELINE_KEYS - keys
    assert not missing, f"CASE_RESET_KEYS に含まれるべきキーが不足しています: {missing}"


def test_case_reset_keys_includes_test_baseline_unavailable():
    """test_baseline構築失敗時の警告表示フラグ（test_baseline_unavailable）が
    CASE_RESET_KEYSに含まれること（test_baseline本体と同じライフサイクルで
    リセットされる必要があるため）"""
    keys = set(_get_case_reset_keys())
    missing = EXPECTED_TEST_BASELINE_UNAVAILABLE_KEYS - keys
    assert not missing, f"CASE_RESET_KEYS に含まれるべきキーが不足しています: {missing}"


def test_defaults_includes_test_baseline_unavailable_defaulting_to_false():
    """DEFAULTS に test_baseline_unavailable が存在し、初期値が False であること。"""
    defaults = _get_defaults_dict()
    assert "test_baseline_unavailable" in defaults, \
        "DEFAULTS に test_baseline_unavailable が定義されていません"
    node = defaults["test_baseline_unavailable"]
    assert isinstance(node, ast.Constant) and node.value is False, \
        "DEFAULTS['test_baseline_unavailable'] の初期値は False である必要があります"


def test_load_case_restores_test_baseline_from_saved_json():
    """既存案件読込処理内に、保存JSONの test_baseline を
    session_state へ復元する `if _ed.get("test_baseline"): ...` 相当の分岐があること。
    旧案件（test_baselineキーが無い）を読み込んだ場合はこの分岐に入らず、
    CASE_RESET_KEYSクリア直後のNoneのまま（＝新規に生成しない）ことは、
    should_create_test_baseline() 側の current_case_id 判定（後続テスト）で保証される。"""
    found = False
    for node in ast.walk(TREE):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        # `_ed.get("test_baseline")` 形式の呼び出しであることを確認
        if (
            isinstance(test, ast.Call)
            and isinstance(test.func, ast.Attribute)
            and test.func.attr == "get"
            and isinstance(test.func.value, ast.Name)
            and test.func.value.id == "_ed"
            and test.args
            and isinstance(test.args[0], ast.Constant)
            and test.args[0].value == "test_baseline"
        ):
            found = True
            break
    assert found, (
        "案件読込処理内に `if _ed.get(\"test_baseline\"):` 相当の復元分岐が見つかりません"
    )


def test_auto_calc_block_calls_should_create_test_baseline_with_expected_conditions():
    """STEP2自動積算ブロック内で should_create_test_baseline() が呼ばれ、
    current_case_id・test_baseline・ai_analysis_used のキーワード引数が
    それぞれ session_state の対応する値を参照していること。"""
    blocks = _button_blocks()
    label = "▶️ 自動積算を実行する"
    assert label in blocks, "STEP2「自動積算を実行する」ボタンが見つかりません"

    calls = [
        n for n in ast.walk(blocks[label])
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "should_create_test_baseline"
    ]
    assert calls, "自動積算ボタンブロック内に should_create_test_baseline() 呼び出しが見つかりません"
    call = calls[0]
    kwargs = {kw.arg: kw.value for kw in call.keywords}

    assert "current_case_id" in kwargs, "current_case_id キーワード引数がありません"
    cc = kwargs["current_case_id"]
    assert (
        isinstance(cc, ast.Call)
        and isinstance(cc.func, ast.Attribute)
        and cc.func.attr == "get"
        and cc.args
        and isinstance(cc.args[0], ast.Constant)
        and cc.args[0].value == "current_case_id"
    ), "current_case_id が st.session_state.get(\"current_case_id\") を参照していません"

    assert "test_baseline" in kwargs, "test_baseline キーワード引数がありません"
    tb = kwargs["test_baseline"]
    assert (
        isinstance(tb, ast.Call)
        and isinstance(tb.func, ast.Attribute)
        and tb.func.attr == "get"
        and tb.args
        and isinstance(tb.args[0], ast.Constant)
        and tb.args[0].value == "test_baseline"
    ), "test_baseline が st.session_state.get(\"test_baseline\") を参照していません"

    assert "ai_analysis_used" in kwargs, "ai_analysis_used キーワード引数がありません"


def test_ai_analysis_used_is_derived_from_successful_input_sources():
    """ai_analysis_used が bool(successful_input_sources) から導出されていること
    （常にTrue固定で渡す設計は採用しない、という確定要件の構造チェック）。"""
    found = False
    for node in ast.walk(TREE):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if (
                isinstance(target, ast.Name)
                and target.id == "_ai_analysis_used"
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "bool"
                and node.value.args
                and isinstance(node.value.args[0], ast.Name)
                and node.value.args[0].id == "successful_input_sources"
            ):
                found = True
                break
    assert found, (
        "`_ai_analysis_used = bool(successful_input_sources)` 相当の代入が見つかりません"
        "（ai_analysis_used を True 固定で渡す設計は禁止）"
    )


def test_test_baseline_snapshot_is_built_after_auto_done_set_true():
    """test_baseline構築（should_create_test_baseline呼び出し）が、
    st.session_state.auto_done = True の代入より後に配置されていること
    （＝全解析・初期quantities生成の正常終了後にだけ配置されている、という要件）。"""
    blocks = _button_blocks()
    label = "▶️ 自動積算を実行する"
    block = blocks[label]

    auto_done_lines = [
        n.lineno for n in ast.walk(block)
        if isinstance(n, ast.Assign) and len(n.targets) == 1
        and isinstance(n.targets[0], ast.Attribute) and n.targets[0].attr == "auto_done"
    ]
    assert auto_done_lines, "st.session_state.auto_done = True の代入が見つかりません"

    sct_calls = [
        n.lineno for n in ast.walk(block)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "should_create_test_baseline"
    ]
    assert sct_calls, "should_create_test_baseline() 呼び出しが見つかりません"

    assert min(sct_calls) > max(auto_done_lines), (
        "should_create_test_baseline() の呼び出しが auto_done=True の代入より前に"
        "配置されています（全解析・初期quantities生成の正常終了後にのみ配置する必要があります）"
    )


def test_no_direct_quantities_reference_in_test_baseline_construction():
    """`{"ai_initial_quantities": quantities}` のような、st.session_state.test_baseline
    への直接dict literal代入（quantitiesへの生参照をそのまま保持してしまい、
    後続の再計算等でtest_baselineが書き換わってしまうバグパターン）が
    app.py中に存在しないこと。test_baselineはbuild_test_baseline()呼び出し経由での
    み構築される必要がある（バグ修正ラウンドで追加した回帰防止テスト）。"""
    for node in ast.walk(TREE):
        if isinstance(node, ast.Dict):
            for key_node, value_node in zip(node.keys, node.values):
                if (
                    key_node is not None
                    and isinstance(key_node, ast.Constant)
                    and key_node.value == "ai_initial_quantities"
                    and isinstance(value_node, ast.Name)
                    and value_node.id == "quantities"
                ):
                    raise AssertionError(
                        'test_baselineへの直接dict literal代入'
                        '（"ai_initial_quantities": quantities）が見つかりました。'
                        "build_test_baseline()経由で構築する必要があります。"
                    )


def test_auto_calc_block_calls_build_test_baseline_with_expected_kwargs():
    """STEP2自動積算ブロック内で build_test_baseline() が呼ばれ、
    ai_initial_quantities に quantities（そのままの名前参照）が渡されていること。
    実際の独立コピーは build_test_baseline() 内部（core/estimate_storage.py）で
    行われるため、app.py側はquantitiesをそのまま渡してよい。"""
    blocks = _button_blocks()
    label = "▶️ 自動積算を実行する"
    calls = [
        n for n in ast.walk(blocks[label])
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "build_test_baseline"
    ]
    assert calls, "自動積算ボタンブロック内に build_test_baseline() 呼び出しが見つかりません"
    call = calls[0]
    kwarg_names = {kw.arg for kw in call.keywords}
    expected_kwargs = {
        "ai_initial_quantities", "input_sources", "app_commit",
        "analysis_started_at", "analysis_completed_at",
    }
    assert expected_kwargs <= kwarg_names, (
        f"build_test_baseline() の呼び出しに必要なキーワード引数が不足しています: "
        f"{expected_kwargs - kwarg_names}"
    )

    ai_kwarg = next(kw.value for kw in call.keywords if kw.arg == "ai_initial_quantities")
    assert isinstance(ai_kwarg, ast.Name) and ai_kwarg.id == "quantities", (
        "build_test_baseline() の ai_initial_quantities 引数は quantities を"
        "参照している必要があります"
    )


def test_build_test_baseline_result_assigned_directly_to_session_state_test_baseline():
    """build_test_baseline() の戻り値が、中間変数を経由せず直接
    st.session_state.test_baseline へ代入されていること
    （session_state上のtest_baselineと保存JSONの構造を同一に保つための設計要件）。"""
    blocks = _button_blocks()
    label = "▶️ 自動積算を実行する"
    calls = [
        n for n in ast.walk(blocks[label])
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "build_test_baseline"
    ]
    assert calls, "build_test_baseline() 呼び出しが見つかりません"
    call = calls[0]
    parent = _PARENT_MAP.get(call)
    assert isinstance(parent, ast.Assign) and len(parent.targets) == 1, (
        "build_test_baseline() の戻り値は単一代入文の右辺である必要があります"
    )
    target = parent.targets[0]
    assert (
        isinstance(target, ast.Attribute)
        and target.attr == "test_baseline"
        and isinstance(target.value, ast.Attribute)
        and target.value.attr == "session_state"
    ), (
        "build_test_baseline() の戻り値は st.session_state.test_baseline へ"
        "直接代入されている必要があります"
    )


def test_test_baseline_build_failure_sets_unavailable_flag():
    """build_test_baseline() 呼び出しを囲むexcept節が、
    st.session_state.test_baseline_unavailable = True を設定していること
    （構築失敗時にUI側で警告表示するためのフラグ）。"""
    blocks = _button_blocks()
    label = "▶️ 自動積算を実行する"
    block = blocks[label]

    build_calls = [
        n for n in ast.walk(block)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "build_test_baseline"
    ]
    assert build_calls, "build_test_baseline() 呼び出しが見つかりません"

    # build_test_baseline() 呼び出しを内包する try/except の except節を特定する
    enclosing_try = None
    for ancestor in _ancestors(build_calls[0]):
        if isinstance(ancestor, ast.Try):
            enclosing_try = ancestor
            break
    assert enclosing_try is not None, (
        "build_test_baseline() 呼び出しが try 節の内側にありません"
    )

    found = False
    for handler in enclosing_try.handlers:
        for n in ast.walk(handler):
            if (
                isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Attribute)
                and n.targets[0].attr == "test_baseline_unavailable"
                and isinstance(n.value, ast.Constant) and n.value.value is True
            ):
                found = True
    assert found, (
        "build_test_baseline() を囲む except 節に "
        "st.session_state.test_baseline_unavailable = True の設定が見つかりません"
    )


def test_warning_shown_when_test_baseline_unavailable():
    """test_baseline_unavailable フラグを条件とした st.warning(...) 表示が、
    app.py中に少なくとも1箇所存在すること（通常操作を止めない非ブロッキング警告）。"""
    found = False
    for node in ast.walk(TREE):
        if isinstance(node, ast.If) and _is_session_state_get_call(node.test, "test_baseline_unavailable"):
            has_warning = any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "warning"
                for n in ast.walk(node)
            )
            if has_warning:
                found = True
                break
    assert found, (
        "`if st.session_state.get(\"test_baseline_unavailable\"): st.warning(...)` "
        "相当の警告表示が見つかりません"
    )


def test_successful_input_sources_only_appended_with_expected_values():
    """successful_input_sources.append(...) の呼び出しが、
    {"voice","drawing_pdf","floor_plan","photos"} の4値のみで構成されており、
    かつ except 節の内側（＝解析失敗経路）には1件も存在しないこと。"""
    append_calls = [
        n for n in ast.walk(TREE)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "append"
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "successful_input_sources"
    ]
    assert append_calls, "successful_input_sources.append(...) 呼び出しが見つかりません"

    values = set()
    for call in append_calls:
        assert call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str), \
            "successful_input_sources.append() の引数は文字列リテラルである必要があります"
        values.add(call.args[0].value)

        # except節（解析失敗経路）の内側に無いことを確認する
        for ancestor in _ancestors(call):
            assert not isinstance(ancestor, ast.ExceptHandler), (
                f"successful_input_sources.append({call.args[0].value!r}) が "
                "except節の内側（解析失敗経路）に配置されています"
            )

    assert values == EXPECTED_SUCCESSFUL_INPUT_SOURCE_VALUES, (
        f"successful_input_sources.append() の値が想定と一致しません: {values}"
    )


def test_manual_paths_do_not_reference_test_baseline_machinery():
    """AIを使わない2つの手動経路のボタン処理内に、
    should_create_test_baseline() 呼び出し・successful_input_sources参照が
    存在しないこと（＝手動経路ではtest_baselineを作らない、という確定要件）。"""
    blocks = _button_blocks()
    manual_labels = ["✏️ 数量入力フォームへ →", "✏️ 手動入力で進める（AIを使わない）"]
    for label in manual_labels:
        assert label in blocks, f"手動経路のボタン「{label}」が見つかりません"
        block = blocks[label]

        sct_calls = [
            n for n in ast.walk(block)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "should_create_test_baseline"
        ]
        assert not sct_calls, f"手動経路「{label}」内に should_create_test_baseline() 呼び出しがあります"

        sis_refs = [
            n for n in ast.walk(block)
            if isinstance(n, ast.Name) and n.id == "successful_input_sources"
        ]
        assert not sis_refs, f"手動経路「{label}」内に successful_input_sources への参照があります"


def test_update_estimate_call_does_not_pass_test_baseline_kwarg():
    """STEP5「💾 この見積りを案件履歴に保存」内の update_estimate() 呼び出しに
    test_baseline キーワード引数が渡されていないこと
    （update_estimate()はtest_baseline引数を持たない設計のため、
    誤って渡そうとするコードが将来追加されていないかの回帰防止）。"""
    blocks = _button_blocks()
    label = "💾 この見積りを案件履歴に保存"
    calls = [
        n for n in ast.walk(blocks[label])
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id in ("_update_est", "update_estimate")
    ]
    assert calls, "保存ボタンブロック内に update_estimate() 呼び出しが見つかりません"
    kwarg_names = {kw.arg for call in calls for kw in call.keywords}
    assert "test_baseline" not in kwarg_names, (
        "update_estimate() 呼び出しに test_baseline キーワード引数が渡されています"
        "（update_estimate()はtest_baselineを引数に持たない設計です）"
    )


def test_save_estimate_button_passes_test_baseline_kwarg():
    """STEP5「💾 この見積りを案件履歴に保存」内の save_estimate()（新規保存側）
    呼び出しにのみ test_baseline キーワード引数が渡されていること。"""
    blocks = _button_blocks()
    label = "💾 この見積りを案件履歴に保存"
    calls = [
        n for n in ast.walk(blocks[label])
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id in ("_save_est", "save_estimate")
    ]
    assert calls, "保存ボタンブロック内に save_estimate() 呼び出しが見つかりません"
    kwarg_names = {kw.arg for call in calls for kw in call.keywords}
    assert "test_baseline" in kwarg_names, \
        "save_estimate() 呼び出しに test_baseline キーワード引数が渡されていません"

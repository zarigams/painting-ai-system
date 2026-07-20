"""
塗装会社専用AI積算・見積りシステム
4ステップフロー: 案件情報 → AI解析 → 数量確認 → 見積書出力
"""

import sys
import tempfile
from datetime import datetime
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from core.auth import verify_password, show_login_page
from core.quantity_calculator import calculate_from_quantities
from core.template_filler import fill_template, fill_estimation_sheet
from core.logger import (
    log_ui, log_auth, log_file, log_error, log_admin, log_measure,
    log_geo_calc, get_session_logs, export_session_logs_json,
    list_log_dates, get_file_logs,
)

# ─────────────────────────────────────────────────────────────
# ページ設定
# ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AI塗装積算システム",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ─────────────────────────────────────────────────────────────
# テーマ定義
# ─────────────────────────────────────────────────────────────
_THEMES = {
    "スタンダード": """<style>
/* プライマリボタン（見積もり作成・ログイン等）*/
[data-testid="baseButton-primary"],
button[kind="primary"],
.stButton > button[kind="primary"],
.stForm button[type="submit"] {
  background:#3d6b8f !important;color:#fff !important;
  border:none !important;border-radius:6px !important;font-weight:600 !important;
}
[data-testid="baseButton-primary"]:hover,
button[kind="primary"]:hover {background:#2f5470 !important}
/* セカンダリボタン */
[data-testid="baseButton-secondary"],
button[kind="secondary"] {
  background:#fff !important;color:#3d6b8f !important;
  border:1.5px solid #3d6b8f !important;border-radius:6px !important;
}
</style>""",

    "ダーク": """<style>
[data-testid="stAppViewContainer"]{background:#0d1117}
[data-testid="stAppViewContainer"] .stMarkdown,[data-testid="stAppViewContainer"] p{color:#e6edf3}
[data-testid="stSidebar"]{background:#161b22;border-right:1px solid #30363d}
[data-testid="stSidebar"] *{color:#c9d1d9 !important}
[data-testid="stTextInput"] input,[data-testid="stTextArea"] textarea{
  background:#21262d !important;color:#e6edf3 !important;
  border:1px solid #30363d !important;border-radius:6px !important}
[data-testid="stNumberInput"] input{
  background:#21262d !important;color:#e6edf3 !important;border:1px solid #30363d !important}
h1{color:#58a6ff !important;font-weight:700 !important}
h2{color:#79c0ff !important;font-weight:600 !important}
h3{color:#cae8ff !important}
[data-testid="baseButton-primary"],
button[kind="primary"],
.stButton > button[kind="primary"],
.stForm button[type="submit"]{
  background:#1f6feb !important;color:#fff !important;
  border:none !important;border-radius:6px !important;font-weight:600 !important}
[data-testid="baseButton-primary"]:hover,
button[kind="primary"]:hover{background:#388bfd !important}
[data-testid="baseButton-secondary"],
button[kind="secondary"]{
  background:#21262d !important;color:#c9d1d9 !important;
  border:1px solid #30363d !important;border-radius:6px !important}
[data-testid="stMetric"]{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px 16px}
[data-testid="stMetricValue"]{color:#58a6ff !important;font-size:1.6rem !important}
[data-testid="stDataFrame"] th{background:#21262d !important;color:#58a6ff !important}
[data-testid="stDataFrame"] td{background:#0d1117 !important;color:#e6edf3 !important}
[data-testid="stExpander"]{background:#161b22 !important;border:1px solid #30363d !important;border-radius:8px !important}
</style>""",

    "サイバーパンク": """<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Share+Tech+Mono&family=Rajdhani:wght@400;500;600;700&display=swap');

/* ── ベース ── */
[data-testid="stAppViewContainer"]{
  background:#00080f;
  font-family:'Rajdhani',sans-serif !important;
  background-image:
    linear-gradient(rgba(0,255,255,0.04) 1px,transparent 1px),
    linear-gradient(90deg,rgba(0,255,255,0.04) 1px,transparent 1px);
  background-size:40px 40px;
}

/* ── 本文テキスト（spanを外してh1サイズを守る）── */
[data-testid="stAppViewContainer"] p,
[data-testid="stAppViewContainer"] .stMarkdown,
[data-testid="stAppViewContainer"] label,
[data-testid="stAppViewContainer"] .stSelectbox div,
[data-testid="stAppViewContainer"] .stRadio div{
  color:#7fffff;
  font-family:'Rajdhani',sans-serif !important;
  font-size:1.05rem;
  letter-spacing:0.5px;
}

/* ── サイドバー（* を使わず具体的に指定）── */
[data-testid="stSidebar"]{
  background:linear-gradient(180deg,#00050f 0%,#00080f 100%);
  border-right:1px solid #00ffff;
  box-shadow:4px 0 20px rgba(0,255,255,0.15);
  font-family:'Rajdhani',sans-serif !important;
}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] div,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] a { color:#00ffff !important; }

/* ── 入力フィールド ── */
[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea{
  background:#00050f !important;color:#00ffff !important;
  border:1px solid #00cccc !important;border-radius:2px !important;
  font-family:'Share Tech Mono',monospace !important;
  font-size:1rem !important;letter-spacing:1px !important;
  box-shadow:0 0 8px rgba(0,255,255,0.2) inset !important;
}
[data-testid="stNumberInput"] input{
  background:#00050f !important;color:#00ffff !important;
  border:1px solid #00cccc !important;
}

/* ── 見出し（font-sizeはStreamlitデフォルト維持）── */
h1{
  font-family:'Orbitron',monospace !important;
  color:#00ffff !important;font-weight:900 !important;
  text-shadow:0 0 10px #00ffff,0 0 30px rgba(0,255,255,0.4) !important;
  letter-spacing:2px;
  font-size:2.5rem !important;
}
h2{
  font-family:'Orbitron',monospace !important;
  color:#00e5ff !important;font-weight:700 !important;
  text-shadow:0 0 8px rgba(0,229,255,0.5) !important;
  font-size:1.8rem !important;
}
h3{
  font-family:'Orbitron',monospace !important;
  color:#7fffff !important;
  text-shadow:0 0 6px rgba(127,255,255,0.4) !important;
  font-size:1.3rem !important;
}

/* ── ボタン ── */
[data-testid="baseButton-primary"],
button[kind="primary"],
.stButton > button[kind="primary"],
.stForm button[type="submit"]{
  background:linear-gradient(135deg,#006666,#00aaaa) !important;
  color:#00ffff !important;border:1px solid #00ffff !important;
  border-radius:2px !important;font-weight:700 !important;
  font-family:'Orbitron',monospace !important;letter-spacing:1px;
  box-shadow:0 0 12px rgba(0,255,255,0.4) !important;
  text-transform:uppercase;
}
[data-testid="baseButton-primary"]:hover,
button[kind="primary"]:hover{
  background:linear-gradient(135deg,#008888,#00cccc) !important;
  box-shadow:0 0 22px rgba(0,255,255,0.7) !important;
}
[data-testid="baseButton-secondary"],
button[kind="secondary"]{
  background:transparent !important;color:#00ffff !important;
  border:1px solid #00cccc !important;border-radius:2px !important;
  font-family:'Share Tech Mono',monospace !important;
  box-shadow:0 0 6px rgba(0,255,255,0.2) !important;
}
[data-testid="stSidebar"] [data-testid="baseButton-secondary"]{
  background:transparent !important;color:#00ffff !important;
  border:1px solid rgba(0,255,255,0.4) !important;
}

/* ── メトリクス ── */
[data-testid="stMetric"]{
  background:rgba(0,8,15,0.8);
  border:1px solid #00ffff;border-radius:2px;padding:12px 16px;
  box-shadow:0 0 12px rgba(0,255,255,0.12);
}
[data-testid="stMetricValue"]{
  color:#00ffff !important;font-size:1.6rem !important;
  font-family:'Orbitron',monospace !important;
  text-shadow:0 0 10px rgba(0,255,255,0.6) !important;
}
[data-testid="stMetricLabel"]{
  font-family:'Orbitron',monospace !important;
  font-size:0.7rem !important;letter-spacing:2px;color:#00cccc !important;
}

/* ── テーブル ── */
[data-testid="stDataFrame"] th{
  background:#001a1a !important;color:#00ffff !important;
  font-family:'Orbitron',monospace !important;font-size:0.75rem !important;
}
[data-testid="stDataFrame"] td{
  background:#00080f !important;color:#7fffff !important;
  font-family:'Share Tech Mono',monospace !important;font-size:0.85rem !important;
}

/* ── エクスパンダー・アラート ── */
[data-testid="stExpander"]{
  background:rgba(0,8,15,0.6) !important;
  border:1px solid rgba(0,255,255,0.35) !important;border-radius:2px !important;
}
[data-testid="stAlert"]{
  background:rgba(0,255,255,0.04) !important;
  border:1px solid rgba(0,255,255,0.3) !important;border-radius:2px !important;
}
</style>""",
}

def _apply_theme(theme_name: str):
    css = _THEMES.get(theme_name, "")
    if css:
        st.markdown(css, unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────
# セッション状態の初期化
# ─────────────────────────────────────────────────────────────
DEFAULTS = {
    "logged_in":         False,
    "company_id":        None,
    "company_name":      None,
    "step":              1,
    "project":           {},
    "drawing_data":      {},
    "image_data":        {},
    "quantities":        {},
    "estimation":        {},
    "voice_memo":        "",
    "voice_extras":      {},
    "voice_raw":         {},
    "auto_done":         False,
    "correction_history": [],
    "last_correction":   {},
    "estimation_rules":  "",
    "extra_options":     {},
    "unit_prices":           {},
    "show_price_settings":   False,
        "show_account_settings": False,
        "_voice_gpt_raw": "",
        "_3d_gpt_raw": "",
        "_3d_trace_png": None,
    "theme":                 "スタンダード",
    "step3_drawing_files":   [],
}
for _k, _v in DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ─────────────────────────────────────────────────────────────
# 案件リセット対象キー（「最初からやり直す」「新しい案件を作成」で共通利用）
# 会社設定（estimation_rules / unit_prices / theme 等）は含まない＝案件データのみ
# ─────────────────────────────────────────────────────────────
CASE_RESET_KEYS = [
    # 既存（従来の2箇所で個別に列挙されていたキー）
    "step", "project", "drawing_data", "image_data",
    "quantities", "estimation", "voice_memo",
    "voice_extras", "voice_raw", "auto_done",
    "correction_history", "last_correction",
    "correction_input", "pdf_bytes", "photo_bytes_list",
    # 追加（コードベース精査で見つかった漏れ）
    "estimation_sheet_data", "extra_options", "floor_plan_bytes",
    "drawing_annotated_img", "drawing_annotations", "drawing_page1_raw",
    "canvas_states", "drawing_page_selector", "drawing_upload_step3",
    "_voice_gpt_raw", "_3d_gpt_raw", "_3d_trace_png",
    # A3-0b-1で追加（STEP3追加図面のsession_stateコピー。current_case_idは未導入）
    "step3_drawing_files",
]

# ─────────────────────────────────────────────────────────────
# ログイン
# ─────────────────────────────────────────────────────────────
# テーマをログイン画面にも適用
_apply_theme(st.session_state.get("theme", "スタンダード"))

if not st.session_state.logged_in:
    show_login_page()
    st.stop()

# ─────────────────────────────────────────────────────────────
# サイドバー
# ─────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"### 🏢 {st.session_state.company_name or ''}様")
    st.markdown("---")
    step_labels = ["① 現場メモ入力", "② AI自動積算", "③ 図面手動積算", "④ 数量確認", "⑤ 見積書出力"]
    cur = st.session_state.step
    for i, label in enumerate(step_labels, 1):
        if i < cur:
            st.markdown(f"✅ {label}")
        elif i == cur:
            st.markdown(f"▶️ **{label}**")
        else:
            st.markdown(f"⬜ {label}")
    st.markdown("---")
    if st.button("🔄 最初からやり直す", use_container_width=True):
        log_ui("最初からやり直す", {"from_step": st.session_state.get("step")})
        for k in CASE_RESET_KEYS:
            if k in st.session_state:
                del st.session_state[k]
        st.session_state.step = 1
        st.rerun()
    with st.expander("⚙️ 積算ルール設定"):
        st.caption("GPTへの追加指示（例：足場は外周×高さで計算、シーリングは外壁×1.6）")
        rules_input = st.text_area(
            "カスタム積算ルール",
            value=st.session_state.estimation_rules,
            height=120,
            placeholder="例）\n・足場は外周×高さで計算すること\n・シーリングは外壁×1.6mを目安にすること\n・土台水切は建物1周の長さで計算すること",
            key="rules_sidebar",
        )
        if st.button("💾 ルールを保存", use_container_width=True, key="save_rules"):
            st.session_state.estimation_rules = rules_input
            from core.auth import save_estimation_rules
            save_estimation_rules(st.session_state.company_id, rules_input)
            log_admin("積算ルール保存", {"rules_length": len(rules_input)})
            st.success("保存しました")

    if st.button("💰 単価設定", use_container_width=True, key="open_price_settings"):
        st.session_state.show_price_settings = not st.session_state.get("show_price_settings", False)

    if st.button("⚙️ アカウント設定", use_container_width=True, key="open_account_settings"):
        st.session_state.show_account_settings = not st.session_state.get("show_account_settings", False)

    with st.expander("📋 過去の案件"):
        from core.estimate_storage import list_estimates as _list_est, load_estimate as _load_est
        _ests = _list_est(st.session_state.company_id)
        if not _ests:
            st.caption("まだ保存された案件はありません")
        else:
            st.caption(f"{len(_ests)}件 保存済み")
            for _e in _ests[:30]:
                _ec1, _ec2 = st.columns([4, 1])
                with _ec1:
                    st.markdown(
                        f"**{_e['client_name']}**  \n"
                        f"{_e['created_at']}  \n"
                        f"¥{_e['total']:,}"
                    )
                with _ec2:
                    if st.button("読込", key=f"load_est_{_e['id']}", use_container_width=True):
                        _ed = _load_est(st.session_state.company_id, _e['id'])
                        if _ed:
                            st.session_state.project    = _ed["project"]
                            st.session_state.quantities = _ed["quantities"]
                            st.session_state.estimation = _ed["estimation"]
                            if _ed.get("estimation_sheet_data"):
                                st.session_state.estimation_sheet_data = _ed["estimation_sheet_data"]
                            st.session_state.step = 5
                            st.success(f"{_e['client_name']} を読み込みました")
                            st.rerun()
    st.markdown("---")

    st.markdown("**🎨 テーマ**")
    selected_theme = st.radio(
        "テーマ選択",
        list(_THEMES.keys()),
        index=list(_THEMES.keys()).index(st.session_state.get("theme", "スタンダード")),
        key="theme_radio",
        label_visibility="collapsed",
    )
    if selected_theme != st.session_state.get("theme"):
        st.session_state.theme = selected_theme
        st.rerun()
    st.markdown("---")

    if st.button("🚪 ログアウト", use_container_width=True):
        log_auth("ログアウト", st.session_state.get("company_id", ""), True)
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

st.title("🏠 AI塗装積算システム")  # v20260704

# ─── 単価設定画面（ボタン押下時に表示）───────────────────────
if st.session_state.get("show_price_settings", False):
    st.header("💰 単価設定")
    st.caption("工事種別ごとの単価を変更できます（円）。変更後「保存」してください。")
    from core.quantity_calculator import UNIT_PRICES as _DEFAULT_PRICES
    _current_prices = st.session_state.get("unit_prices") or dict(_DEFAULT_PRICES)
    _price_labels = {
        "外部足場":         ("外部足場（㎡）", "仮設工事"),
        "屋根足場":         ("屋根足場（㎡）", "仮設工事"),
        "ガードマン":       ("ガードマン（人）", "仮設工事"),
        "防護管":           ("防護管（式）", "仮設工事"),
        "屋根塗装":         ("屋根塗装（㎡）", "塗装工事（屋根）"),
        "外壁塗装":         ("外壁塗装（㎡）", "塗装工事（外壁）"),
        "破風鼻隠し塗装":   ("破風・鼻隠し（m）", "塗装工事（付帯部）"),
        "軒天塗装_m":       ("軒天（m）", "塗装工事（付帯部）"),
        "雨樋塗装":         ("雨樋（m）", "塗装工事（付帯部）"),
        "土台水切塗装":     ("土台水切（m）", "塗装工事（付帯部）"),
        "シャッターボックス":("シャッターボックス（m）","塗装工事（付帯部）"),
        "出窓天端塗装":     ("出窓天端（m）", "塗装工事（付帯部）"),
        "化粧梁付梁塗装":   ("化粧梁・付梁（m）", "塗装工事（付帯部）"),
        "基礎塗装":         ("基礎塗装（式）", "塗装工事（付帯部）"),
        "カーポート脱着":   ("カーポート・バルコニー脱着（式）", "仮設工事（オプション）"),
        "目地シーリング":   ("目地シーリング（m）", "シーリング工事"),
        "雑シーリング":     ("雑シーリング（式）", "シーリング工事"),
        "トップライト":     ("トップライトシーリング（箇所）", "シーリング工事"),
        "諸経費":           ("諸経費（式）", "諸経費"),
    }
    _new_prices = dict(_current_prices)
    _prev_cat = ""
    for key, (label, cat) in _price_labels.items():
        if cat != _prev_cat:
            st.subheader(cat)
            _prev_cat = cat
        col_l, col_r = st.columns([2, 1])
        with col_l:
            st.markdown(f"**{label}**")
        with col_r:
            _new_prices[key] = st.number_input(
                label, min_value=0,
                value=int(_current_prices.get(key, _DEFAULT_PRICES.get(key, 0))),
                step=100, key=f"price_{key}",
                label_visibility="collapsed",
            )
    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 保存して閉じる", type="primary", use_container_width=True):
            changed = {k: {"old": _current_prices.get(k), "new": v}
                       for k, v in _new_prices.items() if v != _current_prices.get(k)}
            st.session_state.unit_prices = _new_prices
            st.session_state.show_price_settings = False
            from core.auth import save_unit_prices
            save_unit_prices(st.session_state.company_id, _new_prices)
            log_admin("単価設定保存", {"changed_items": changed})
            st.success("単価を保存しました")
            st.rerun()
    with c2:
        if st.button("✕ キャンセル", use_container_width=True):
            st.session_state.show_price_settings = False
            st.rerun()
    st.stop()

# ─── アカウント設定画面 ────────────────────────────────────────
if st.session_state.get("show_account_settings", False):
    st.header("⚙️ アカウント設定")
    from core.auth import (
        get_company, update_company_info, change_password,
        list_companies, add_company,
    )

    _cid = st.session_state.company_id
    _cdata = get_company(_cid) or {}
    _is_admin = _cdata.get("is_admin", False) or _cid == "admin"

    # ── 会社情報編集 ──────────────────────────────────────────
    st.subheader("🏢 会社情報")
    with st.form("company_info_form"):
        _ci1, _ci2 = st.columns(2)
        _new_name  = _ci1.text_input("会社名",   value=_cdata.get("company_name", ""))
        _new_dept  = _ci2.text_input("部署",     value=_cdata.get("department", ""))
        _new_cont  = _ci1.text_input("担当者名", value=_cdata.get("contact_name", ""))
        _new_tel   = _ci2.text_input("TEL",      value=_cdata.get("tel", ""))
        _new_fax   = _ci1.text_input("FAX",      value=_cdata.get("fax", ""))
        _new_addr  = st.text_input("住所",       value=_cdata.get("address", ""))
        _save_info = st.form_submit_button("💾 会社情報を保存", type="primary", use_container_width=True)
        if _save_info:
            update_company_info(_cid, {
                "company_name": _new_name,
                "department":   _new_dept,
                "contact_name": _new_cont,
                "tel":          _new_tel,
                "fax":          _new_fax,
                "address":      _new_addr,
            })
            log_admin("会社情報保存", {"company_name": _new_name, "contact_name": _new_cont, "tel": _new_tel})
            st.success("✅ 会社情報を保存しました")

    st.markdown("---")

    # ── パスワード変更 ────────────────────────────────────────
    st.subheader("🔑 パスワード変更")
    with st.form("change_pw_form"):
        _old_pw  = st.text_input("現在のパスワード", type="password")
        _new_pw  = st.text_input("新しいパスワード", type="password")
        _new_pw2 = st.text_input("新しいパスワード（確認）", type="password")
        _chg_pw  = st.form_submit_button("🔑 変更する", type="primary", use_container_width=True)
        if _chg_pw:
            if not _old_pw or not _new_pw:
                st.error("全フィールドを入力してください")
            elif _new_pw != _new_pw2:
                st.error("新しいパスワードが一致しません")
            elif len(_new_pw) < 4:
                st.error("パスワードは4文字以上にしてください")
            else:
                if change_password(_cid, _old_pw, _new_pw):
                    log_admin("パスワード変更成功", {"company_id": _cid})
                    st.success("✅ パスワードを変更しました")
                else:
                    log_admin("パスワード変更失敗（現在PW不一致）", {"company_id": _cid})
                    st.error("現在のパスワードが間違っています")

    # ── 管理者専用セクション ──────────────────────────────────
    if _is_admin:
        st.markdown("---")
        st.subheader("🔐 管理者専用")

        # アカウント一覧
        _companies = list_companies()
        st.markdown(f"**登録会社一覧（{len(_companies)}社）**")
        import pandas as pd
        _rows = [
            {
                "会社ID":    c["id"],
                "会社名":    c.get("company_name", ""),
                "担当者":    c.get("contact_name", ""),
                "TEL":       c.get("tel", ""),
                "作成日":    c.get("created_at", "")[:10] if c.get("created_at") else "",
                "管理者":    "✅" if c.get("is_admin") else "",
            }
            for c in _companies
        ]
        st.dataframe(pd.DataFrame(_rows), hide_index=True, use_container_width=True)

        # パスワードリセット
        st.markdown("**パスワードリセット（強制変更）**")
        with st.form("reset_pw_form"):
            _all_ids = [c["id"] for c in _companies]
            _target_id  = st.selectbox("対象アカウント", _all_ids, key="admin_reset_target")
            _reset_pw   = st.text_input("新しいパスワード", type="password", key="admin_reset_pw")
            _reset_btn  = st.form_submit_button("🔑 強制リセット", use_container_width=True)
            if _reset_btn:
                if not _reset_pw or len(_reset_pw) < 4:
                    st.error("4文字以上のパスワードを入力してください")
                else:
                    import hashlib
                    from core.auth import _load_accounts, _save_accounts, _hash_password
                    _d = _load_accounts()
                    for _c in _d["companies"]:
                        if _c["id"] == _target_id:
                            _c["password_hash"] = _hash_password(_reset_pw)
                            _save_accounts(_d)
                            log_admin("管理者: PW強制リセット", {"target_id": _target_id, "by": _cid})
                            st.success(f"✅ {_target_id} のパスワードをリセットしました")
                            break

        # 新規アカウント追加
        st.markdown("---")
        st.markdown("**新規アカウント追加**")
        with st.form("add_company_form"):
            _na1, _na2 = st.columns(2)
            _new_id    = _na1.text_input("会社ID（英数字）")
            _new_cname = _na2.text_input("会社名")
            _init_pw   = _na1.text_input("初期パスワード", type="password")
            _new_admin = _na2.checkbox("管理者権限を付与")
            _add_btn   = st.form_submit_button("➕ 追加する", type="primary", use_container_width=True)
            if _add_btn:
                if not _new_id or not _new_cname or not _init_pw:
                    st.error("全フィールドを入力してください")
                elif len(_init_pw) < 4:
                    st.error("パスワードは4文字以上にしてください")
                else:
                    _ok = add_company(
                        _new_id, _new_cname, _init_pw,
                        is_admin=_new_admin,
                    )
                    if _ok:
                        log_admin("管理者: 新規アカウント追加", {"new_id": _new_id, "new_name": _new_cname, "is_admin": _new_admin})
                        st.success(f"✅ {_new_id}（{_new_cname}）を追加しました")
                        st.rerun()
                    else:
                        log_admin("管理者: 新規アカウント追加失敗（ID重複）", {"new_id": _new_id})
                        st.error(f"ID「{_new_id}」は既に存在します")

    # ── ログビューア ─────────────────────────────────────────
    st.markdown("---")
    st.subheader("🔍 操作ログビューア")
    _logs = get_session_logs()
    if not _logs:
        st.info("このセッションにログはまだありません。操作するとここに表示されます。")
    else:
        # フィルタ
        _lv_cols = st.columns(3)
        _cat_opts = ["すべて"] + sorted(set(e.get("category","") for e in _logs))
        _lvl_opts = ["すべて", "INFO", "WARN", "ERROR"]
        _sel_cat = _lv_cols[0].selectbox("カテゴリ", _cat_opts, key="log_cat_filter")
        _sel_lvl = _lv_cols[1].selectbox("レベル", _lvl_opts, key="log_lvl_filter")
        _sel_n   = _lv_cols[2].number_input("表示件数", min_value=10, max_value=500, value=50, step=10, key="log_n")
        _filtered = [
            e for e in _logs
            if (_sel_cat == "すべて" or e.get("category") == _sel_cat)
            and (_sel_lvl == "すべて" or e.get("level") == _sel_lvl)
        ]
        _show = list(reversed(_filtered))[:int(_sel_n)]
        st.caption(f"全{len(_filtered)}件中 最新{len(_show)}件を表示")
        import pandas as pd
        _log_rows = [{
            "時刻":     e.get("ts","")[-12:],
            "Lv":       e.get("level",""),
            "カテゴリ": e.get("category",""),
            "イベント": e.get("event",""),
        } for e in _show]
        st.dataframe(pd.DataFrame(_log_rows), use_container_width=True, hide_index=True)
        # 選択ログの詳細
        _sel_idx = st.number_input("詳細表示（行番号 0〜）", min_value=0, max_value=max(0, len(_show)-1), value=0, step=1, key="log_detail_idx")
        if _show:
            st.json(_show[int(_sel_idx)])
        # ダウンロード
        st.download_button(
            "📥 ログをJSONでダウンロード",
            data=export_session_logs_json().encode("utf-8"),
            file_name=f"app_log_{__import__('datetime').datetime.now().strftime('%Y%m%d_%H%M')}.json",
            mime="application/json",
            use_container_width=True,
        )
        # ローカルファイルログも表示（Claude読み取り用）
        if _is_admin:
            with st.expander("📂 ファイルログ（ローカル実行時のみ）"):
                _log_dates = list_log_dates(_cid)
                if _log_dates:
                    _sel_date = st.selectbox("日付", _log_dates, key="log_date_sel")
                    _file_logs = get_file_logs(_cid, _sel_date)
                    st.caption(f"{_sel_date}: {len(_file_logs)}件")
                    if _file_logs:
                        st.dataframe(pd.DataFrame([{
                            "時刻": e.get("ts","")[-12:], "Lv": e.get("level",""),
                            "カテゴリ": e.get("category",""), "イベント": e.get("event",""),
                        } for e in reversed(_file_logs)]), use_container_width=True, hide_index=True)
                else:
                    st.info("ファイルログがありません（Streamlit Cloud では揮発性のため残りません）")

    st.markdown("---")
    if st.button("✕ 閉じる", use_container_width=True, key="close_account_settings"):
        st.session_state.show_account_settings = False
        st.rerun()
    st.stop()


# ═════════════════════════════════════════════════════════════
# STEP 1: 案件情報入力
# ═════════════════════════════════════════════════════════════
if st.session_state.step == 1:
    st.header("① 現場メモ入力")
    st.caption("🎤 音声メモ1本で見積もりの8割が完成します。必須はお客様名・現場住所だけ。")

    # ── 音声メモ（メイン入力）─────────────────────────────────
    st.subheader("🎤 現場音声メモ（メイン入力）")
    st.markdown(
        "現場を歩きながら、**面積・長さ・施工範囲**を吹き込んでください。\n\n"
        "> 例：「住吉屋さんの現場、外壁サイディング237平米、屋根スレート190平米、"
        "破風74メートル、雨樋92メートル、土台水切49メートル、目地シーリング202メートル、"
        "2階建て、道路使用許可必要」"
    )

    ac1, ac2 = st.columns([1, 1])
    with ac1:
        audio_input = st.audio_input("ここで録音 →")
        if audio_input is not None and st.button(
            "🎧 文字起こし実行", use_container_width=True):
            with st.spinner("Whisperで文字起こし中…"):
                try:
                    from modules.llm_client import LLMClient
                    llm = LLMClient()
                    text = llm.transcribe_audio(audio_input.getvalue(), "memo.webm")
                    prev = st.session_state.voice_memo
                    st.session_state.voice_memo = (prev + "\n" + text).strip() if prev else text
                    log_ui("STEP1: 音声文字起こし完了", {"text_len": len(text), "audio_size": len(audio_input.getvalue())})
                    st.success("文字起こし完了！右の欄に反映しました。")
                    st.rerun()
                except Exception as e:
                    log_error("STEP1: 音声文字起こし失敗", e)
                    st.error(f"文字起こし失敗: {e}")
    with ac2:
        voice_memo = st.text_area(
            "音声メモ（文字起こし結果・手入力も可）",
            value=st.session_state.voice_memo,
            height=180,
            placeholder="外壁237平米、屋根190平米、破風74メートル、雨樋92メートル…",
        )

    st.markdown("---")

    # ── お客様情報（必須）＋ 補足資料（任意）─────────────────
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("👤 お客様情報（必須）")
        _p = st.session_state.project
        client_name  = st.text_input("お客様名 ＊",
            value=_p.get("client_name", ""), placeholder="例：住吉屋 栄子 様")
        site_address = st.text_input("現場住所 ＊",
            value=_p.get("site_address", ""), placeholder="例：東京都世田谷区…")
        sales_rep    = st.text_input("担当者名",
            value=_p.get("sales_rep", ""), placeholder="例：山田 太郎")
    with col2:
        st.subheader("📄 補足資料（任意）")
        pdf_file = st.file_uploader(
            "図面PDF（あれば面積を自動補完）", type=["pdf"],
            help="音声で言い忘れた面積を図面から補います",
        )
        if pdf_file:
            _scale_cols = st.columns(2)
            drawing_scale = _scale_cols[0].selectbox(
                "図面の縮尺",
                ["不要", "1/100", "1/200", "1/50", "1/150", "1/250", "1/300"],
                index=1,
                help="図面に記載されている縮尺。1/100・1/200が一般的",
            )
            if drawing_scale != "不要":
                original_paper = _scale_cols[1].selectbox(
                    "元の用紙サイズ（補正）",
                    ["補正なし", "A1", "A2", "A3", "A4"],
                    index=0,
                    help="縮尺を合わせてコピー済みなら「補正なし」。A2図面をA4スキャンした場合はA2を選択",
                )
            else:
                original_paper = None
        else:
            drawing_scale = "不要"
            original_paper = None
        floor_plan_file = st.file_uploader(
            "📐 平面図PDF（間取り図・あれば窓位置を正確に取得）",
            type=["pdf"],
            help="立面図とは別に平面図（間取り図）があればアップロード。窓・ドアの正確な位置を取得して3D精度が向上します",
        )
        photo_files = st.file_uploader(
            "現場写真（あれば劣化状況を解析・複数可）",
            type=["jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True,
        )

    with st.expander("🏗️ 建物情報を補足する（任意）"):
        bc1, bc2, bc3 = st.columns(3)
        building_type   = bc1.selectbox("建物種別",
                            ["戸建て", "共同住宅", "マンション", "店舗・工場"])
        building_floors = bc2.number_input("階数",
                            min_value=1, max_value=10, value=2, step=1)
        building_area   = bc3.number_input("建築面積（㎡）",
                            min_value=0.0, value=0.0, step=1.0)

    with st.expander("🔧 工事オプション（任意）"):
        st.caption("音声で言い忘れた項目をここで追加できます")
        eo = st.session_state.extra_options
        oc1, oc2, oc3 = st.columns(3)
        with oc1:
            opt_guardman    = st.number_input("ガードマン（人）", min_value=0,
                                value=int(eo.get("guardman_count", 0)), step=1)
            opt_window_top  = st.number_input("出窓天端（m）", min_value=0.0,
                                value=float(eo.get("window_top_length", 0)), step=0.5)
            opt_beam        = st.number_input("化粧梁・付梁（m）", min_value=0.0,
                                value=float(eo.get("beam_length", 0)), step=0.5)
        with oc2:
            opt_shutter     = st.number_input("シャッターボックス（m）", min_value=0.0,
                                value=float(eo.get("shutter_box_length", 0)), step=0.5)
            opt_soffit_sqm  = st.number_input("ベランダ軒天面積（㎡）", min_value=0.0,
                                value=float(eo.get("soffit_balcony_sqm", 0)), step=0.5)
            opt_skylight    = st.number_input("トップライト（箇所）", min_value=0,
                                value=int(eo.get("skylight_count", 0)), step=1)
        with oc3:
            opt_protection  = st.checkbox("防護管設置", value=eo.get("do_protection_pipe", False))
            opt_carport     = st.checkbox("カーポート・バルコニー屋根脱着",
                                value=eo.get("do_carport", False))
            opt_foundation  = st.checkbox("基礎塗装", value=eo.get("do_foundation", False))
        # オプションをセッションに保存（ボタン押下前でも）
        st.session_state.extra_options = {
            "guardman_count":     opt_guardman,
            "window_top_length":  opt_window_top,
            "beam_length":        opt_beam,
            "shutter_box_length": opt_shutter,
            "soffit_balcony_sqm": opt_soffit_sqm,
            "skylight_count":     opt_skylight,
            "do_protection_pipe": opt_protection,
            "do_carport":         opt_carport,
            "do_foundation":      opt_foundation,
        }

    st.markdown("---")
    if st.button("🚀 見積もりを作成する", type="primary", use_container_width=True):
        if not client_name:
            st.error("お客様名を入力してください")
        elif not site_address:
            st.error("現場住所を入力してください")
        else:
            st.session_state.project = {
                "client_name":     client_name,
                "site_address":    site_address,
                "sales_rep":       sales_rep,
                "project_name":    f"{client_name}邸 塗装工事",
                "building_type":   building_type,
                "building_floors": building_floors,
                "building_area":   building_area,
                "voice_memo":      voice_memo,
            }
            if pdf_file:
                st.session_state["pdf_bytes"] = pdf_file.getvalue()
                st.session_state["drawing_scale"]  = drawing_scale
                st.session_state["original_paper"] = original_paper
            elif "pdf_bytes" in st.session_state:
                del st.session_state["pdf_bytes"]
                st.session_state.pop("drawing_scale", None)
                st.session_state.pop("original_paper", None)
            if floor_plan_file:
                st.session_state["floor_plan_bytes"] = floor_plan_file.getvalue()
            elif "floor_plan_bytes" in st.session_state:
                del st.session_state["floor_plan_bytes"]
            if photo_files:
                st.session_state["photo_bytes_list"] = [f.getvalue() for f in photo_files]
            elif "photo_bytes_list" in st.session_state:
                del st.session_state["photo_bytes_list"]
            st.session_state.voice_memo = voice_memo
            st.session_state.auto_done  = False
            st.session_state.step = 2
            log_ui("STEP1→STEP2遷移: 見積もり作成開始", {
                "has_pdf": bool(pdf_file),
                "has_photos": bool(photo_files),
                "has_voice": bool(voice_memo.strip()),
                "building_type": building_type,
                "floors": building_floors,
            })
            st.rerun()


# ═════════════════════════════════════════════════════════════
# STEP 2: AI解析
# ═════════════════════════════════════════════════════════════
elif st.session_state.step == 2:
    st.header("② AI自動積算")
    proj       = st.session_state.project
    voice_text = (proj.get("voice_memo") or "").strip()
    has_voice  = bool(voice_text)
    has_pdf    = "pdf_bytes" in st.session_state
    has_photos = bool(st.session_state.get("photo_bytes_list"))

    def _merge_drawing(q, drawing_data, annotations=None):
        """図面で得た面積を、音声で未入力(0)の項目だけ補完する。"""
        # faces.total_wall_area を優先（開口部控除済みの正確な値）
        faces = drawing_data.get("faces") or {}
        total_wall_area = drawing_data.get("total_wall_area") or faces.get("total_wall_area")
        wall = total_wall_area or drawing_data.get("exterior_wall_area")
        roof = drawing_data.get("roof_area")

        # annotationsから幅・高さを取得して幾何計算
        # wall または roof が未取得の場合にフォールバック（独立して判定）
        if (not wall or not roof) and annotations:
            def _ann_val(kw, items):
                for a in items:
                    if kw in a.get("label", "") and a.get("confidence") in ("high", "medium"):
                        try:
                            return float(a["value"])
                        except Exception:
                            pass
                return None
            south_w = _ann_val("南面幅", annotations)
            east_w  = _ann_val("東面幅", annotations)
            eave_h  = _ann_val("軒高",   annotations) or 6.5
            ridge_h = _ann_val("棟高",   annotations) or 8.693
            if south_w and east_w:
                try:
                    from core.drawing_calc import calc_geometry_4face
                    geo = calc_geometry_4face(
                        south_width_m=south_w, north_width_m=0,
                        east_width_m=east_w,   west_width_m=0,
                        ridge_height_m=ridge_h, eave_height_m=eave_h,
                        opening_deduction_rate=0.15,
                    )
                    if not wall:
                        wall = geo["wall_net_total"]
                    if not roof:
                        roof = geo["roof_area_m2"]
                    # 土台水切 = 周長（1データポイントで確認済み: 周長×1.5≈実測値）
                    # 保守的に周長のみ使用。テスターデータ蓄積後に係数調整予定
                    if not q.get("water_cutoff_length"):
                        perimeter = 2 * (south_w + east_w)
                        q["water_cutoff_length"] = round(perimeter, 1)
                except Exception:
                    pass

        if wall and not q.get("wall_area"):
            q["wall_area"]     = float(wall)
            q["scaffold_area"] = round(float(wall) * 1.1, 1)
            if not q.get("joint_seal_length"):
                q["joint_seal_length"] = round(float(wall) * 0.85, 1)
        if roof and not q.get("roof_area"):
            q["roof_area"] = float(roof)
            if q.get("do_roof", True):
                q["roof_scaffold_area"] = float(roof)
        return q

    def _merge_photo(q, image_data):
        """写真解析で得た数量を、未入力(0)の項目だけ補完する。"""
        if not image_data or "quantities" not in image_data:
            return q
        iq = image_data["quantities"]
        for src, dst in [
            ("exterior_wall_area", "wall_area"),
            ("roof_area",          "roof_area"),
            ("fascia_length",      "fascia_length"),
            ("gutter_length",      "gutter_length"),
            ("sealing_length",     "joint_seal_length"),
        ]:
            v = iq.get(src, {})
            val = v.get("value") if isinstance(v, dict) else None
            if val and not q.get(dst):
                q[dst] = float(val)
        return q

    # ── データが何も無い → 手動フォームへ ───────────────────
    if not has_voice and not has_pdf and not has_photos:
        st.info("音声メモ・図面・写真がありません。手動で数量を入力してください。")
        if st.button("✏️ 数量入力フォームへ →", type="primary"):
            from core.voice_extractor import build_quantities
            st.session_state.quantities = build_quantities({})
            log_ui("STEP2: データなし→手動フォームへ")
            st.session_state.step = 4
            st.rerun()
        if st.button("← 入力に戻る"):
            log_ui("STEP2→STEP1: 入力に戻る")
            st.session_state.step = 1
            st.rerun()
        st.stop()

    # ── 自動積算 未実行 → 実行ボタン ─────────────────────────
    if not st.session_state.get("auto_done"):
        srcs = []
        if has_voice:  srcs.append("🎤 音声メモ")
        if has_pdf:    srcs.append("📐 図面PDF")
        if has_photos: srcs.append("📸 現場写真")
        st.caption("入力ソース： " + " ＋ ".join(srcs))

        if st.button("▶️ 自動積算を実行する", type="primary", use_container_width=True):
            log_ui("自動積算実行ボタン", {"has_voice": has_voice, "has_pdf": has_pdf, "has_photos": has_photos})
            with st.spinner("AIが音声・資料から数量を抽出中…（30秒〜1分程度）"):
                try:
                    from modules.llm_client import LLMClient
                    from core.voice_extractor import extract_quantities, build_quantities
                    llm = LLMClient()

                    extras, raw = {}, {}
                    if has_voice:
                        custom_rules = st.session_state.get("estimation_rules", "")
                        result    = extract_quantities(voice_text, llm, custom_rules=custom_rules)
                        quantities = result["quantities"]
                        extras     = result["extras"]
                        raw        = result["raw"]
                        st.session_state["_voice_gpt_raw"] = result.get("_gpt_raw_text", "")
                    else:
                        # 音声なし（図面/写真のみ）→ 経験則のベース dict から開始
                        quantities = build_quantities({})

                    if has_pdf:
                        from core.drawing_analyzer import DrawingAnalyzer, CATEGORY_LABELS
                        da = DrawingAnalyzer(llm.api_key)
                        drawing_data, annotated_img, annotations = da.analyze_with_annotations(
                            st.session_state.pdf_bytes,
                            stated_scale=st.session_state.get("drawing_scale", "不要"),
                            original_paper=st.session_state.get("original_paper"),
                        )
                        st.session_state.drawing_data = drawing_data
                        st.session_state.drawing_annotated_img = annotated_img
                        st.session_state.drawing_annotations = annotations
                        # 4面分割用に1ページ目の生画像（マーカー無し）を保持
                        try:
                            _raw_imgs, _ = da.pdf_to_images(st.session_state.pdf_bytes)
                            st.session_state.drawing_page1_raw = (
                                _raw_imgs[0] if _raw_imgs else annotated_img
                            )
                        except Exception:
                            st.session_state.drawing_page1_raw = annotated_img
                        # ── Building Model v1.0 生成（Step A）────────────────────
                        # _merge_drawing() は変更せず、Building Model を session_state に保存するのみ
                        try:
                            from core.building_model import build_building_model
                            _bm = build_building_model(
                                drawing_data, annotations or []
                            )
                            st.session_state["building_model"] = _bm
                        except Exception as _bm_e:
                            st.session_state["building_model"] = {
                                "_error": str(_bm_e),
                                "_schema": "Building_Model_v1.0",
                            }
                        # ──────────────────────────────────────────────────────────
                        quantities = _merge_drawing(quantities, drawing_data, annotations)

                    if "floor_plan_bytes" in st.session_state:
                        try:
                            from core.drawing_analyzer import DrawingAnalyzer
                            _fp_da = DrawingAnalyzer(llm.api_key)
                            _fp_data = _fp_da.analyze_floor_plan(
                                st.session_state["floor_plan_bytes"]
                            )
                            if "error" not in _fp_data:
                                st.session_state["floor_plan_data"] = _fp_data
                                # 平面図のfacesで窓x座標を上書き（より正確）
                                _fp_faces = _fp_data.get("faces") or {}
                                if _fp_faces:
                                    # drawing_dataのfacesをマージ（x_from_left付き）
                                    _existing_dd = st.session_state.get("drawing_data") or {}
                                    _existing_faces = _existing_dd.get("faces") or {}
                                    for _fn, _fdata in _fp_faces.items():
                                        if _fn in _existing_faces:
                                            _existing_faces[_fn]["openings"] = _fdata.get("openings", [])
                                            _existing_faces[_fn]["x_from_left_available"] = True
                                        else:
                                            _existing_faces[_fn] = _fdata
                                    if _existing_dd:
                                        _existing_dd["faces"] = _existing_faces
                                        st.session_state["drawing_data"] = _existing_dd
                                # 建物外形寸法を平面図から補完
                                _fp_w = _fp_data.get("total_width")
                                _fp_d = _fp_data.get("total_depth")
                                if _fp_w and not quantities.get("wall_area"):
                                    quantities["scaffold_area"] = round(float(_fp_w) * 1.1, 1)
                                st.info(f"📐 平面図解析完了: 幅{_fp_data.get('total_width','?')}m × 奥行{_fp_data.get('total_depth','?')}m")
                            else:
                                st.warning(f"平面図解析エラー: {_fp_data.get('error')}")
                        except Exception as _fp_e:
                            st.warning(f"平面図解析スキップ: {_fp_e}")

                    if has_photos:
                        from modules.image_analyzer import ImageAnalyzer
                        ia = ImageAnalyzer(llm)
                        desc = voice_text + f"\n建物種別: {proj.get('building_type','')}"
                        image_data = ia.analyze(st.session_state.photo_bytes_list, desc)
                        st.session_state.image_data = image_data
                        quantities = _merge_photo(quantities, image_data)

                    # extra_options（工事オプション欄）で上書き
                    eo = st.session_state.get("extra_options", {})
                    if eo.get("guardman_count", 0):
                        quantities["guardman_count"]    = eo["guardman_count"]
                    if eo.get("window_top_length", 0):
                        quantities["window_top_length"] = eo["window_top_length"]
                    if eo.get("beam_length", 0):
                        quantities["beam_length"]       = eo["beam_length"]
                    if eo.get("shutter_box_length", 0):
                        quantities["shutter_box_length"]= eo["shutter_box_length"]
                    if eo.get("soffit_balcony_sqm", 0):
                        quantities["soffit_balcony_sqm"] = eo["soffit_balcony_sqm"]
                    if eo.get("skylight_count", 0):
                        quantities["skylight_count"]    = eo["skylight_count"]
                    if eo.get("do_protection_pipe"):
                        quantities["do_protection_pipe"]= True
                    if eo.get("do_carport"):
                        quantities["do_carport"]        = True
                    if eo.get("do_foundation"):
                        quantities["do_foundation"]     = True

                    st.session_state.quantities   = quantities
                    st.session_state.voice_extras = extras
                    st.session_state.voice_raw    = raw
                    st.session_state.estimation   = calculate_from_quantities(
                        quantities,
                        client_name=proj.get("client_name", ""),
                        site_address=proj.get("site_address", ""),
                        sales_rep=proj.get("sales_rep", ""),
                    )
                    st.session_state.auto_done = True
                    log_ui("自動積算完了", {
                        "wall_area": quantities.get("wall_area"),
                        "roof_area": quantities.get("roof_area"),
                        "scaffold_area": quantities.get("scaffold_area"),
                    })
                    st.rerun()

                except Exception as e:
                    log_error("自動積算エラー", e)
                    st.error(f"自動積算エラー: {e}")
                    st.info("APIキー未設定などの場合は、下のボタンで手動入力に切り替えできます。")

        if st.button("✏️ 手動入力で進める（AIを使わない）"):
            from core.voice_extractor import build_quantities
            st.session_state.quantities = build_quantities({})
            log_ui("STEP2: AI使わず手動入力へ")
            st.session_state.step = 4
            st.rerun()
        if st.button("← 入力に戻る"):
            log_ui("STEP2→STEP1: 入力に戻る")
            st.session_state.step = 1
            st.rerun()

    # ── 自動積算 完了 → サマリー表示 ─────────────────────────
    else:
        # 修正反映後に入力欄を空に戻す（widget生成前に値を設定する公式パターン）
        if st.session_state.pop("_clear_correction", False):
            st.session_state["correction_input"] = ""

        q      = st.session_state.quantities
        extras = st.session_state.get("voice_extras", {})
        est    = st.session_state.estimation
        st.success("✅ 自動積算が完了しました！内容をご確認ください。")

        # ── 図面読み取り確認ビュー ────────────────────────────
        ann_img   = st.session_state.get("drawing_annotated_img")
        ann_items = st.session_state.get("drawing_annotations", [])
        if ann_img:
            with st.expander("📐 図面読み取り確認（AIが何を読んだか）", expanded=True):
                img_col, tbl_col = st.columns([2, 1])
                with img_col:
                    st.image(ann_img, caption="● 色付きマーカー = AIが読み取った寸法の位置",
                             use_container_width=True)
                    from core.drawing_analyzer import CATEGORY_LABELS
                    color_hex = {"height": "#185FA5", "width": "#0F6E56", "roof": "#993C1D",
                                 "scale": "#534AB7", "area": "#993C1D", "other": "#5F5E5A"}
                    cats_shown = list(dict.fromkeys(a.get("category", "other") for a in ann_items))
                    legend_cols = st.columns(min(len(cats_shown), 3) or 1)
                    for i, cat in enumerate(cats_shown[:6]):
                        hex_c = color_hex.get(cat, "#5F5E5A")
                        lbl   = CATEGORY_LABELS.get(cat, cat)
                        legend_cols[i % 3].markdown(
                            f"<span style='color:{hex_c};font-size:1.1em'>●</span> {lbl}",
                            unsafe_allow_html=True,
                        )
                with tbl_col:
                    st.markdown("**読み取り結果一覧**")
                    if ann_items:
                        conf_jp = {"high": "✅ 確定", "medium": "⚠️ 推定", "low": "❓ 不鮮明"}
                        rows = []
                        for a in ann_items:
                            val_str = f"{a.get('value', '')} {a.get('unit', '')}".strip()
                            rows.append({
                                "項目":       a.get("label", ""),
                                "読み取り値": val_str,
                                "信頼度":     conf_jp.get(a.get("confidence", "low"), "❓ 不鮮明"),
                            })
                        import pandas as pd
                        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
                        low_items = [a.get("label") for a in ann_items if a.get("confidence") == "low"]
                        if low_items:
                            st.warning("⚠️ 不鮮明: " + "、".join(low_items) + "\n手動で確認・修正してください。")
                    else:
                        st.info("アノテーション情報なし")

        # ── 図面クリック計測 ───────────────────────────────────
        drawing_img_bytes = st.session_state.get("drawing_annotated_img")
        # 4面分割で使う1ページ目の生画像（マーカー無し）。無ければ注釈付き画像で代用。
        drawing_raw_bytes = st.session_state.get("drawing_page1_raw") or drawing_img_bytes
        if drawing_img_bytes:

            # ② 図面拡大表示用ダイアログ
            @st.dialog("🔍 図面拡大表示", width="large")
            def _zoom_dialog(_img, _caption=""):
                st.image(_img, caption=_caption, use_container_width=True)
                st.caption("※ さらに拡大: ブラウザのズーム（Ctrl + マウスホイール）もご利用ください")

            # 画像を上下2段×左右2列の4等分で切り出すヘルパー（③）
            def _crop_quad(_img_bytes, _row, _col):
                from PIL import Image as _PImg
                import io as _io2
                _im = _PImg.open(_io2.BytesIO(_img_bytes))
                _w, _h = _im.size
                _x1 = _col * _w // 2
                _x2 = (_col + 1) * _w // 2
                _y1 = _row * _h // 2
                _y2 = (_row + 1) * _h // 2
                _crop = _im.crop((_x1, _y1, _x2, _y2))
                _out = _io2.BytesIO()
                _crop.save(_out, format="PNG")
                return _out.getvalue()

            # クリック計測UI。fragment 化してクリック毎の全ページ再実行を防ぐ。
            # ns で session_state を名前空間化し、全体図＋4面パネルを独立動作させる。
            @st.fragment
            def _render_click_ruler(_img_bytes, ns="ruler", labels=None,
                                    reflect_map=None, scale_default=9.10):
                try:
                    from streamlit_image_coordinates import streamlit_image_coordinates
                    from PIL import Image, ImageDraw
                    from core.pixel_ruler import LABELS, COLORS
                    import io as _io, math as _math

                    _labels = labels or LABELS
                    _reflect = reflect_map if reflect_map is not None else {
                        "南面幅": "ruler_south_w", "北面幅": "ruler_north_w",
                        "東面幅": "ruler_east_w",  "西面幅": "ruler_west_w",
                    }
                    _k_pts, _k_pending, _k_last = f"{ns}_pts", f"{ns}_pending", f"{ns}_last_coord"

                    _pil_orig = Image.open(_io.BytesIO(_img_bytes))
                    _orig_w, _orig_h = _pil_orig.size
                    _base_w = 900 if _orig_w >= 900 else _orig_w

                    # セッション初期化（名前空間ごと）
                    if _k_pts not in st.session_state:
                        st.session_state[_k_pts] = []      # [{label, x1,y1,x2,y2}]
                    if _k_pending not in st.session_state:
                        st.session_state[_k_pending] = None  # {label, x1, y1}
                    if _k_last not in st.session_state:
                        st.session_state[_k_last] = None

                    # ③ 使い方ガイド（図の上に3ステップ表示）
                    st.markdown(
                        "##### 📖 使い方（3ステップ）\n"
                        "1. **縮尺線を2点クリック** … 寸法が分かっている線（例: 9.10m）の両端をクリック\n"
                        "2. **実寸を入力** … 下の「縮尺基準線の実長（m）」へ図面の数値を入力\n"
                        "3. **幅を測定** … ラベルを選ぶ（自由入力も可）→ 測りたい線を2点クリック"
                    )

                    # ズーム倍率スライダー（拡大してクリック計測が可能）
                    _zoom_pct = st.select_slider(
                        "🔍 ズーム倍率（拡大してクリック計測できます）",
                        options=[50, 75, 100, 150, 200, 300],
                        value=100, key=f"{ns}_zoom",
                        format_func=lambda x: f"{x}%",
                    )
                    _disp_w  = int(_base_w * _zoom_pct / 100)
                    _scale_r = _orig_w / _disp_w
                    _disp_h  = int(_orig_h / _scale_r)
                    _pil_disp = _pil_orig.resize((_disp_w, _disp_h), Image.LANCZOS)

                    # クリック済みの線をプレビュー描画
                    _preview = _pil_disp.copy()
                    _draw = ImageDraw.Draw(_preview)
                    for _seg in st.session_state[_k_pts]:
                        _col = COLORS.get(_seg["label"], "#FF0000")
                        _rgb = tuple(int(_col.lstrip("#")[i:i+2],16) for i in (0,2,4))
                        _draw.line([(_seg["x1"],_seg["y1"]),(_seg["x2"],_seg["y2"])],
                                   fill=_rgb, width=3)
                        _mx, _my = (_seg["x1"]+_seg["x2"])//2, (_seg["y1"]+_seg["y2"])//2
                        _draw.ellipse([_mx-4,_my-4,_mx+4,_my+4], fill=_rgb)
                    # 待機中の1点目
                    if st.session_state[_k_pending]:
                        _px = st.session_state[_k_pending]["x1"]
                        _py = st.session_state[_k_pending]["y1"]
                        _draw.ellipse([_px-6,_py-6,_px+6,_py+6], fill=(255,80,0), outline=(255,255,255), width=2)

                    # 手順表示 ＋ ラベル選択（定型 or 自由入力）④
                    _pending = st.session_state[_k_pending]
                    if _pending is None:
                        _col_a, _col_b = st.columns(2)
                        with _col_a:
                            _cur_label_sel = st.selectbox(
                                "計測する項目（定型）", _labels, key=f"{ns}_cur_label",
                            )
                        with _col_b:
                            _cur_label_free = st.text_input(
                                "ラベル自由入力（入力時はこちらを優先）",
                                key=f"{ns}_free_label", placeholder="例: 玄関ポーチ幅",
                            )
                        _cur_label = _cur_label_free.strip() or _cur_label_sel
                        st.info(f"📍 **{_cur_label}** の **開始点** をクリックしてください")
                    else:
                        _cur_label = _pending["label"]
                        st.success(f"📍 **{_cur_label}** の **終了点** をクリックしてください（開始点: {_pending['x1']}, {_pending['y1']}）")

                    # 画像クリック受付
                    # streamlit-image-coordinates はクリック位置にライブラリ自身が
                    # 赤いマーカーを描画し、それが次のクリックまでブラウザ側に残る。
                    # 計測状態が変わるたびに key を変えて再マウントし、赤マーカーを消す。
                    _ruler_key = f"{ns}_img_{len(st.session_state[_k_pts])}_{'p' if _pending else 'n'}"
                    _coord = streamlit_image_coordinates(_preview, key=_ruler_key, width=_disp_w)

                    # クリック処理（新しいクリックのみ）
                    if _coord and _coord != st.session_state[_k_last]:
                        st.session_state[_k_last] = _coord
                        cx, cy = _coord["x"], _coord["y"]
                        if st.session_state[_k_pending] is None:
                            st.session_state[_k_pending] = {"label": _cur_label, "x1": cx, "y1": cy}
                        else:
                            p = st.session_state[_k_pending]
                            px_len = _math.sqrt((cx-p["x1"])**2 + (cy-p["y1"])**2)
                            new_seg = {
                                "label": p["label"], "x1": p["x1"], "y1": p["y1"],
                                "x2": cx, "y2": cy,
                                "px_disp": round(px_len, 1),
                                "px_orig": round(px_len * _scale_r, 1),
                            }
                            st.session_state[_k_pts].append(new_seg)
                            log_measure("クリック計測: セグメント確定", segments=[new_seg])
                            st.session_state[_k_pending] = None
                        st.rerun(scope="fragment")  # fragment だけ再描画

                    # 計測結果テーブル
                    if st.session_state[_k_pts]:
                        import pandas as pd
                        st.markdown("**計測済みの線**")
                        _rows = [{"ラベル": s["label"], "ピクセル長（表示）": s["px_disp"]}
                                 for s in st.session_state[_k_pts]]
                        st.dataframe(pd.DataFrame(_rows), hide_index=True, use_container_width=True)

                        # 縮尺基準線があれば実寸換算
                        _ref_segs = [s for s in st.session_state[_k_pts] if s["label"] == "縮尺基準線"]
                        if _ref_segs:
                            _ref_real = st.number_input(
                                "縮尺基準線の実長（m）",
                                min_value=0.1, max_value=100.0, value=scale_default,
                                step=0.01, format="%.2f", key=f"{ns}_ref_real",
                                help="図面の寸法数字を確認してここに入力",
                            )
                            _mpp = _ref_real / _ref_segs[0]["px_disp"] if _ref_segs[0]["px_disp"] > 0 else 0

                            if _mpp > 0:
                                _result_rows = []
                                _label_vals = {}
                                for s in st.session_state[_k_pts]:
                                    if s["label"] == "縮尺基準線":
                                        continue
                                    _m = round(s["px_disp"] * _mpp, 3)
                                    _result_rows.append({"ラベル": s["label"], "実寸（m）": _m})
                                    _label_vals[s["label"]] = _m

                                if _result_rows:
                                    st.markdown("**実寸換算結果**")
                                    st.dataframe(pd.DataFrame(_result_rows), hide_index=True, use_container_width=True)

                                    if _reflect and st.button("📐 下の計算フォームに反映", type="primary",
                                                              use_container_width=True, key=f"{ns}_reflect"):
                                        _reflected = {}
                                        for _lab, _key in _reflect.items():
                                            if _lab in _label_vals:
                                                st.session_state[_key] = _label_vals[_lab]
                                                _reflected[_lab] = _label_vals[_lab]
                                        log_measure("クリック計測: フォームに反映", reflected_values=_reflected)
                                        st.success("✅ 幾何学計算フォームに反映しました")
                                        # 下の計算フォームへ反映するためページ全体を再実行
                                        st.rerun()
                        else:
                            st.info("最初に「縮尺基準線」を計測してください（既知の寸法線の上）")

                    # リセットボタン
                    if st.button("🗑️ 計測をリセット", use_container_width=True, key=f"{ns}_reset"):
                        log_measure("クリック計測: リセット", segments=st.session_state.get(_k_pts, []))
                        st.session_state[_k_pts] = []
                        st.session_state[_k_pending] = None
                        st.session_state[_k_last] = None
                        st.rerun(scope="fragment")

                except ImportError:
                    st.warning("⚠️ streamlit-image-coordinates が未インストールです")
                except Exception as _e:
                    st.error(f"クリック計測エラー: {_e}")

            # ── 全体図のクリック計測パネル ──
            with st.expander("📏 図面クリック計測（2点クリックで正確な寸法を読む）", expanded=False):
                if st.button("🔍 図面を拡大表示", key="zoom_full", use_container_width=True):
                    _zoom_dialog(drawing_img_bytes, "図面全体（AI読み取りマーカー付き）")
                _render_click_ruler(drawing_img_bytes, ns="ruler")

            # ── ② 線検出・全寸法抽出 ─────────────────────────────────
            with st.expander("📏 図面の線を全て検出・実寸表示", expanded=False):
                st.caption(
                    "OpenCVで図面の全線分を検出し、縮尺で実寸（m）に換算して表示します。"
                    "検出した数値を付帯部入力に活用できます。"
                )
                # 縮尺設定
                _sc_col1, _sc_col2 = st.columns(2)
                _scale_denom = _sc_col1.number_input(
                    "縮尺（分母）", min_value=10, max_value=1000,
                    value=int(st.session_state.get("drawing_data", {}).get("scale_denominator", 100) or 100),
                    step=10, help="S=1/100 なら 100",
                )
                _min_len = _sc_col2.number_input(
                    "最小検出長（m）", min_value=0.1, max_value=5.0,
                    value=0.5, step=0.1, format="%.1f",
                    help="これ未満の線は無視。小さくすると窓枠等も拾う",
                )

                _orient_filter = st.radio(
                    "表示する線の向き",
                    ["全て", "水平のみ（幅・長さ）", "垂直のみ（高さ）"],
                    horizontal=True,
                )

                if st.button("🔍 線を検出する", type="primary", use_container_width=True, key="btn_line_detect"):
                    with st.spinner("OpenCVで線を解析中…"):
                        try:
                            from core.line_detector import detect_lines_with_lengths
                            _ld_result = detect_lines_with_lengths(
                                img_bytes=drawing_img_bytes,
                                scale_denominator=int(_scale_denom),
                                min_length_m=float(_min_len),
                            )
                            st.session_state["line_detect_result"] = _ld_result
                        except Exception as _e:
                            st.error(f"線検出エラー: {_e}")
                            import traceback
                            st.code(traceback.format_exc())

                _ld = st.session_state.get("line_detect_result")
                if _ld and not _ld.get("error"):
                    _stats = _ld["stats"]
                    _sc1, _sc2, _sc3, _sc4 = st.columns(4)
                    _sc1.metric("検出総数",   f"{_stats['total']}本")
                    _sc2.metric("水平（幅）", f"{_stats['horizontal']}本")
                    _sc3.metric("垂直（高さ）",f"{_stats['vertical']}本")
                    _sc4.metric("斜め",        f"{_stats['diagonal']}本")

                    # ラベル付き画像 / トレースビュー をタブで切り替え
                    _view_tab1, _view_tab2 = st.tabs(["🖼 ラベル付き図面", "📐 ベクタートレース（角度＋寸法）"])

                    with _view_tab1:
                        st.caption("色：🟢8m以上 🟠3m以上 🔵1m以上 🟣1m未満")
                        st.image(_ld["annotated_bytes"], use_container_width=True)

                    with _view_tab2:
                        st.caption("実寸比率・実際の角度でトレース表示。H=水平 V=垂直 数字=傾き角度")
                        _tc1, _tc2, _tc3 = st.columns([2,1,1])
                        _trace_min = _tc1.slider("最小表示長（m）", 0.3, 5.0, 1.0, step=0.1, key="trace_min_len")
                        _show_diag = _tc2.checkbox("斜め線を表示", value=True, key="trace_diag")
                        _show_grid = _tc3.checkbox("グリッド（1m）", value=True, key="trace_grid")
                        _group_blk  = st.checkbox("ブロック代表のみ（各ブロック最長1本）", value=False, key="trace_group")
                        from core.line_detector import generate_trace_svg
                        _svg = generate_trace_svg(
                            lines=_ld["lines"],
                            scale_m_per_px=_ld["scale_m_per_px"],
                            svg_width=860,
                            min_length_m=_trace_min,
                            group_by_block=_group_blk,
                            show_grid=_show_grid,
                            show_diagonal=_show_diag,
                        )
                        st.markdown(_svg, unsafe_allow_html=True)


                    # 線一覧テーブル
                    import pandas as pd
                    _all_lines = _ld["lines"]
                    if _orient_filter == "水平のみ（幅・長さ）":
                        _disp_lines = [l for l in _all_lines if l["orientation"] == "horizontal"]
                    elif _orient_filter == "垂直のみ（高さ）":
                        _disp_lines = [l for l in _all_lines if l["orientation"] == "vertical"]
                    else:
                        _disp_lines = _all_lines

                    # 長さ別ヒストグラム的サマリー（常に表示）
                    _buckets = {"8m以上":0,"3〜8m":0,"1〜3m":0,"0.5〜1m":0,"0.5m未満":0}
                    for l in _all_lines:
                        m = l["real_m"]
                        if m >= 8: _buckets["8m以上"] += 1
                        elif m >= 3: _buckets["3〜8m"] += 1
                        elif m >= 1: _buckets["1〜3m"] += 1
                        elif m >= 0.5: _buckets["0.5〜1m"] += 1
                        else: _buckets["0.5m未満"] += 1
                    st.markdown("**📊 長さ分布**")
                    _bc1, _bc2, _bc3, _bc4, _bc5 = st.columns(5)
                    _bc1.metric("8m以上", f"{_buckets['8m以上']}本")
                    _bc2.metric("3〜8m",  f"{_buckets['3〜8m']}本")
                    _bc3.metric("1〜3m",  f"{_buckets['1〜3m']}本")
                    _bc4.metric("0.5〜1m",f"{_buckets['0.5〜1m']}本")
                    _bc5.metric("0.5m未満",f"{_buckets['0.5m未満']}本")

                    if _disp_lines:
                        # ── ブロック別テーブル（左）＋ハイライト画像（右） ──
                        import math as _mth
                        import pandas as _pd_ln
                        from collections import defaultdict as _ddict
                        _orient_abbr = {"horizontal":"水平↔","vertical":"垂直↕","diagonal":"斜め↗"}
                        _blk_groups = _ddict(list)
                        for _ll in _disp_lines:
                            _blk_groups[str(_ll.get("id","?"))[0]].append(_ll)
                        if "_sel_line_id" not in st.session_state:
                            st.session_state["_sel_line_id"] = None
                        if "_disabled_lines" not in st.session_state:
                            st.session_state["_disabled_lines"] = set()
                        _disabled = st.session_state["_disabled_lines"]
                        _col_tbl, _col_hl = st.columns([1, 1.4])
                        with _col_tbl:
                            st.markdown(f"**📋 線一覧（{len(_disp_lines)}本）— 行クリックで右に表示**")
                            _sorted_blk = sorted(_blk_groups.keys())
                            for _blk_letter in _sorted_blk:
                                _blk_lines = _blk_groups[_blk_letter]
                                _is_first = (_blk_letter == _sorted_blk[0])
                                with st.expander(f"ブロック {_blk_letter}（{len(_blk_lines)}本）", expanded=_is_first):
                                    _blk_rows = [
                                        {
                                            "✓使用": l["id"] not in _disabled,
                                            "線名": l["id"],
                                            "実寸(m)": l["real_m"],
                                            "向き": _orient_abbr.get(l["orientation"], ""),
                                            "角度(°)": l["angle_deg"],
                                        }
                                        for l in _blk_lines
                                    ]
                                    _ev = st.dataframe(
                                        _pd_ln.DataFrame(_blk_rows),
                                        hide_index=True,
                                        use_container_width=True,
                                        height=min(200, 38 + 35 * len(_blk_lines)),
                                        on_select="rerun",
                                        selection_mode="single-row",
                                        key=f"tbl_blk_{_blk_letter}",
                                    )
                                    _sr = _ev.selection.rows if hasattr(_ev, "selection") else []
                                    if _sr:
                                        _clicked_id = _blk_lines[_sr[0]].get("id")
                                        st.session_state["_sel_line_id"] = _clicked_id
                                        _tog1, _tog2 = st.columns(2)
                                        if _clicked_id in _disabled:
                                            if _tog1.button(f"✅ {_clicked_id} を有効化", key=f"en_{_blk_letter}_{_sr[0]}"):
                                                _disabled.discard(_clicked_id)
                                                st.rerun()
                                        else:
                                            if _tog2.button(f"🚫 {_clicked_id} を無効化", key=f"dis_{_blk_letter}_{_sr[0]}"):
                                                _disabled.add(_clicked_id)
                                                st.rerun()
                        with _col_hl:
                            _sel_id_now = st.session_state.get("_sel_line_id")
                            _sel_obj = next((l for l in _disp_lines if str(l.get("id")) == str(_sel_id_now)), None) if _sel_id_now else None
                            if _sel_obj:
                                from core.line_detector import highlight_line as _hl_fn2
                                _hl_bytes2 = _hl_fn2(_ld["annotated_bytes"], _sel_obj)
                                st.image(_hl_bytes2, use_container_width=True,
                                         caption=f"🔴 {_sel_id_now}: {_sel_obj['real_m']:.3f}m  {_orient_abbr.get(_sel_obj['orientation'],'')}")
                            else:
                                st.info("👈 左の表の行をクリックすると、ここに図面上でハイライト表示されます")
                                st.image(_ld["annotated_bytes"], use_container_width=True, caption="図面（選択前）")
                        # ── 基準長さ校正 ────────────────────────────────────
                        st.markdown("---")
                        with st.expander("📐 基準長さ校正（1辺の実寸がわかれば全線を再計算）", expanded=False):
                            st.caption("図面上の任意の線を1本選び、実際の長さ(m)を入力すると縮尺を自動補正して全線を再計算します")
                            _ref_id = st.selectbox(
                                "基準にする線",
                                [l["id"] for l in _ld["lines"]],
                                key="ref_line_sel"
                            )
                            _ref_line = next((l for l in _ld["lines"] if l["id"] == _ref_id), None)
                            if _ref_line:
                                st.info(f"選択中: **{_ref_id}** — 現在の計算値 **{_ref_line['real_m']:.3f} m**")
                                _ref_actual = st.number_input("この線の実際の長さ（m）", min_value=0.1, max_value=100.0, value=float(round(_ref_line["real_m"],1)), step=0.1, key="ref_actual_m")
                                if st.button("🔄 全線を再計算", type="primary", key="btn_recalc_scale"):
                                    _corr = _ref_actual / _ref_line["real_m"] if _ref_line["real_m"] > 0 else 1.0
                                    for _ln in _ld["lines"]:
                                        _ln["real_m"] = round(_ln["real_m"] * _corr, 3)
                                    st.session_state["line_detect_result"]["scale_m_per_px"] = round(_ld["scale_m_per_px"] * _corr, 6)
                                    st.success(f"補正係数 {_corr:.4f} を適用しました。全線の実寸を再計算しました。")
                                    st.rerun()
                        # ── AI 3D変換 ──────────────────────────────────────
                        st.markdown("---")
                        with st.expander("🏗 AI 3D変換（Beta）— 2段階パイプラインで精密3Dモデルを生成", expanded=False):
                            _3d_mode_tab, _3d_result_tab = st.tabs(["⚙️ 解析方法", "🏠 3D表示"])

                            with _3d_mode_tab:
                                st.markdown("**方法を選んで実行してください**")
                                _m1, _m2, _m3, _m4 = st.columns(4)

                                with _m1:
                                    st.markdown("##### 🔮 方法1: 図面直接解析")
                                    _m1_ann = st.session_state.get("drawing_annotations") or []
                                    if _m1_ann:
                                        st.caption("✅ 図面の寸法データ取得済み。屋根タイプを選んで実行。")
                                        _m1_roof = st.selectbox("屋根タイプ", ["寄棟", "切妻", "片流れ", "陸屋根"], key="m1_roof_sel")
                                    else:
                                        st.caption("図面画像をそのままGPT-4oに送信。速い（15〜30秒）が精度は中程度。")
                                    if st.button("🔮 直接解析を実行", key="btn_3d_direct"):
                                        if _m1_ann:
                                            # DrawingAnalyzerの抽出値を直接使用（GPTコール不要）
                                            try:
                                                from core.building_3d_generator import build_3d_from_annotations
                                                _m1_roof_sel = st.session_state.get("m1_roof_sel", "寄棟")
                                                _faces1 = st.session_state.get("drawing_data", {}).get("faces")
                                                # floor_footprints優先順: 平面図PDF > 図面解析（DrawingAnalyzer直接返却）> 空
                                                _dd_fps1 = (st.session_state.get("drawing_data") or {}).get("floor_footprints") or []
                                                _fp1 = (st.session_state.get("floor_plan_data") or {}).get("floor_footprints") or _dd_fps1
                                                _bldg_data = build_3d_from_annotations(_m1_ann, roof_type=_m1_roof_sel, faces=_faces1, floor_footprints=_fp1)
                                                if "error" in _bldg_data:
                                                    st.error(f"解析エラー: {_bldg_data['error']}")
                                                else:
                                                    st.session_state["building_3d_data"] = _bldg_data
                                                    st.session_state["_3d_trace_png"] = None
                                                    st.session_state["_3d_gpt_raw"] = ""
                                                    st.success(f"✅ 解析完了 [寸法値使用]: {_bldg_data.get('note','')}")
                                            except Exception as _e3d:
                                                st.error(f"エラー: {_e3d}")
                                        else:
                                            with st.spinner("GPT-4oが図面を直接解析中…"):
                                                try:
                                                    from core.building_3d_generator import analyze_drawing_3d, generate_building_3d_html
                                                    from modules.llm_client import _get_api_key
                                                    _api_key = _get_api_key()
                                                    _bldg_data = analyze_drawing_3d(drawing_raw_bytes, _api_key)
                                                    # 常にGPTの生応答をデバッグタブに保存
                                                    st.session_state["_3d_gpt_raw"] = _bldg_data.get("_raw_gpt_response", "")
                                                    if "error" in _bldg_data:
                                                        st.error(f"解析エラー: {_bldg_data['error']}")
                                                        st.caption("💡 デバッグタブで GPT生応答を確認できます")
                                                    else:
                                                        st.session_state["building_3d_data"] = _bldg_data
                                                        st.session_state["_3d_trace_png"] = None
                                                        _pipeline_badge = " [直接解析]" if _bldg_data.get("_pipeline") == "direct_fallback" else ""
                                                        st.success(f"✅ 解析完了{_pipeline_badge}: {_bldg_data.get('building_type','')} / {_bldg_data.get('note','')}")
                                                except Exception as _e3d:
                                                    st.error(f"エラー: {_e3d}")

                                with _m2:
                                    st.markdown("##### 🔬 方法2: 2段階精密解析（推奨）")
                                    st.caption("**Stage1**: 線検出データからクリーントレースPNG生成  \n**Stage2**: トレース画像＋実寸データをGPTに送信 → 精密な建物構造を取得")
                                    if not st.session_state.get("line_detect_result"):
                                        st.warning("先に「🔍 線を検出する」を実行してください")
                                    else:
                                        if st.button("🔬 精密解析を実行", type="primary", key="btn_3d_trace"):
                                            _ld2 = st.session_state["line_detect_result"]
                                            with st.spinner("Stage1: クリーントレースPNG生成中…"):
                                                try:
                                                    from core.trace_analyzer import generate_clean_trace_png, analyze_trace_for_building
                                                    from modules.llm_client import _get_api_key
                                                    _trace_png = generate_clean_trace_png(
                                                        lines=_ld2["lines"],
                                                        scale_m_per_px=_ld2["scale_m_per_px"],
                                                        canvas_w=900,
                                                        min_length_m=1.5,
                                                        show_grid=True,
                                                    )
                                                    st.session_state["_3d_trace_png"] = _trace_png
                                                    _filtered_cnt = len([l for l in _ld2["lines"] if l["real_m"] >= 1.5])
                                                    st.success(f"Stage1完了: クリーントレース生成（構造線{_filtered_cnt}本 / 総検出{len(_ld2['lines'])}本）")
                                                except Exception as _e_s1:
                                                    st.error(f"Stage1エラー: {_e_s1}")
                                                    _trace_png = None

                                            if st.session_state.get("_3d_trace_png"):
                                                with st.spinner("Stage2: GPT-4oがトレースから建物要素を精密解析中…（20〜40秒）"):
                                                    try:
                                                        _api_key = _get_api_key()
                                                        _bldg_data = analyze_trace_for_building(
                                                            clean_png_bytes=st.session_state["_3d_trace_png"],
                                                            lines=_ld2["lines"],
                                                            scale_m_per_px=_ld2["scale_m_per_px"],
                                                            api_key=_api_key,
                                                        )
                                                        if "error" in _bldg_data:
                                                            st.error(f"Stage2エラー: {_bldg_data['error']}")
                                                        else:
                                                            # DrawingAnalyzerの寸法でGPT推定値を補正
                                                            _ann2 = st.session_state.get("drawing_annotations") or []
                                                            if _ann2:
                                                                from core.building_3d_generator import build_3d_from_annotations
                                                                _faces2 = st.session_state.get("drawing_data", {}).get("faces")
                                                                _trace_fps2 = _bldg_data.get("floor_footprints") or []
                                                                _fp2 = (st.session_state.get("floor_plan_data") or {}).get("floor_footprints") or _trace_fps2
                                                                _ann_data = build_3d_from_annotations(_ann2, faces=_faces2, floor_footprints=_fp2)
                                                                if "error" not in _ann_data:
                                                                    _dim_fix = _ann_data["dimensions"]
                                                                    # ★補正前の幅を保存（openingsスケーリング用）
                                                                    _old_w = float((_bldg_data.get("dimensions") or {}).get("total_width") or 1)
                                                                    _new_w = float(_dim_fix.get("total_width") or 1)
                                                                    _scale_r = _new_w / _old_w if _old_w > 0.01 else 1.0
                                                                    # 寸法補正（幅・奥行・軒高・棟高）
                                                                    _bldg_data.setdefault("dimensions", {}).update(_dim_fix)
                                                                    _bldg_data.setdefault("roof", {}).update({
                                                                        "eave_height":  _dim_fix["eave_height"],
                                                                        "ridge_height": _dim_fix["ridge_height"],
                                                                    })
                                                                    # ★GPT壁はwrong寸法のためクリア→JSが補正BW/BD/EHで4面自動生成
                                                                    _bldg_data["walls"] = []
                                                                    # ★屋根タイプをannotationsから上書き（traceGPTは屋根タイプを誤判定することが多い）
                                                                    if _ann_data.get("roof", {}).get("type"):
                                                                        _bldg_data.setdefault("roof", {})["type"] = _ann_data["roof"]["type"]
                                                                    # ★openings x座標を新幅にスケーリング補正
                                                                    for _op in (_bldg_data.get("openings") or []):
                                                                        _op["x"] = round(float(_op.get("x") or 0) * _scale_r, 2)
                                                                    _bldg_data["note"] = f"{_bldg_data.get('note','')} ／ 寸法補正: {_ann_data['note']}"
                                                                    _bldg_data["_pipeline"] = "trace_v2+annotations"
                                                                    # floor_footprints: 図面解析(DrawingAnalyzer直接) > 平面図PDF > トレース > 空 の優先順
                                                                    _dd_fps2 = (st.session_state.get("drawing_data") or {}).get("floor_footprints") or []
                                                                    _ann_fps2 = _ann_data.get("floor_footprints") or []
                                                                    _best_fps = _ann_fps2 or _dd_fps2 or []
                                                                    _bldg_data["floor_footprints"] = _best_fps
                                                                    # ★traceのfloor_footprints使用時: floor_heightを実際の軒高に比例スケール
                                                                    if _bldg_data["floor_footprints"] and not _ann_fps2:
                                                                        _total_fh = sum(fp.get("floor_height") or 3.0 for fp in _bldg_data["floor_footprints"])
                                                                        _target_eh = _dim_fix.get("eave_height") or 6.0
                                                                        if _total_fh > 0.1:
                                                                            _scale_fh = _target_eh / _total_fh
                                                                            for _fp in _bldg_data["floor_footprints"]:
                                                                                _fp["floor_height"] = round((_fp.get("floor_height") or 3.0) * _scale_fh, 2)
                                                                    # openings: faces由来（face付き・全方位）で上書き。トレースのopeningsはface未設定で全部南壁になるため
                                                                    if _ann_data.get("openings"):
                                                                        _bldg_data["openings"] = _ann_data["openings"]
                                                            st.session_state["building_3d_data"] = _bldg_data
                                                            st.session_state["_3d_gpt_raw"] = _bldg_data.get("_raw_gpt_response", "")
                                                            _corr_badge = " [寸法補正済]" if _ann2 else ""
                                                            st.success(f"✅ Stage2完了{_corr_badge}: {_bldg_data.get('building_type','')} / {_bldg_data.get('note','')[:80]}")
                                                    except Exception as _e_s2:
                                                        st.error(f"Stage2エラー: {_e_s2}")

                                # Stage1のクリーントレース表示
                                if st.session_state.get("_3d_trace_png"):
                                    st.markdown("**Stage1 出力: クリーントレースPNG（これをGPTに送信）**")
                                    st.image(st.session_state["_3d_trace_png"], use_container_width=True)

                                with _m3:
                                    st.markdown("##### 🧩 方法3: 多段階精密解析 v2")
                                    st.caption(
                                        "**2a**: 建物外形ratio → **2b**: 寸法数値読取 → **2c**: 1F/2F境界 → "
                                        "**2d**: セットバック検出 → **3a-e**: 階ごとに窓数→位置 → **4**: 屋根判定 → **5**: 3D組み立て  \n"
                                        "⚠️ 各面を個別クロップして解析。annotationsによる上書きなし。"
                                    )
                                    _ms2_orig = st.session_state.get("drawing_page1_raw")
                                    if not _ms2_orig:
                                        st.warning("先にSTEP2で図面を解析してください")
                                    else:
                                        if st.button("🧩 多段階v2を実行", type="primary", key="btn_3d_multi2"):
                                            from core.trace_analyzer import (
                                                ms_stage1_layout, ms_stage2a_bounds, ms_stage2b_dims,
                                                ms_stage2c_floor_line, ms_stage2d_setback,
                                                ms_stage2d_depth_setback,
                                                ms_stage3_count_openings, ms_stage3_opening_positions,
                                                ms_stage4_roof_type, ms_stage5_assemble, _crop_r,
                                            )
                                            from modules.llm_client import _get_api_key
                                            _msv2_key = _get_api_key()
                                            _face_lmap = {"south":"南立面図","north":"北立面図","east":"東立面図","west":"西立面図"}

                                            # ── Stage 1: 各面の位置特定 ──
                                            with st.spinner("Stage 1: 各立面図（南/北/東/西）の位置を特定中…"):
                                                try:
                                                    _msv2_layout = ms_stage1_layout(_ms2_orig, _msv2_key)
                                                    _msv2_valid = {k: v for k, v in _msv2_layout.items()
                                                                   if k in ("south","north","east","west") and isinstance(v, dict)}
                                                    st.success(f"Stage1完了: {len(_msv2_valid)}面検出 ({', '.join(_msv2_valid.keys())})")
                                                except Exception as _e:
                                                    st.error(f"Stage1失敗: {_e}")
                                                    _msv2_valid = {}

                                            if not _msv2_valid:
                                                st.stop()

                                            _msv2_bounds      = {}
                                            _msv2_dims        = {}
                                            _msv2_floor_lines = {}
                                            _msv2_setbacks    = {}
                                            _msv2_openings    = {}

                                            for _msv2_fk, _msv2_freg in _msv2_valid.items():
                                                _fl = _face_lmap.get(_msv2_fk, _msv2_fk)
                                                _fc = _crop_r(_ms2_orig, _msv2_freg["x1"], _msv2_freg["y1"],
                                                              _msv2_freg["x2"], _msv2_freg["y2"])

                                                # Stage 2a: 建物外形ratio
                                                with st.spinner(f"Stage 2a [{_fl}]: 建物外形を特定中…"):
                                                    try:
                                                        _msv2_bounds[_msv2_fk] = ms_stage2a_bounds(_fc, _fl, _msv2_key)
                                                        _b = _msv2_bounds[_msv2_fk]
                                                        st.success(f"  {_fl}: left={_b.get('left'):.2f} right={_b.get('right'):.2f} ground={_b.get('ground'):.2f} eave={_b.get('eave'):.2f}")
                                                    except Exception as _e:
                                                        st.warning(f"  {_fl} 2a失敗: {_e}")
                                                        _msv2_bounds[_msv2_fk] = {}

                                                # Stage 2b: 寸法数値読取
                                                with st.spinner(f"Stage 2b [{_fl}]: 寸法数値を読み取り中…"):
                                                    try:
                                                        _is_side = _msv2_fk in ("east", "west")
                                                        _msv2_dims[_msv2_fk] = ms_stage2b_dims(_fc, _fl, _msv2_key, is_side_view=_is_side)
                                                        _d = _msv2_dims[_msv2_fk]
                                                        st.success(f"  {_fl}: 幅={_d.get('width_m')}m / 軒高={_d.get('eave_height_m')}m / 棟高={_d.get('ridge_height_m')}m")
                                                    except Exception as _e:
                                                        st.warning(f"  {_fl} 2b失敗: {_e}")
                                                        _msv2_dims[_msv2_fk] = {}

                                                # Stage 2c: 1F/2F境界線
                                                with st.spinner(f"Stage 2c [{_fl}]: 1F/2F境界線を検出中…"):
                                                    try:
                                                        _msv2_floor_lines[_msv2_fk] = ms_stage2c_floor_line(_fc, _fl, _msv2_key)
                                                        _fl2 = _msv2_floor_lines[_msv2_fk]
                                                        if _fl2.get("has_second_floor"):
                                                            st.success(f"  {_fl}: 2階あり / 境界y={_fl2.get('floor2_start_y_ratio'):.3f}")
                                                        else:
                                                            st.success(f"  {_fl}: 平屋 or 1階建て")
                                                    except Exception as _e:
                                                        st.warning(f"  {_fl} 2c失敗: {_e}")
                                                        _msv2_floor_lines[_msv2_fk] = {}

                                                # Stage 2d: セットバック検出
                                                with st.spinner(f"Stage 2d [{_fl}]: セットバック（凸凹）を検出中…"):
                                                    try:
                                                        _msv2_setbacks[_msv2_fk] = ms_stage2d_setback(_fc, _fl, _msv2_key)
                                                        _sb = _msv2_setbacks[_msv2_fk]
                                                        if _sb.get("has_setback"):
                                                            st.success(f"  {_fl}: セットバックあり / 1F={_sb.get('f1_left_ratio'):.2f}〜{_sb.get('f1_right_ratio'):.2f} / 2F={_sb.get('f2_left_ratio'):.2f}〜{_sb.get('f2_right_ratio'):.2f}")
                                                        else:
                                                            st.success(f"  {_fl}: セットバックなし（長方形）")
                                                    except Exception as _e:
                                                        st.warning(f"  {_fl} 2d失敗: {_e}")
                                                        _msv2_setbacks[_msv2_fk] = {}

                                                # Stage 2d-depth: 奥行きセットバック（東/西面のみ）
                                                if _msv2_fk in ("east", "west"):
                                                    with st.spinner(f"Stage 2d-depth [{_fl}]: 奥行き方向セットバックを検出中…"):
                                                        try:
                                                            _msv2_dsb = ms_stage2d_depth_setback(_fc, _fl, _msv2_key)
                                                            _depth_key = f"{_msv2_fk}_depth"
                                                            _msv2_setbacks[_depth_key] = _msv2_dsb
                                                            if _msv2_dsb.get("has_depth_setback"):
                                                                st.success(f"  {_fl}: 奥行きセットバックあり / 2F奥行き={_msv2_dsb.get('f2_depth_ratio'):.2f}×1F")
                                                            else:
                                                                st.success(f"  {_fl}: 奥行きセットバックなし")
                                                        except Exception as _e:
                                                            st.warning(f"  {_fl} 2d-depth失敗: {_e}")

                                                # Stage 3: 各階ごとに窓・ドア検出
                                                _msv2_openings[_msv2_fk] = {}
                                                _has2f = (_msv2_floor_lines.get(_msv2_fk) or {}).get("has_second_floor", False)
                                                _floors_to_check = [1, 2] if _has2f else [1]
                                                _msv2_w = float((_msv2_dims.get(_msv2_fk) or {}).get("width_m") or 10.0)
                                                _msv2_eh = float((_msv2_dims.get(_msv2_fk) or {}).get("eave_height_m") or 6.0)

                                                for _fn in _floors_to_check:
                                                    _fh = _msv2_eh / len(_floors_to_check)

                                                    # Stage 3a/3c: 窓数カウント
                                                    with st.spinner(f"Stage 3 [{_fl}] {_fn}F: 窓・ドア数を数え中…"):
                                                        try:
                                                            _cnt = ms_stage3_count_openings(_fc, _fl, _fn, _msv2_key)
                                                            _wcnt = int(_cnt.get("window_count") or 0)
                                                            _dcnt = int(_cnt.get("door_count") or 0)
                                                            st.success(f"  {_fl} {_fn}F: 窓{_wcnt}個 / ドア{_dcnt}個")
                                                        except Exception as _e:
                                                            st.warning(f"  {_fl} {_fn}F カウント失敗: {_e}")
                                                            _wcnt = _dcnt = 0

                                                    # Stage 3b/3d: 窓の位置
                                                    if _wcnt > 0:
                                                        with st.spinner(f"Stage 3 [{_fl}] {_fn}F: {_wcnt}個の窓の位置を取得中…"):
                                                            try:
                                                                _wops = ms_stage3_opening_positions(
                                                                    _fc, _fl, _fn, "窓", _wcnt, _msv2_w, _fh, _msv2_key)
                                                                _msv2_openings[_msv2_fk][f"{_fn}F_窓"] = _wops
                                                                st.success(f"  {_fl} {_fn}F 窓: {len(_wops)}個の位置取得")
                                                            except Exception as _e:
                                                                st.warning(f"  窓位置取得失敗: {_e}")

                                                    # Stage 3e: ドアの位置
                                                    if _dcnt > 0:
                                                        with st.spinner(f"Stage 3 [{_fl}] {_fn}F: {_dcnt}個のドアの位置を取得中…"):
                                                            try:
                                                                _dops = ms_stage3_opening_positions(
                                                                    _fc, _fl, _fn, "ドア", _dcnt, _msv2_w, _fh, _msv2_key)
                                                                _msv2_openings[_msv2_fk][f"{_fn}F_ドア"] = _dops
                                                                st.success(f"  {_fl} {_fn}F ドア: {len(_dops)}個の位置取得")
                                                            except Exception as _e:
                                                                st.warning(f"  ドア位置取得失敗: {_e}")

                                            # Stage 4: 屋根タイプ
                                            _msv2_roof = "寄棟"
                                            if "south" in _msv2_valid:
                                                with st.spinner("Stage 4: 屋根タイプを判定中…"):
                                                    try:
                                                        _sc = _crop_r(_ms2_orig, _msv2_valid["south"]["x1"], _msv2_valid["south"]["y1"],
                                                                      _msv2_valid["south"]["x2"], _msv2_valid["south"]["y2"])
                                                        _msv2_roof = ms_stage4_roof_type(_sc, _msv2_key)
                                                        st.success(f"Stage4完了: 屋根タイプ={_msv2_roof}")
                                                    except Exception as _e:
                                                        st.warning(f"Stage4失敗: {_e}")

                                            # Stage 5: 3Dデータ組み立て
                                            with st.spinner("Stage 5: 全データを3Dデータに統合中…"):
                                                _msv2_bldg = ms_stage5_assemble(
                                                    layout        = _msv2_layout,
                                                    face_bounds   = _msv2_bounds,
                                                    face_dims     = _msv2_dims,
                                                    face_floor_lines = _msv2_floor_lines,
                                                    face_setbacks = _msv2_setbacks,
                                                    face_openings_raw = _msv2_openings,
                                                    roof_type     = _msv2_roof,
                                                )
                                                # DrawingAnalyzerの寸法を補正（openings/footprintsは多段階優先）
                                                _msv2_ann = st.session_state.get("drawing_annotations") or []
                                                _msv2_dd  = st.session_state.get("drawing_data") or {}
                                                if _msv2_ann:
                                                    from core.building_3d_generator import build_3d_from_annotations
                                                    _msv2_ann_fps = (st.session_state.get("floor_plan_data") or {}).get("floor_footprints") or []
                                                    _msv2_dd_fps  = _msv2_dd.get("floor_footprints") or []
                                                    _msv2_ann_data = build_3d_from_annotations(_msv2_ann, floor_footprints=_msv2_ann_fps or _msv2_dd_fps)
                                                    if "error" not in _msv2_ann_data:
                                                        _msv2_bldg["dimensions"].update(_msv2_ann_data["dimensions"])
                                                        _msv2_bldg["roof"]["eave_height"]  = _msv2_ann_data["dimensions"]["eave_height"]
                                                        _msv2_bldg["roof"]["ridge_height"] = _msv2_ann_data["dimensions"]["ridge_height"]
                                                        # ★奥行きをDrawingAnalyzerから優先使用（GPT誤読対策）
                                                        _da_depth = _msv2_ann_data["dimensions"].get("total_depth")
                                                        if _da_depth and _da_depth > 0:
                                                            _msv2_bldg["dimensions"]["total_depth"] = _da_depth
                                                            # floor_footprintsの奥行きも更新
                                                            for _fp in (_msv2_bldg.get("floor_footprints") or []):
                                                                if _fp.get("floor") == 1:
                                                                    _fp["depth"] = _da_depth
                                                                elif _fp.get("floor") == 2 and _fp.get("depth"):
                                                                    # 2Fは比率を維持
                                                                    _ratio = _fp["depth"] / _msv2_bldg["dimensions"].get("total_depth", _da_depth)
                                                                    _fp["depth"] = round(_da_depth * _ratio, 2)
                                                        # floor_footprints: 多段階で検出した場合は維持、なければAnnotationsから
                                                        if not _msv2_bldg["floor_footprints"]:
                                                            _msv2_bldg["floor_footprints"] = _msv2_ann_data.get("floor_footprints") or []
                                                        _msv2_bldg["note"] += " ／ 寸法補正済"
                                                        _msv2_bldg["_pipeline"] = "multistage_v2+annotations"
                                                st.session_state["building_3d_data"] = _msv2_bldg
                                                st.success(f"✅ Stage5完了: {_msv2_bldg['note'][:120]}")


                                with _m4:
                                    st.markdown("##### 📐 方法4: 線解析→3D（推奨）")
                                    st.caption("検出線の実寸座標を直接3Dに使用。GPTは面ラベルと屋根タイプ判定のみ。")
                                    _m4_orig = st.session_state.get("drawing_page1_raw")
                                    if not _m4_orig:
                                        st.warning("先にSTEP2で図面を解析してください")
                                    else:
                                        # 縮尺設定
                                        _m4_scale = st.number_input("縮尺分母 (S=1/○○)", min_value=50, max_value=500,
                                                                     value=100, step=50, key="m4_scale")
                                        # 面割当: 自動 or 手動
                                        _m4_auto = st.checkbox("面ラベルを自動検出（GPT）", value=True, key="m4_auto")
                                        if not _m4_auto:
                                            st.caption("各象限に表示されている立面図を選択してください")
                                            _q1, _q2 = st.columns(2)
                                            _face_opts = ["south（南）","north（北）","east（東）","west（西）","skip"]
                                            _tl = _q1.selectbox("左上", _face_opts, index=3, key="m4_tl")
                                            _tr = _q2.selectbox("右上", _face_opts, index=0, key="m4_tr")
                                            _bl = _q1.selectbox("左下", _face_opts, index=1, key="m4_bl")
                                            _br = _q2.selectbox("右下", _face_opts, index=2, key="m4_br")
                                            def _parse_face(s): return s.split("（")[0]
                                            _m4_manual_regions = {}
                                            for quad, sel, coords in [
                                                ("top_left",    _tl, (0.0,0.0,0.5,0.5)),
                                                ("top_right",   _tr, (0.5,0.0,1.0,0.5)),
                                                ("bottom_left", _bl, (0.0,0.5,0.5,1.0)),
                                                ("bottom_right",_br, (0.5,0.5,1.0,1.0)),
                                            ]:
                                                f = _parse_face(sel)
                                                if f in ("south","north","east","west"):
                                                    _m4_manual_regions[f] = coords
                                        else:
                                            _m4_manual_regions = None

                                        if st.button("📐 線解析→3D を実行", type="primary", key="btn_m4"):
                                            from modules.llm_client import _get_api_key
                                            from core.line_3d_builder import build_3d_from_line_analysis
                                            _m4_key = _get_api_key()
                                            _m4_ann_dims = None
                                            _m4_ann = st.session_state.get("drawing_annotations") or []
                                            if _m4_ann:
                                                from core.building_3d_generator import build_3d_from_annotations
                                                _m4_tmp = build_3d_from_annotations(_m4_ann)
                                                if "error" not in _m4_tmp:
                                                    _m4_ann_dims = _m4_tmp.get("dimensions")
                                            # ステージ別進捗UI
                                            _m4_status_area = st.empty()
                                            _m4_log_area    = st.empty()
                                            _m4_all_logs    = []
                                            _stage_icons = {"A":"🏷️","B":"📏","C":"📐","D":"🏠","E":"🧩"}
                                            def _m4_progress(stage, msg):
                                                icon = _stage_icons.get(stage, "▶️")
                                                _m4_all_logs.append(f"{icon} Stage {stage}: {msg}")
                                                _m4_status_area.info(f"{icon} **Stage {stage}**: {msg}")
                                                _m4_log_area.caption(" → ".join(_m4_all_logs[-3:]))
                                            # DrawingAnalyzerのfacesデータを取得（窓検出に使用）
                                            # DrawingAnalyzerのfacesデータ取得（なければ自動実行）
                                            _m4_faces_data = None
                                            _dd = st.session_state.get("drawing_data") or {}
                                            if isinstance(_dd, dict) and _dd.get("faces"):
                                                _m4_faces_data = _dd["faces"]
                                                _cb_has_openings = any(
                                                    bool(v.get("openings")) if isinstance(v, dict) else False
                                                    for v in _m4_faces_data.values()
                                                )
                                            else:
                                                _cb_has_openings = False
                                            # facesがない or openingsが全面空の場合→DrawingAnalyzerを自動実行
                                            if not _cb_has_openings and _m4_orig:
                                                _m4_status_area.info("🔍 DrawingAnalyzerを自動実行中（窓データ取得）…")
                                                try:
                                                    from core.drawing_analyzer import DrawingAnalyzer
                                                    _da = DrawingAnalyzer(api_key=_m4_key)
                                                    _da_result = _da.analyze(_m4_orig)
                                                    if _da_result and _da_result.get("faces"):
                                                        _m4_faces_data = _da_result["faces"]
                                                        st.session_state["drawing_data"] = _da_result
                                                        _m4_status_area.info(f"✅ DrawingAnalyzer完了: faces={list(_m4_faces_data.keys())}")
                                                    if not _m4_ann_dims and _da_result:
                                                        from core.building_3d_generator import build_3d_from_annotations
                                                        _da_ann = _da_result.get("annotations") or []
                                                        if _da_ann:
                                                            _da_tmp = build_3d_from_annotations(_da_ann)
                                                            if "error" not in _da_tmp:
                                                                _m4_ann_dims = _da_tmp.get("dimensions")
                                                except Exception as _da_e:
                                                    _m4_status_area.warning(f"⚠️ DrawingAnalyzer自動実行失敗: {_da_e}")
                                            try:
                                                _m4_result = build_3d_from_line_analysis(
                                                    img_bytes        = _m4_orig,
                                                    scale            = _m4_scale,
                                                    api_key          = _m4_key,
                                                    face_regions     = _m4_manual_regions,
                                                    annotations_dims = _m4_ann_dims,
                                                    faces_data       = _m4_faces_data,
                                                    progress_callback= _m4_progress,
                                                )
                                                _m4_status_area.empty()
                                                _m4_log_area.empty()
                                                st.session_state["building_3d_data"] = _m4_result
                                                st.session_state["_m4_face_regions"] = _m4_result.get("_face_regions")
                                                st.success(f"✅ 完了: {_m4_result.get('note','')[:120]}")
                                                # 面ごとの結果サマリ
                                                _m4_fg = _m4_result.get("_face_geometries", {})
                                                if _m4_fg:
                                                    with st.expander("🔍 各面の検出結果"):
                                                        for _fn, _fg in _m4_fg.items():
                                                            if isinstance(_fg, dict) and "error" not in _fg:
                                                                st.caption(f"**{_fn}**: 幅{_fg.get('width_m')}m / 高{_fg.get('height_m')}m / 窓{len(_fg.get('windows',[]))}個")
                                                            elif isinstance(_fg, dict):
                                                                st.caption(f"**{_fn}**: {_fg.get('error')}")
                                                with st.expander("📋 全解析ログ"):
                                                    for _log in _m4_all_logs:
                                                        st.caption(_log)
                                            except Exception as _m4_e:
                                                _m4_status_area.empty()
                                                st.error(f"線解析失敗: {_m4_e}")
                                                import traceback
                                                st.code(traceback.format_exc())

                            with _3d_result_tab:
                                _bdata = st.session_state.get("building_3d_data")
                                if _bdata and "error" not in _bdata:
                                    _pipe = _bdata.get("_pipeline", "直接解析")
                                    _pipe_label = {
                                        "trace_v2": "🔬 2段階精密解析",
                                        "trace_v2+annotations": "🔬 精密解析+寸法補正",
                                        "annotations_v1": "📐 寸法値直接使用",
                                        "direct_fallback": "🔮 GPT直接解析",
                                        "multistage_v1": "🧩 多段階精密解析",
                                        "multistage_v1+annotations": "🧩 多段階解析+寸法補正",
                                        "multistage_v2": "🧩 多段階v2",
                                        "multistage_v2+annotations": "🧩 多段階v2+寸法補正",
                                        "line_analysis_v1": "📐 線解析→3D",
                                    }.get(_pipe, "🔮 直接解析")
                                    st.caption(f"使用パイプライン: {_pipe_label} | {_bdata.get('note','')[:100]}")
                                    from core.building_3d_generator import generate_building_3d_html
                                    _html3d = generate_building_3d_html(_bdata, canvas_height=600)
                                    import streamlit.components.v1 as _comp3d
                                    _comp3d.html(_html3d, height=620, scrolling=False)

                                    # ── 3D手入力補正フォーム ────────────────────────────
                                    with st.expander("🔧 3D寸法を手動補正（解析が合っていない場合）"):
                                        _dim_cur = _bdata.get("dimensions") or {}
                                        _fp_cur  = _bdata.get("floor_footprints") or []
                                        _c1, _c2, _c3 = st.columns(3)
                                        _fix_w   = _c1.number_input("幅 (m)",     min_value=2.0, max_value=40.0, value=float(_dim_cur.get("total_width",  10.0)), step=0.5, key="fix_bw")
                                        _fix_d   = _c2.number_input("奥行き (m)", min_value=2.0, max_value=40.0, value=float(_dim_cur.get("total_depth",   8.0)), step=0.5, key="fix_bd")
                                        _fix_oh  = _c3.number_input("軒の出 (m)", min_value=0.2, max_value=1.5,  value=float(_bdata.get("eave_overhang",    0.6)), step=0.1, key="fix_oh")
                                        _c4, _c5 = st.columns(2)
                                        _fix_eh  = _c4.number_input("軒高 (m)",   min_value=2.0, max_value=12.0, value=float(_dim_cur.get("eave_height",   5.5)), step=0.1, key="fix_eh")
                                        _fix_rh  = _c5.number_input("棟高 (m)",   min_value=2.5, max_value=14.0, value=float(_dim_cur.get("ridge_height",  7.5)), step=0.1, key="fix_rh")

                                        # 各階フットプリント補正（2階建て以上のセットバックがある場合）
                                        _fix_fps = list(_fp_cur)  # コピー
                                        if _fp_cur:
                                            st.markdown("**各階フットプリント補正**")
                                            for _fi, _fp_item in enumerate(_fp_cur):
                                                _fca, _fcb, _fcc = st.columns(3)
                                                _fix_fps[_fi] = dict(_fp_item)
                                                _fix_fps[_fi]["width"]       = _fca.number_input(f"{_fi+1}F幅 (m)",   min_value=2.0, max_value=40.0, value=float(_fp_item.get("width",       10.0)), step=0.5, key=f"fix_fp_w{_fi}")
                                                _fix_fps[_fi]["floor_height"] = _fcb.number_input(f"{_fi+1}F高 (m)",   min_value=2.0, max_value=5.5,  value=float(_fp_item.get("floor_height", 2.8)), step=0.1, key=f"fix_fp_h{_fi}")
                                                _fix_fps[_fi]["x_offset"]    = _fcc.number_input(f"{_fi+1}F左オフセット(m)", min_value=0.0, max_value=10.0, value=float(_fp_item.get("x_offset", 0.0)), step=0.1, key=f"fix_fp_x{_fi}")

                                        if st.button("✅ 3Dを更新", type="primary", key="btn_3d_fix"):
                                            _bdata_fix = dict(st.session_state["building_3d_data"])
                                            _bdata_fix["dimensions"] = dict(_bdata_fix.get("dimensions") or {})
                                            _bdata_fix["dimensions"].update({
                                                "total_width":  _fix_w,
                                                "total_depth":  _fix_d,
                                                "eave_height":  _fix_eh,
                                                "ridge_height": _fix_rh,
                                            })
                                            _bdata_fix["eave_overhang"] = _fix_oh
                                            if _fix_fps:
                                                _bdata_fix["floor_footprints"] = _fix_fps
                                            st.session_state["building_3d_data"] = _bdata_fix
                                            st.rerun()

                                else:
                                    st.info("「⚙️ 解析方法」タブで解析を実行すると3Dモデルがここに表示されます")
                    # ── クリック割り当てUI ────────────────────────
                    st.markdown("---")
                    st.markdown("### 🎯 線をクリックして項目に割り当て")
                    st.caption("下の画像の線をクリック → 最も近い検出線を自動で特定 → 項目に値を登録します")

                    # 割り当て先の選択
                    _ASSIGN_ITEMS = {
                        "破風・鼻隠（m）":        ("fascia_m",           "m"),
                        "軒天（㎡）":             ("soffit_m2",          "㎡"),
                        "玄関庇軒天（㎡）":       ("entrance_soffit_m2", "㎡"),
                        "ベランダ軒天（㎡）":     ("veranda_soffit_m2",  "㎡"),
                        "SB（m）":               ("sb_m",               "m"),
                        "土台水切（m）":          ("base_cut_m",         "m"),
                        "中間水切（m）":          ("mid_cut_m",          "m"),
                        "ベランダ水切（m）":      ("veranda_cut_m",      "m"),
                        "基礎（㎡）":            ("foundation_m2",      "㎡"),
                        "出窓天端鉄部（m）":     ("window_top_m",       "m"),
                        "付梁（m）":             ("beam_m",             "m"),
                        "雨樋（m）":             ("gutter_m",           "m"),
                        "開口部廻りシール（m）":  ("opening_seal_m",     "m"),
                        "目地シール（m）":        ("joint_seal_m",       "m"),
                        "屋根（㎡）":            ("roof_m2",            "㎡"),
                    }
                    _FACE_MAP = {"東面": "east", "西面": "west", "南面": "south", "北面": "north"}

                    _ac1, _ac2, _ac3 = st.columns([2, 1, 1])
                    _assign_item = _ac1.selectbox("割り当て項目", list(_ASSIGN_ITEMS.keys()), key="assign_item_sel")
                    _assign_face = _ac2.selectbox("面", list(_FACE_MAP.keys()), key="assign_face_sel")
                    _assign_mode = _ac3.radio("加算/上書き", ["上書き", "加算"], horizontal=True, key="assign_mode_sel")

                    st.caption("👆 下の画像で線をクリックしてください")

                    from streamlit_image_coordinates import streamlit_image_coordinates as _sic
                    _ann_key = f"line_assign_{st.session_state.get('_assign_click_n', 0)}"
                    # annotated_bytes の実寸を取得してスケール係数を計算
                    import io as _io2
                    from PIL import Image as _PILImg2
                    _ann_pil = _PILImg2.open(_io2.BytesIO(_ld["annotated_bytes"]))
                    _ann_orig_w = _ann_pil.size[0]
                    _ann_disp_w = min(880, _ann_orig_w)
                    _ann_scale_r = _ann_orig_w / _ann_disp_w  # 表示→原画像の変換係数
                    # bytes→PIL Image に変換（_sic は bytes を受け付けない）
                    _ann_coord = _sic(_ann_pil, key=_ann_key, width=_ann_disp_w)

                    if _ann_coord:
                        from core.line_detector import find_nearest_line, highlight_line
                        # streamlit_image_coordinates は表示サイズでの座標を返す場合がある
                        # annotated_bytes の実寸を取得してスケール補正
                        import io as _io
                        from PIL import Image as _PILImg
                        _ann_img_pil = _PILImg.open(_io.BytesIO(_ld["annotated_bytes"]))
                        _orig_w, _orig_h = _ann_img_pil.size
                        # 座標がそのまま原画像空間なら補正不要
                        # 表示サイズ→原画像スペースに変換
                        _cx = _ann_coord["x"] * _ann_scale_r
                        _cy = _ann_coord["y"] * _ann_scale_r

                        _nearest = find_nearest_line(_cx, _cy, _ld["lines"], max_dist_px=60)

                        if _nearest:
                            # ハイライト画像
                            _hl_bytes = highlight_line(_ld["annotated_bytes"], _nearest)
                            st.image(_hl_bytes, use_container_width=True)

                            _orient_label = {"horizontal":"水平","vertical":"垂直","diagonal":"斜め"}.get(_nearest["orientation"],"")
                            _ln_num = _nearest.get("id", "?")
                            st.success(
                                f"✅ #{_ln_num} の線：**{_nearest['real_m']:.3f} m**  "
                                f"（{_orient_label}  距離:{_nearest['_dist_px']}px）"
                            )

                            _item_key, _item_unit = _ASSIGN_ITEMS[_assign_item]
                            _face_key = _FACE_MAP[_assign_face]

                            if st.button(
                                f"✅ {_assign_face}の「{_assign_item}」に **{_nearest['real_m']:.3f}{_item_unit}** を{'上書き' if _assign_mode=='上書き' else '加算'}する",
                                type="primary", use_container_width=True, key="btn_assign_confirm"
                            ):
                                if "face_inputs" not in st.session_state:
                                    from core.estimation_sheet_builder import make_empty_face_inputs
                                    st.session_state.face_inputs = make_empty_face_inputs()
                                _cur = st.session_state.face_inputs[_face_key].get(_item_key, 0) or 0
                                if _assign_mode == "加算":
                                    st.session_state.face_inputs[_face_key][_item_key] = round(_cur + _nearest["real_m"], 3)
                                else:
                                    st.session_state.face_inputs[_face_key][_item_key] = _nearest["real_m"]
                                # クリックをリセット
                                st.session_state["_assign_click_n"] = st.session_state.get("_assign_click_n", 0) + 1
                                _new_val = st.session_state.face_inputs[_face_key][_item_key]
                                st.success(f"🎉 登録完了！{_assign_face}「{_assign_item}」= {_new_val:.3f}{_item_unit}")
                                st.rerun()
                        else:
                            st.warning("クリック位置の近くに線が見つかりませんでした。もう少し線に近い位置をクリックしてください。")

                    # 現在の割り当て済み値を表示
                    _fi_now = st.session_state.get("face_inputs", {})
                    if any(_fi_now.get(f, {}) for f in ["east","west","south","north"]):
                        st.markdown("**📋 現在の割り当て済み値**")
                        import pandas as pd
                        _assigned_rows = []
                        for _fn, _fk in _FACE_MAP.items():
                            for _iname, (_ikey, _iunit) in _ASSIGN_ITEMS.items():
                                _v = _fi_now.get(_fk, {}).get(_ikey, 0)
                                if _v:
                                    _assigned_rows.append({"面": _fn, "項目": _iname, "値": f"{_v:.3f}{_iunit}"})
                        if _assigned_rows:
                            st.dataframe(pd.DataFrame(_assigned_rows), hide_index=True, use_container_width=True)
                else:
                    st.info("「線を検出する」ボタンを押すと、図面の全線分と実寸が表示されます。")

            # ── ③ 4面分割表示（図面を4等分し、各パネルで面ラベルを選んで計測） ──
            with st.expander("🪟 4面分割表示（南・北・東・西を個別に計測）", expanded=False):
                st.caption(
                    "図面を上下2段×左右2列の4ブロックに分割します。"
                    "各パネルのドロップダウンで南・北・東・西を割り当て、個別に計測・拡大できます。"
                )
                _face_opts = ["南面", "北面", "東面", "西面"]
                _face_code = {"南面": "south", "北面": "north", "東面": "east", "西面": "west"}
                # 各ブロック: (位置キー, 行, 列, タブ名, 既定の面ラベル)
                _quads = [
                    ("tl", 0, 0, "左上", "南面"),
                    ("tr", 0, 1, "右上", "北面"),
                    ("bl", 1, 0, "左下", "東面"),
                    ("br", 1, 1, "右下", "西面"),
                ]
                _tabs = st.tabs([q[3] for q in _quads])
                for _ti, (_pos, _r, _c, _tabname, _default) in enumerate(_quads):
                    with _tabs[_ti]:
                        _sel_face = st.selectbox(
                            "この面の向き（入れ替え可）",
                            _face_opts,
                            index=_face_opts.index(_default),
                            key=f"facesel_{_pos}",
                        )
                        _fcode = _face_code[_sel_face]
                        _quad_bytes = _crop_quad(drawing_raw_bytes, _r, _c)
                        st.image(_quad_bytes, caption=f"{_sel_face}（{_tabname}ブロック）",
                                 use_container_width=True)
                        if st.button("🔍 この面を拡大表示", use_container_width=True,
                                     key=f"zoom_{_pos}"):
                            _zoom_dialog(_quad_bytes, f"{_sel_face}（{_tabname}ブロック）")
                        st.divider()
                        _render_click_ruler(
                            _quad_bytes,
                            ns=f"quad_{_pos}",
                            labels=["縮尺基準線", f"{_sel_face}幅"],
                            reflect_map={f"{_sel_face}幅": f"ruler_{_fcode}_w"},
                        )

                # ── 幾何学計算ビュー（4面個別入力） ───────────────────────
        drawing_data_geo = st.session_state.get("drawing_data", {})
        ann_items_geo    = st.session_state.get("drawing_annotations", [])

        # アノテーションから高さ・幅の確定値を抽出
        def _ann_val(label_kw, items):
            for a in items:
                if label_kw in a.get("label", "") and a.get("confidence") in ("high", "medium"):
                    try:
                        return float(a["value"])
                    except Exception:
                        pass
            return None

        ridge_h = _ann_val("棟高", ann_items_geo) or drawing_data_geo.get("ridge_height")
        eave_h  = _ann_val("軒高", ann_items_geo) or drawing_data_geo.get("eave_height")
        south_w = _ann_val("南面幅", ann_items_geo)
        east_w  = _ann_val("東面幅", ann_items_geo)

        if ridge_h is None:
            ridge_h = 8.693
        if eave_h is None:
            eave_h  = 6.500

        with st.expander("📐 幾何学計算（4面個別入力・正確な面積算出）", expanded=True):
            st.markdown("##### 🏠 高さ（共通）")
            hc1, hc2 = st.columns(2)
            ridge_h_input = hc1.number_input(
                "棟高（m）", min_value=0.0, max_value=20.0,
                value=float(ridge_h), step=0.1, format="%.3f",
                help="GL（地盤面）から棟頂部までの高さ"
            )
            eave_h_input = hc2.number_input(
                "軒高（m）", min_value=0.0, max_value=15.0,
                value=float(eave_h), step=0.1, format="%.3f",
                help="GL（地盤面）から軒先までの高さ"
            )
            rise_preview = round(ridge_h_input - eave_h_input, 3)
            st.caption(f"屋根立上がり: **{rise_preview} m**")

            st.markdown("##### 📏 各面の幅（図面から計測）")
            st.caption("南面・東面は必須。北面・西面が南面・東面と異なる場合のみ入力（L字・凹凸のある建物）")
            # クリック計測で反映された値があれば優先使用
            _r_s = st.session_state.get("ruler_south_w", 0.0)
            _r_n = st.session_state.get("ruler_north_w", 0.0)
            _r_e = st.session_state.get("ruler_east_w",  0.0)
            _r_w = st.session_state.get("ruler_west_w",  0.0)

            wc1, wc2, wc3, wc4 = st.columns(4)
            s_w = wc1.number_input("南面幅（m）", min_value=0.0, max_value=50.0,
                value=_r_s if _r_s > 0 else (float(south_w) if south_w else 0.0),
                step=0.1, format="%.2f")
            n_w = wc2.number_input("北面幅（m）", min_value=0.0, max_value=50.0,
                value=_r_n, step=0.1, format="%.2f",
                help="南面と同じ場合は 0 のまま")
            e_w = wc3.number_input("東面幅（m）", min_value=0.0, max_value=50.0,
                value=_r_e if _r_e > 0 else (float(east_w) if east_w else 0.0),
                step=0.1, format="%.2f")
            w_w = wc4.number_input("西面幅（m）", min_value=0.0, max_value=50.0,
                value=_r_w, step=0.1, format="%.2f",
                help="東面と同じ場合は 0 のまま")

            st.markdown("##### 📐 屋根勾配")
            slope_mode = st.radio("勾配の指定方法", ["高さから自動計算", "勾配を直接入力（寸）"],
                                  horizontal=True, label_visibility="collapsed")
            if slope_mode == "勾配を直接入力（寸）":
                koun_input = st.number_input(
                    "屋根勾配（寸）", min_value=1.0, max_value=12.0,
                    value=6.0, step=0.5, format="%.1f",
                    help="6寸 = 10の水平距離に対して6の高さ。図面凡例や構造図から確認してください。"
                )
                import math
                angle_rad_input = math.atan(koun_input / 10.0)
                st.caption(f"→ {round(math.degrees(angle_rad_input), 1)}° / cos(θ) = {round(math.cos(angle_rad_input), 4)}")
                use_direct_slope = True
            else:
                koun_input = None
                angle_rad_input = None
                use_direct_slope = False

            st.markdown("##### 🪟 開口控除（窓・玄関等）")
            oc_mode = st.radio("控除方法", ["一律控除率（%）", "面ごとに開口面積を入力（㎡）"],
                               horizontal=True, label_visibility="collapsed")
            if oc_mode == "一律控除率（%）":
                ded_rate_pct = st.slider("開口控除率", 5, 30, 15, step=1,
                    help="標準は15%（窓・玄関等を差し引く割合）")
                ded_rate = ded_rate_pct / 100.0
                so_m2 = no_m2 = eo_m2 = wo_m2 = 0.0
            else:
                ded_rate = 0.0  # per-face 入力使用時は率を0にして個別値で控除
                oc1, oc2, oc3, oc4 = st.columns(4)
                so_m2 = oc1.number_input("南面開口（㎡）", min_value=0.0, max_value=100.0, step=0.5, format="%.1f")
                no_m2 = oc2.number_input("北面開口（㎡）", min_value=0.0, max_value=100.0, step=0.5, format="%.1f")
                eo_m2 = oc3.number_input("東面開口（㎡）", min_value=0.0, max_value=100.0, step=0.5, format="%.1f")
                wo_m2 = oc4.number_input("西面開口（㎡）", min_value=0.0, max_value=100.0, step=0.5, format="%.1f")

            st.markdown("##### 🏠 軒の出（のきので）")
            eave_overhang = st.number_input(
                "軒の出（m）",
                min_value=0.0, max_value=2.0, value=0.0, step=0.05, format="%.2f",
                help="屋根が外壁より外へ出ている長さ（片側）。標準は0.5〜0.9m。"
                     "外壁幅に 2×軒の出 を加えてフットプリントを計算します。"
            )
            if eave_overhang > 0:
                st.caption(f"フットプリントへの加算: 各辺に +{eave_overhang*2:.2f}m")

            if s_w > 0 and e_w > 0:
                from core.drawing_calc import calc_geometry_4face
                import pandas as pd
                geo = calc_geometry_4face(
                    south_width_m=s_w, north_width_m=n_w,
                    east_width_m=e_w,  west_width_m=w_w,
                    ridge_height_m=ridge_h_input, eave_height_m=eave_h_input,
                    south_opening_m2=so_m2, north_opening_m2=no_m2,
                    east_opening_m2=eo_m2,  west_opening_m2=wo_m2,
                    opening_deduction_rate=ded_rate,
                    angle_rad_override=angle_rad_input if use_direct_slope else None,
                    eave_overhang_m=eave_overhang,
                )
                st.session_state["geo_result"] = geo
                log_geo_calc("幾何計算実行", inputs={
                    "south_width_m": s_w, "north_width_m": n_w,
                    "east_width_m": e_w, "west_width_m": w_w,
                    "ridge_height_m": ridge_h_input, "eave_height_m": eave_h_input,
                }, result={
                    "wall_net_total": geo.get("wall_net_total"),
                    "roof_area_m2": geo.get("roof_area_m2"),
                    "koun": geo.get("koun"),
                })

                # 各面の内訳テーブル
                st.markdown("##### 📊 外壁 — 面ごとの計算")
                n_label = f"{geo['north_width_m']}m" + (" ※南面と同値" if n_w == 0 else "")
                w_label = f"{geo['west_width_m']}m"  + (" ※東面と同値" if w_w == 0 else "")
                wall_rows = [
                    {"面":  "南", "幅（m）": geo["south_width_m"], "軒高（m）": eave_h_input,
                     "総面積（㎡）": geo["wall_south_gross"], "控除（㎡）": round(geo["wall_south_gross"] - geo["wall_south_net"], 2), "正味面積（㎡）": geo["wall_south_net"]},
                    {"面":  "北", "幅（m）": geo["north_width_m"], "軒高（m）": eave_h_input,
                     "総面積（㎡）": geo["wall_north_gross"], "控除（㎡）": round(geo["wall_north_gross"] - geo["wall_north_net"], 2), "正味面積（㎡）": geo["wall_north_net"]},
                    {"面":  "東", "幅（m）": geo["east_width_m"],  "軒高（m）": eave_h_input,
                     "総面積（㎡）": geo["wall_east_gross"],  "控除（㎡）": round(geo["wall_east_gross"]  - geo["wall_east_net"],  2), "正味面積（㎡）": geo["wall_east_net"]},
                    {"面":  "西", "幅（m）": geo["west_width_m"],  "軒高（m）": eave_h_input,
                     "総面積（㎡）": geo["wall_west_gross"],  "控除（㎡）": round(geo["wall_west_gross"]  - geo["wall_west_net"],  2), "正味面積（㎡）": geo["wall_west_net"]},
                    {"面": "合計", "幅（m）": "—", "軒高（m）": "—",
                     "総面積（㎡）": geo["wall_gross_total"], "控除（㎡）": round(geo["wall_gross_total"] - geo["wall_net_total"], 2), "正味面積（㎡）": geo["wall_net_total"]},
                ]
                st.dataframe(pd.DataFrame(wall_rows), hide_index=True, use_container_width=True)

                # 屋根テーブル
                st.markdown("##### 🏠 屋根")
                roof_rows = [
                    {"項目": "屋根勾配",             "値": f"{geo['koun']}寸勾配（{geo['angle_deg']}°）"},
                    {"項目": "垂木長（実長）",         "値": f"{geo['rafter_length_m']} m"},
                    {"項目": "フットプリント（平均幅）", "値": f"{geo['avg_ns_m']} m × {geo['avg_ew_m']} m = {geo['footprint_m2']} ㎡"},
                    {"項目": "屋根面積（勾配補正後）",  "値": f"{geo['footprint_m2']} ÷ cos({geo['angle_deg']}°) = **{geo['roof_area_m2']} ㎡**"},
                ]
                st.dataframe(pd.DataFrame(roof_rows), hide_index=True, use_container_width=True)

                # メトリクス
                m1, m2 = st.columns(2)
                m1.metric("外壁面積（正味）", f"{geo['wall_net_total']} ㎡",
                          delta=f"総計 {geo['wall_gross_total']}㎡ → 控除後")
                m2.metric("屋根面積", f"{geo['roof_area_m2']} ㎡",
                          delta=f"{geo['koun']}寸勾配 / {geo['angle_deg']}°")

                if st.button("✅ この計算値を見積もりに使う", type="primary", use_container_width=True):
                    from core.quantity_calculator import calculate_from_quantities
                    q["wall_area"]  = geo["wall_net_total"]
                    q["roof_area"]  = geo["roof_area_m2"]
                    st.session_state.quantities = q
                    st.session_state.estimation = calculate_from_quantities(
                        q,
                        client_name=st.session_state.get("project", {}).get("client_name", ""),
                        site_address=st.session_state.get("project", {}).get("site_address", ""),
                        sales_rep=st.session_state.get("project", {}).get("sales_rep", ""),
                    )
                    log_ui("幾何計算値を見積もりに反映", {"wall_area": geo["wall_net_total"], "roof_area": geo["roof_area_m2"]})
                    st.success("✅ 計算値を反映しました")
                    st.rerun()
            else:
                st.info("南面・東面の幅を入力すると、屋根勾配・各面の外壁・屋根面積が自動計算されます。")

        # ── 付帯部 4面別入力（積算集計表用） ──────────────────────
        with st.expander("📋 付帯部寸法（4面別入力）→ 積算集計表を生成", expanded=False):
            st.caption("各面の付帯部寸法を入力すると、サンプルExcelと同じ形式の積算集計表を出力できます。")
            from core.estimation_sheet_builder import FACES, FACE_LABEL, make_empty_face_inputs

            # session_state 初期化
            if "face_inputs" not in st.session_state:
                st.session_state.face_inputs = make_empty_face_inputs()
            fi = st.session_state.face_inputs

            # --- 屋根面積 自動分配 UI ---
            _geo_for_auto = st.session_state.get("geo_result", {})
            if _geo_for_auto and not _geo_for_auto.get("error"):
                _total_roof = _geo_for_auto.get("roof_area_m2", 0)
                if _total_roof and _total_roof > 0:
                    st.markdown(
                        f"**📐 幾何計算の屋根面積: {_total_roof} ㎡**  →  形状を選んで各面に自動入力できます"
                    )
                    _rc1, _rc2 = st.columns([3, 2])
                    _roof_shape = _rc1.selectbox(
                        "屋根形状",
                        ["切妻（南北棟）", "切妻（東西棟）", "寄棟", "片流れ（南）", "片流れ（北）", "片流れ（東）", "片流れ（西）"],
                        key="roof_shape_sel",
                        label_visibility="collapsed",
                    )
                    if _rc2.button("🔄 屋根面積を自動入力", use_container_width=True, key="auto_roof_btn"):
                        from core.drawing_calc import distribute_roof_area as _dist_roof
                        _dist = _dist_roof(_total_roof, _geo_for_auto, _roof_shape)
                        for _fk in ["east", "west", "south", "north"]:
                            fi[_fk]["roof_m2"] = _dist[_fk]
                        st.session_state.face_inputs = fi
                        st.success(
                            f"✅ {_total_roof}㎡ を分配しました — "
                            + " / ".join(f"{v}㎡" for v in [_dist['south'], _dist['north'], _dist['east'], _dist['west']])
                            + "（南/北/東/西）"
                        )
                        st.rerun()
                    st.markdown("---")

            # --- 入力テーブル（タブで面を切り替え） ---
            tabs_fi = st.tabs(["東面", "西面", "南面", "北面"])
            face_keys = ["east", "west", "south", "north"]

            for _ti, (_tab, _fk) in enumerate(zip(tabs_fi, face_keys)):
                with _tab:
                    _fi = fi[_fk]
                    _c1, _c2 = st.columns(2)
                    _fi["roof_m2"]            = _c1.number_input(f"屋根（㎡）",           min_value=0.0, value=float(_fi.get("roof_m2",0)),            step=0.1, format="%.3f", key=f"fi_{_fk}_roof")
                    _fi["roof_opening_m2"]    = _c2.number_input(f"屋根開口控除（㎡）",   min_value=0.0, value=float(_fi.get("roof_opening_m2",0)),    step=0.1, format="%.3f", key=f"fi_{_fk}_roof_o")
                    _fi["fascia_m"]           = _c1.number_input(f"破風・鼻隠（m）",      min_value=0.0, value=float(_fi.get("fascia_m",0)),           step=0.1, format="%.2f", key=f"fi_{_fk}_fascia")
                    _fi["soffit_m2"]          = _c2.number_input(f"軒天（㎡）",           min_value=0.0, value=float(_fi.get("soffit_m2",0)),          step=0.1, format="%.2f", key=f"fi_{_fk}_soffit")
                    _fi["entrance_soffit_m2"] = _c1.number_input(f"玄関庇軒天（㎡）",    min_value=0.0, value=float(_fi.get("entrance_soffit_m2",0)), step=0.1, format="%.2f", key=f"fi_{_fk}_eso")
                    _fi["veranda_soffit_m2"]  = _c2.number_input(f"ベランダ軒天（㎡）",  min_value=0.0, value=float(_fi.get("veranda_soffit_m2",0)),  step=0.1, format="%.2f", key=f"fi_{_fk}_vso")
                    _fi["sb_m"]               = _c1.number_input(f"SB（m）",             min_value=0.0, value=float(_fi.get("sb_m",0)),               step=0.1, format="%.2f", key=f"fi_{_fk}_sb")
                    _fi["base_cut_m"]         = _c2.number_input(f"土台水切（m）",        min_value=0.0, value=float(_fi.get("base_cut_m",0)),         step=0.1, format="%.2f", key=f"fi_{_fk}_bcut")
                    _fi["mid_cut_m"]          = _c1.number_input(f"中間水切（m）",        min_value=0.0, value=float(_fi.get("mid_cut_m",0)),          step=0.1, format="%.2f", key=f"fi_{_fk}_mcut")
                    _fi["veranda_cut_m"]      = _c2.number_input(f"ベランダ水切（m）",   min_value=0.0, value=float(_fi.get("veranda_cut_m",0)),      step=0.1, format="%.2f", key=f"fi_{_fk}_vcut")
                    _fi["gutter_m"]           = _c1.number_input(f"雨樋（m）",            min_value=0.0, value=float(_fi.get("gutter_m",0)),           step=0.1, format="%.2f", key=f"fi_{_fk}_gutter")
                    _fi["opening_seal_m"]     = _c2.number_input(f"開口部廻りシール（m）",min_value=0.0, value=float(_fi.get("opening_seal_m",0)),     step=0.1, format="%.2f", key=f"fi_{_fk}_oseal")
                    _fi["joint_seal_m"]       = _c1.number_input(f"目地シール（m）",      min_value=0.0, value=float(_fi.get("joint_seal_m",0)),       step=0.1, format="%.2f", key=f"fi_{_fk}_jseal")
                    _fi["foundation_m2"]      = _c2.number_input(f"基礎（㎡）",           min_value=0.0, value=float(_fi.get("foundation_m2",0)),      step=0.1, format="%.2f", key=f"fi_{_fk}_found")
                    _fi["toplight_seal_m"]    = _c1.number_input(f"トップライト廻りシール（m）",min_value=0.0, value=float(_fi.get("toplight_seal_m",0)), step=0.1, format="%.2f", key=f"fi_{_fk}_toplight")
                    _fi["window_top_m"]       = _c2.number_input(f"出窓天端鉄部（m）",   min_value=0.0, value=float(_fi.get("window_top_m",0)),       step=0.1, format="%.2f", key=f"fi_{_fk}_wtop")
                    _fi["beam_m"]             = _c1.number_input(f"付梁（m）",            min_value=0.0, value=float(_fi.get("beam_m",0)),             step=0.1, format="%.2f", key=f"fi_{_fk}_beam")
                    fi[_fk] = _fi

            st.session_state.face_inputs = fi

            # --- プレビュー（geoがあれば積算集計表を即時プレビュー） ---
            _geo_for_est = st.session_state.get("geo_result", {})
            if _geo_for_est and not _geo_for_est.get("error"):
                from core.estimation_sheet_builder import build_estimation_data
                import pandas as pd
                _est_data = build_estimation_data(
                    geo=_geo_for_est,
                    face_inputs=fi,
                    project={
                        "client_name":   st.session_state.get("project", {}).get("client_name", ""),
                        "site_address":  st.session_state.get("project", {}).get("site_address", ""),
                        "building_type": st.session_state.get("project", {}).get("building_type", ""),
                        "roof_type":     st.session_state.get("project", {}).get("roof_type", ""),
                        "company_name":  st.session_state.get("company_name", ""),
                        "sales_rep":     st.session_state.get("project", {}).get("sales_rep", ""),
                    },
                )
                st.session_state["estimation_sheet_data"] = _est_data

                # プレビューテーブル
                _preview_rows = []
                for _r in _est_data["rows"]:
                    if _r["total"] > 0:
                        _fv = _r["faces"]
                        _preview_rows.append({
                            "項目": _r["label"],
                            "単位": _r["unit"],
                            "東面": _fv["east"]["gross"] or "",
                            "東控除": _fv["east"]["opening"] or "",
                            "東計": _fv["east"]["net"] or "",
                            "西面": _fv["west"]["gross"] or "",
                            "南面": _fv["south"]["gross"] or "",
                            "北面": _fv["north"]["gross"] or "",
                            "合計": _r["total"],
                        })
                if _preview_rows:
                    st.markdown("##### 📊 積算集計表プレビュー（0以外の項目のみ）")
                    st.dataframe(pd.DataFrame(_preview_rows), hide_index=True, use_container_width=True)
                else:
                    st.info("付帯部寸法を入力すると積算集計表プレビューが表示されます。")
            else:
                st.info("先に「📐 幾何学計算」で各面の幅を入力してください。外壁の計算結果が積算集計表に反映されます。")

        # ── 合計表示 ────────────────────────────────────────
        st.metric("合計（税込）", f"¥{est.get('total', 0):,}")

        # ── 数値直接編集フォーム ──────────────────────────────
        st.caption("📝 数値を直接編集できます。変更後「再計算」を押してください")
        ec1, ec2, ec3 = st.columns(3)
        edit_wall   = ec1.number_input("外壁面積（㎡）",      min_value=0.0, value=float(q.get("wall_area", 0)),         step=1.0)
        edit_roof   = ec2.number_input("屋根面積（㎡）",      min_value=0.0, value=float(q.get("roof_area", 0)),         step=1.0)
        edit_fascia = ec3.number_input("破風（m）",           min_value=0.0, value=float(q.get("fascia_length", 0)),     step=0.5)
        ec4, ec5, ec6 = st.columns(3)
        edit_soffit = ec4.number_input("軒天（破風m合わせ）",   min_value=0.0, value=float(q.get("soffit_estimate_m", 0)), step=0.5)
        edit_gutter = ec5.number_input("雨樋（m）",           min_value=0.0, value=float(q.get("gutter_length", 0)),     step=0.5)
        edit_joint  = ec6.number_input("目地シーリング（m）", min_value=0.0, value=float(q.get("joint_seal_length", 0)), step=0.5)

        # ── 工事オプション ────────────────────────────────────
        st.markdown("**🔧 工事オプション**")
        oc1, oc2, oc3 = st.columns(3)
        edit_guardman  = oc1.number_input("ガードマン（人）",     min_value=0,   value=int(q.get("guardman_count", 0)),     step=1)
        edit_discount  = oc2.number_input("値引き（円）",         min_value=0,   value=int(q.get("discount", 0)),           step=10000)
        edit_window_top= oc3.number_input("出窓天端（m）",        min_value=0.0, value=float(q.get("window_top_length", 0)), step=0.5)
        oc4, oc5, oc6 = st.columns(3)
        edit_beam      = oc4.number_input("化粧梁（m）",          min_value=0.0, value=float(q.get("beam_length", 0)),      step=0.5)
        edit_shutter   = oc5.number_input("シャッターBOX（m）",   min_value=0.0, value=float(q.get("shutter_box_length", 0)), step=0.5)
        edit_skylight  = oc6.number_input("トップライト（箇所）", min_value=0,   value=int(q.get("skylight_count", 0)),     step=1)
        fl1, fl2, fl3 = st.columns(3)
        edit_pipe      = fl1.checkbox("防護管",     value=bool(q.get("do_protection_pipe", False)))
        edit_carport   = fl2.checkbox("カーポート脱着", value=bool(q.get("do_carport", False)))
        edit_foundation= fl3.checkbox("基礎塗装",   value=bool(q.get("do_foundation", False)))

        if st.button("🔄 再計算する", type="primary", use_container_width=True):
            q["wall_area"]          = edit_wall
            q["roof_area"]          = edit_roof
            q["fascia_length"]      = edit_fascia
            q["soffit_estimate_m"]  = edit_soffit
            q["gutter_length"]      = edit_gutter
            q["joint_seal_length"]  = edit_joint
            q["scaffold_area"]      = round(edit_wall * 1.1, 1)
            if edit_wall > 0 and edit_roof > 0:
                q["roof_scaffold_area"] = edit_roof
            q["guardman_count"]     = edit_guardman
            q["discount"]           = edit_discount
            q["window_top_length"]  = edit_window_top
            q["beam_length"]        = edit_beam
            q["shutter_box_length"] = edit_shutter
            q["skylight_count"]     = edit_skylight
            q["do_protection_pipe"] = edit_pipe
            q["do_carport"]         = edit_carport
            q["do_foundation"]      = edit_foundation
            st.session_state.quantities = q
            st.session_state.estimation = calculate_from_quantities(
                q,
                client_name=proj.get("client_name", ""),
                site_address=proj.get("site_address", ""),
                sales_rep=proj.get("sales_rep", ""),
            )
            log_ui("STEP2: 再計算ボタン", {"wall_area": edit_wall, "roof_area": edit_roof, "discount": edit_discount})
            st.rerun()

        if extras.get("notes"):
            st.info(f"📝 音声メモ補足: {extras['notes']}")
        st.caption(
            "※ 足場・シーリング等の未入力項目は塗装業の経験則で自動補完しています。"
            "金額の内訳は次の見積書画面でご確認いただけます。"
        )

        # ── 直近の修正結果 ────────────────────────────────────
        last = st.session_state.get("last_correction") or {}
        if last.get("changes"):
            st.success("🔄 修正を反映しました：" + last.get("explanation", ""))
            for c in last["changes"]:
                st.write("　・ " + c["text"])

        # ── 音声・テキストで修正 ──────────────────────────────
        st.markdown("---")
        st.subheader("🎤 修正がある場合は音声または入力で伝えてください")
        st.caption("例：「屋根は185平米、ガードマン不要、値引き5万円」")

        mc1, mc2 = st.columns([1, 1])
        with mc1:
            corr_audio = st.audio_input("修正を録音 →", key="corr_audio")
            if corr_audio is not None and st.button(
                "🎧 文字起こし（修正）", use_container_width=True):
                with st.spinner("Whisperで文字起こし中…"):
                    try:
                        from modules.llm_client import LLMClient
                        llm = LLMClient()
                        text = llm.transcribe_audio(corr_audio.getvalue(), "correction.webm")
                        st.session_state["correction_input"] = text
                        st.rerun()
                    except Exception as e:
                        st.error(f"文字起こし失敗: {e}")
        with mc2:
            correction_text = st.text_area(
                "修正内容（文字起こし結果・手入力も可）",
                key="correction_input",
                height=120,
                placeholder="屋根は185平米、ガードマン不要、値引き5万円…",
            )

        if st.button("🔄 修正を反映する", use_container_width=True):
            if not (correction_text or "").strip():
                st.warning("修正内容を入力してください")
            else:
                with st.spinner("AIが修正指示を解釈中…"):
                    try:
                        from modules.llm_client import LLMClient
                        from core.quantity_adjuster import adjust_quantities
                        llm = LLMClient()
                        result = adjust_quantities(
                            st.session_state.quantities, correction_text, llm)
                        if result["changes"]:
                            st.session_state.quantities = result["quantities"]
                            st.session_state.estimation = calculate_from_quantities(
                                result["quantities"],
                                client_name=proj.get("client_name", ""),
                                site_address=proj.get("site_address", ""),
                                sales_rep=proj.get("sales_rep", ""),
                            )
                            st.session_state.correction_history.append({
                                "text":        correction_text,
                                "explanation": result["explanation"],
                                "changes":     result["changes"],
                            })
                            st.session_state.last_correction = result
                            st.session_state["_clear_correction"] = True
                            log_ui("STEP2: 修正反映", {
                                "changes": result["changes"],
                                "explanation": result.get("explanation", ""),
                            })
                            st.rerun()
                        else:
                            st.info(
                                "変更点が見つかりませんでした"
                                f"（{result.get('explanation', '')}）"
                            )
                    except Exception as e:
                        log_error("修正反映エラー", e)
                        st.error(f"修正反映エラー: {e}")

        # ── 修正履歴 ──────────────────────────────────────────
        hist = st.session_state.get("correction_history", [])
        if hist:
            with st.expander(f"🕑 修正履歴（{len(hist)}件）"):
                for i, h in enumerate(hist, 1):
                    st.markdown(f"**{i}. 「{h['text']}」**")
                    for c in h["changes"]:
                        st.caption("　・ " + c["text"])

        st.markdown("---")
        b1, b2, b3 = st.columns(3)
        with b1:
            if st.button("📐 図面で手動計測する", use_container_width=True):
                log_ui("STEP2→STEP3: 図面手動積算へ")
                st.session_state.step = 3
                st.rerun()
        with b2:
            if st.button("📝 数量を確認・修正する", use_container_width=True):
                log_ui("STEP2→STEP4: 数量確認へ")
                st.session_state.step = 4
                st.rerun()
        with b3:
            if st.button("✅ この内容で見積書へ", type="primary", use_container_width=True):
                log_ui("STEP2→STEP5: 見積書へ直接進む")
                st.session_state.step = 5
                st.rerun()
        if st.button("← 入力に戻る"):
            log_ui("STEP2→STEP1: 入力に戻る（積算完了後）")
            st.session_state.step = 1
            st.rerun()


# ═════════════════════════════════════════════════════════════
# STEP 3: 図面手動積算
# ═════════════════════════════════════════════════════════════
elif st.session_state.step == 3:
    st.header("③ 図面手動積算")
    st.caption("図面から直接面積・長さを計測します（スキップ可能）")

    # ── 図面ソースを収集 ────────────────────────────────────
    from core.drawing_import import load_drawing_pages_with_errors
    import os as _os

    step1_sources: list = []
    pdf_bytes = st.session_state.get("pdf_bytes")
    floor_plan_bytes = st.session_state.get("floor_plan_bytes")
    if pdf_bytes:
        step1_sources.append(("図面PDF", ".pdf", pdf_bytes))
    if floor_plan_bytes:
        step1_sources.append(("間取り図", ".pdf", floor_plan_bytes))

    # ── STEP3 追加図面アップローダー ──────────────────────
    additional_files = st.file_uploader(
        "追加の図面ファイル（PDF / PNG / JPEG）",
        type=["pdf", "png", "jpg", "jpeg"],
        accept_multiple_files=True,
        key="drawing_upload_step3",
    )
    additional_sources = [
        (f.name, _os.path.splitext(f.name)[1].lower(), f.getvalue())
        for f in (additional_files or [])
    ]
    all_sources = step1_sources + additional_sources

    # ── STEP3追加図面をsession_stateへコピー（A3-0b-1） ─────────
    # ウィジェット（drawing_upload_step3）の状態そのものに依存せず、
    # STEP3表示のたびに現在の添付内容をミラーリングしておく。
    # これによりSTEP5（保存ボタン）到達時にも、STEP3で最後に表示された
    # 添付内容を参照できる。
    st.session_state["step3_drawing_files"] = [
        {"filename": f.name, "bytes": f.getvalue()}
        for f in (additional_files or [])
    ]

    pages, load_errors = load_drawing_pages_with_errors(all_sources)

    for err in load_errors:
        st.error(err)

    if not pages:
        st.info("図面が見つかりません。STEP1で図面PDFまたは画像をアップロードしてください。")
    else:
        # ── ページセレクタ ──────────────────────────────────
        page_labels = [p["label"] for p in pages]
        selected_idx = st.selectbox(
            "ページを選択",
            range(len(pages)),
            format_func=lambda i: page_labels[i],
            key="drawing_page_selector",
        )
        selected_page = pages[selected_idx]

        # ── 手動計測キャンバス（A2） ────────────────────────
        # ページ識別子: ファイルハッシュ + ページ番号（ラベル変更でも不変）
        page_key = f'{selected_page["file_hash"]}:p{selected_page["page"]}'

        # ページ単位の状態 dict をセッションで管理
        if "canvas_states" not in st.session_state:
            st.session_state.canvas_states = {}

        # ページ切替・rerun 後の復元用: 保存済みの状態 dict を渡す
        canvas_state = st.session_state.canvas_states.get(page_key)

        from core.drawing_canvas import drawing_canvas as _drawing_canvas
        _canvas_result = _drawing_canvas(
            image_bytes=selected_page["img_bytes"],
            image_width=selected_page["width"],
            image_height=selected_page["height"],
            page_key=page_key,
            canvas_height=600,
            canvas_state=canvas_state,
            key=f"dc_{page_key}",
        )

        # 操作完了時のみ値が返る → ページ状態全体を更新して保存
        if _canvas_result is not None:
            st.session_state.canvas_states[page_key] = _canvas_result

        # 現在のページの線数を表示
        _current_state = st.session_state.canvas_states.get(page_key, {})
        _current_lines = _current_state.get("objects", [])
        st.caption(
            f"サイズ: {selected_page['width']} × {selected_page['height']} px"
            f"　|　計測線: {len(_current_lines)} 本"
        )

    # ── ナビゲーション ──────────────────────────────────────
    st.markdown("---")
    nav1, nav2 = st.columns(2)
    with nav1:
        if st.button("← AI積算に戻る", use_container_width=True):
            log_ui("STEP3→STEP2: AI積算に戻る")
            st.session_state.step = 2
            st.rerun()
    with nav2:
        if st.button("スキップ → 数量確認へ", type="primary", use_container_width=True):
            log_ui("STEP3→STEP4: 数量確認へスキップ")
            st.session_state.step = 4
            st.rerun()


# ═════════════════════════════════════════════════════════════
# STEP 4: 数量確認フォーム
# ═════════════════════════════════════════════════════════════
elif st.session_state.step == 4:
    st.header("④ 数量確認フォーム")
    st.caption("AI解析結果を確認・修正し、実際の数量を入力してください")

    q = st.session_state.quantities.copy()

    drawing_data = st.session_state.get("drawing_data", {})
    if drawing_data.get("notes"):
        st.info(f"📐 図面AIメモ: {drawing_data['notes']}")

    with st.form("quantity_form"):

        # ── 仮設工事 ──────────────────────────────────────────
        st.subheader("🏗️ 仮設工事")
        f1, f2 = st.columns(2)
        with f1:
            scaffold_area      = st.number_input("外部足場面積（㎡）",
                min_value=0.0, value=float(q.get("scaffold_area", 0)), step=0.5)
            roof_scaffold_area = st.number_input("屋根足場面積（㎡）",
                min_value=0.0, value=float(q.get("roof_scaffold_area", 0)), step=0.5)
            guardman_count     = st.number_input("ガードマン（人）",
                min_value=0, value=int(q.get("guardman_count", 0)), step=1)
        with f2:
            do_lifting         = st.checkbox("昇降設備",           value=q.get("do_lifting", True))
            do_transport       = st.checkbox("運搬費",             value=q.get("do_transport", True))
            do_road_permit     = st.checkbox("道路使用許可申請",   value=q.get("do_road_permit", True))
            do_protection_pipe = st.checkbox("防護管",             value=q.get("do_protection_pipe", False))

        # ── 屋根塗装 ──────────────────────────────────────────
        st.subheader("🏠 屋根塗装")
        do_roof = st.checkbox("屋根塗装を実施する", value=q.get("do_roof", True))
        if do_roof:
            r1, r2, r3 = st.columns(3)
            with r1:
                roof_area = st.number_input("屋根面積（㎡）",
                    min_value=0.0, value=float(q.get("roof_area", 0)), step=0.5)
            with r2:
                roof_type = st.selectbox("屋根種別",
                    ["スレート", "金属屋根（ガルバリウム）", "日本瓦", "アスファルトシングル"])
            with r3:
                roof_paint_spec = st.selectbox("屋根塗料",
                    ["クールタイトSi", "クールタイトF", "ヤネフレッシュSi",
                     "アレスクールSi", "サーモアイSi", "その他"])
        else:
            roof_area = 0.0
            roof_type = "スレート"
            roof_paint_spec = "クールタイトSi"

        # ── 外壁塗装 ──────────────────────────────────────────
        st.subheader("🧱 外壁塗装")
        w1, w2, w3 = st.columns(3)
        with w1:
            wall_area = st.number_input("外壁面積（㎡）",
                min_value=0.0, value=float(q.get("wall_area", 0)), step=0.5)
        with w2:
            wall_paint_spec = st.selectbox("外壁塗料",
                ["ラジカル塗料（パーフェクトトップ等）",
                 "シリコン（クリーンマイルドシリコン等）",
                 "フッ素（プレミアムシリコン等）", "無機塗料", "その他"])
        with w3:
            sub_paint_spec = st.selectbox("付帯部塗料",
                ["クリーンマイルドシリコン", "1液ファインシリコンセラUV",
                 "パーフェクトトップ", "その他"])

        # ── 付帯部 ────────────────────────────────────────────
        st.subheader("🔩 付帯部")
        a1, a2, a3 = st.columns(3)
        with a1:
            fascia_length       = st.number_input("破風・鼻隠し（m）",
                min_value=0.0, value=float(q.get("fascia_length", 0)), step=0.5)
            soffit_estimate_m   = st.number_input("軒天（破風m合わせ）",
                min_value=0.0, value=float(q.get("soffit_estimate_m", 0)), step=0.5)
            soffit_entrance_sqm = st.number_input("玄関庇軒天面積（㎡）",
                min_value=0.0, value=float(q.get("soffit_entrance_sqm", 0)), step=0.5)
            soffit_balcony_sqm  = st.number_input("ベランダ軒天面積（㎡）",
                min_value=0.0, value=float(q.get("soffit_balcony_sqm", 0)), step=0.5)
        with a2:
            gutter_length       = st.number_input("雨樋（m）",
                min_value=0.0, value=float(q.get("gutter_length", 0)), step=0.5)
            water_cutoff_length = st.number_input("土台水切（m）",
                min_value=0.0, value=float(q.get("water_cutoff_length", 0)), step=0.5)
            window_top_length   = st.number_input("出窓天端（m）",
                min_value=0.0, value=float(q.get("window_top_length", 0)), step=0.5)
        with a3:
            beam_length         = st.number_input("化粧梁・付梁（m）",
                min_value=0.0, value=float(q.get("beam_length", 0)), step=0.5)
            shutter_box_length  = st.number_input("シャッターボックス（m）",
                min_value=0.0, value=float(q.get("shutter_box_length", 0)), step=0.5)
            do_foundation       = st.checkbox("基礎塗装",
                value=q.get("do_foundation", False))

        # ── シーリング ────────────────────────────────────────
        st.subheader("🔵 シーリング工事")
        sl1, sl2, sl3 = st.columns(3)
        with sl1:
            joint_seal_length = st.number_input("目地シーリング（m）",
                min_value=0.0, value=float(q.get("joint_seal_length", 0)), step=0.5)
        with sl2:
            do_misc_seal = st.checkbox("雑シーリング（開口部等）",
                value=q.get("do_misc_seal", True))
        with sl3:
            skylight_count = st.number_input("トップライト（箇所）",
                min_value=0, value=int(q.get("skylight_count", 0)), step=1)

        # ── 金額調整 ──────────────────────────────────────────
        st.subheader("💰 金額調整")
        m1, m2 = st.columns(2)
        with m1:
            misc_cost = st.number_input("諸経費（円）",
                min_value=0, value=int(q.get("misc_cost", 200000)), step=10000)
        with m2:
            discount = st.number_input("値引き（円）",
                min_value=0, value=int(q.get("discount", 0)), step=10000,
                help="値引き額（プラスで入力してください）")

        submitted = st.form_submit_button(
            "✅ 積算・見積書を作成する", type="primary", use_container_width=True)

        if submitted:
            new_q = {
                "scaffold_area":      scaffold_area,
                "roof_scaffold_area": roof_scaffold_area,
                "guardman_count":     guardman_count,
                "do_lifting":         do_lifting,
                "do_transport":       do_transport,
                "do_road_permit":     do_road_permit,
                "do_protection_pipe": do_protection_pipe,
                "do_roof":            do_roof,
                "roof_area":          roof_area,
                "roof_type":          roof_type,
                "roof_paint_spec":    roof_paint_spec,
                "wall_area":          wall_area,
                "wall_paint_spec":    wall_paint_spec,
                "sub_paint_spec":     sub_paint_spec,
                "fascia_length":      fascia_length,
                "soffit_estimate_m":  soffit_estimate_m,
                "soffit_entrance_sqm": soffit_entrance_sqm,
                "soffit_balcony_sqm": soffit_balcony_sqm,
                "gutter_length":      gutter_length,
                "water_cutoff_length": water_cutoff_length,
                "window_top_length":  window_top_length,
                "beam_length":        beam_length,
                "shutter_box_length": shutter_box_length,
                "do_foundation":      do_foundation,
                "joint_seal_length":  joint_seal_length,
                "do_misc_seal":       do_misc_seal,
                "skylight_count":     skylight_count,
                "misc_cost":          misc_cost,
                "discount":           discount,
            }
            st.session_state.quantities = new_q
            proj = st.session_state.project
            estimation = calculate_from_quantities(
                new_q,
                client_name=proj.get("client_name", ""),
                site_address=proj.get("site_address", ""),
                sales_rep=proj.get("sales_rep", ""),
            )
            st.session_state.estimation = estimation
            log_ui("STEP3フォーム送信", {
                "wall_area": wall_area, "roof_area": roof_area,
                "scaffold_area": scaffold_area, "fascia_length": fascia_length,
                "gutter_length": gutter_length, "joint_seal_length": joint_seal_length,
                "misc_cost": misc_cost, "discount": discount,
                "do_roof": do_roof, "do_foundation": do_foundation,
                "total": estimation.get("total"),
            })
            st.session_state.step = 5
            st.rerun()

    if st.button("← 図面手動積算へ戻る"):
        log_ui("STEP4→STEP3: 図面手動積算に戻る")
        st.session_state.step = 3
        st.rerun()


# ═════════════════════════════════════════════════════════════
# STEP 5: 見積書出力
# ═════════════════════════════════════════════════════════════
elif st.session_state.step == 5:
    st.header("⑤ 見積書完成")

    proj       = st.session_state.project
    estimation = st.session_state.estimation
    items      = estimation.get("estimation_items", [])

    # ── サマリー ─────────────────────────────────────────────
    m1, m2, m3 = st.columns(3)
    m1.metric("小計（税抜）",  f"¥{estimation.get('subtotal', 0):,}")
    m2.metric("消費税（10%）", f"¥{estimation.get('tax_amount', 0):,}")
    m3.metric("合計（税込）",  f"¥{estimation.get('total', 0):,}")
    if estimation.get("discount", 0) > 0:
        st.info(f"💡 値引き ¥{estimation['discount']:,} 適用済み")

    # ── 明細テーブル ─────────────────────────────────────────
    st.subheader("📋 積算明細")
    if items:
        import pandas as pd
        rows = [{
            "区分":   it.get("category", ""),
            "工事名": it.get("item_name", ""),
            "数量":   it.get("quantity", 0),
            "単位":   it.get("unit", ""),
            "単価":   f"¥{it.get('unit_price', 0):,}",
            "金額":   f"¥{it.get('amount', 0):,}",
            "仕様":   it.get("notes", ""),
        } for it in items]
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.warning("明細が空です。数量フォームで面積・長さを入力してください。")

    # ── 積算集計表プレビュー（付帯部4面入力済みの場合） ─────────
    _est_sheet = st.session_state.get("estimation_sheet_data")
    if _est_sheet:
        import pandas as _pd2
        _prev = [
            {
                "項目": _r["label"], "単位": _r["unit"],
                "東面": _r["faces"]["east"]["gross"] or "",
                "東控除": _r["faces"]["east"]["opening"] or "",
                "東計": _r["faces"]["east"]["net"] or "",
                "西面": _r["faces"]["west"]["gross"] or "",
                "南面": _r["faces"]["south"]["gross"] or "",
                "北面": _r["faces"]["north"]["gross"] or "",
                "合計": _r["total"],
            }
            for _r in _est_sheet["rows"] if _r["total"] > 0
        ]
        if _prev:
            with st.expander("📋 積算集計表（4面別）", expanded=True):
                st.dataframe(_pd2.DataFrame(_prev), hide_index=True, use_container_width=True)

    st.markdown("---")

    # ── Excel出力 ────────────────────────────────────────────
    st.subheader("📥 Excelファイル出力")
    template_path = Path(__file__).parent / "data" / "templates" / "standard.xlsx"

    if template_path.exists():
        if st.button("📊 Excelファイルを生成する", type="primary", use_container_width=True):
            with st.spinner("Excelを生成中…"):
                try:
                    client_name = proj.get("client_name", "顧客")
                    safe_name   = "".join(c for c in client_name
                                          if c.isalnum() or c in "　・ー") or "顧客"
                    timestamp   = datetime.now().strftime("%Y%m%d_%H%M")
                    filename    = f"見積_{safe_name}_{timestamp}.xlsx"

                    with tempfile.TemporaryDirectory() as tmpdir:
                        output_path = Path(tmpdir) / filename
                        fill_template(
                            template_id="standard",
                            template_path=template_path,
                            output_path=output_path,
                            estimation=estimation,
                            project_data=st.session_state.get("image_data", {}),
                            client_name=proj.get("client_name", ""),
                            site_address=proj.get("site_address", ""),
                            sales_rep=proj.get("sales_rep", ""),
                            discount=estimation.get("discount", 0),
                        )
                        with open(output_path, "rb") as f:
                            excel_bytes = f.read()

                        # ── 積算集計表も生成 ──
                        est_template = template_path.parent / "estimation_sheet.xlsx"
                        est_bytes = None
                        est_filename = None
                        if est_template.exists():
                            est_filename = f"積算集計表_{safe_name}_{timestamp}.xlsx"
                            est_output = Path(tmpdir) / est_filename
                            fill_estimation_sheet(
                                template_path=est_template,
                                output_path=est_output,
                                estimation=estimation,
                                client_name=proj.get("client_name", ""),
                                site_address=proj.get("site_address", ""),
                                sales_rep=proj.get("sales_rep", ""),
                                company_name=st.session_state.get("company_name") or "",
                                building_type=proj.get("building_type", ""),
                                estimation_sheet_data=st.session_state.get("estimation_sheet_data"),
                            )
                            with open(est_output, "rb") as f:
                                est_bytes = f.read()

                    st.download_button(
                        label=f"⬇️ {filename} をダウンロード",
                        data=excel_bytes,
                        file_name=filename,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                    )
                    if est_bytes and est_filename:
                        st.download_button(
                            label=f"⬇️ {est_filename} をダウンロード",
                            data=est_bytes,
                            file_name=est_filename,
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True,
                        )
                    log_file("Excel生成成功", filename, size_bytes=len(excel_bytes))
                    st.success(f"✅ 見積書・積算集計表を生成しました！")

                except Exception as e:
                    log_error("Excel生成エラー", e, "FILE")
                    st.error(f"Excel生成エラー: {e}")
                    import traceback
                    with st.expander("詳細エラー"):
                        st.code(traceback.format_exc())
    else:
        st.warning("⚠️ Excelテンプレートが見つかりません")
        st.caption(f"パス: {template_path}")

    # ── 案件保存 ───────────────────────────────────────────────
    st.markdown("---")
    from core.estimate_storage import save_estimate as _save_est
    _saved_key = "estimate_saved_id"
    if st.session_state.get(_saved_key):
        st.info(f"💾 保存済み（ID: {st.session_state[_saved_key]}）")
    if st.button("💾 この見積りを案件履歴に保存", use_container_width=True, key="save_estimate_btn"):
        # A3-0b-1: 図面等の実体ファイルはこの保存タイミングでのみ永続化する
        # A3-0b-2: canvas_states（手動計測キャンバスの状態）も同じタイミングでJSON内へ保存する
        #          （読込・session_stateへの復元はA3-0b-3の対象のため、ここでは扱わない）
        _drawing_materials = {
            "pdf":               st.session_state.get("pdf_bytes"),
            "floor_plan":        st.session_state.get("floor_plan_bytes"),
            "photos":            st.session_state.get("photo_bytes_list") or [],
            "drawing_annotated": st.session_state.get("drawing_annotated_img"),
            "drawing_page1_raw": st.session_state.get("drawing_page1_raw"),
            "trace_3d":          st.session_state.get("_3d_trace_png"),
            "step3_drawings":    st.session_state.get("step3_drawing_files") or [],
        }
        try:
            _eid = _save_est(
                company_id=st.session_state.company_id,
                project=st.session_state.get("project", {}),
                quantities=st.session_state.get("quantities", {}),
                estimation=st.session_state.get("estimation", {}),
                estimation_sheet_data=st.session_state.get("estimation_sheet_data"),
                drawing_materials=_drawing_materials,
                canvas_states=st.session_state.get("canvas_states") or {},
            )
            st.session_state[_saved_key] = _eid
            st.success(f"✅ 案件を保存しました")
        except Exception as e:
            log_error("案件保存エラー", e, "FILE")
            st.error("保存に失敗しました。もう一度お試しください。")

    # ── アクションボタン ─────────────────────────────────────
    st.markdown("---")
    b1, b2 = st.columns(2)
    with b1:
        if st.button("← 数量を確認・修正する", use_container_width=True):
            log_ui("STEP5→STEP4: 数量確認に戻る")
            st.session_state.step = 4
            st.rerun()
    with b2:
        if st.button("🆕 新しい案件を作成", type="primary", use_container_width=True):
            log_ui("STEP4: 新規案件作成")
            for k in CASE_RESET_KEYS:
                if k in st.session_state:
                    del st.session_state[k]
            st.session_state.step = 1
            st.rerun()

    # ── デバッグ ─────────────────────────────────────────────
    with st.expander("🔍 デバッグ情報（GPTログ）"):
        _dbg_tab1, _dbg_tab2, _dbg_tab3, _dbg_tab4, _dbg_tab5 = st.tabs(
            ["📐 図面解析", "🎤 音声抽出", "🏠 3D解析", "📊 積算結果", "🏗️ Building Model"])

        with _dbg_tab1:
            st.markdown("**図面解析 生データ（GPT-4o返答）**")
            drawing_dbg = st.session_state.get("drawing_data", {})
            ann_count = drawing_dbg.get("_annotations_count", "未実行")
            raw_resp  = drawing_dbg.get("_raw_gpt_response", "")
            st.metric("annotations 取得件数", ann_count)
            if raw_resp:
                st.markdown("**GPT-4o 生テキスト（JSONパース前）**")
                st.code(raw_resp, language="json")
            else:
                st.info("図面解析未実行 or 生テキスト未取得")
            draw_err = drawing_dbg.get("_draw_error")
            if draw_err:
                st.error(f"マーカー描画エラー: {draw_err}")
            st.markdown("**パース済みデータ**")
            st.json({k: v for k, v in drawing_dbg.items()
                     if not k.startswith("_raw")})

        with _dbg_tab2:
            st.markdown("**音声抽出 GPT-4o 生テキスト**")
            _voice_raw = st.session_state.get("_voice_gpt_raw", "")
            if _voice_raw:
                st.code(_voice_raw, language="json")
            else:
                st.info("音声抽出未実行")
            _vr = st.session_state.get("voice_raw", {})
            if _vr:
                st.markdown("**パース済みRAW dict**")
                st.json(_vr)

        with _dbg_tab3:
            st.markdown("**3D解析 GPT-4o 生テキスト**")
            _3d_raw = st.session_state.get("_3d_gpt_raw", "")
            if _3d_raw:
                st.code(_3d_raw, language="json")
            else:
                st.info("3D解析未実行")
            _3d_data = st.session_state.get("building_3d_data", {})
            if _3d_data:
                st.markdown("**パース済み建物データ**")
                st.json({k: v for k, v in _3d_data.items()
                         if not k.startswith("_raw")})

        with _dbg_tab4:
            st.json(estimation)
        with _dbg_tab5:
            st.markdown("**Building Model v1.0（Step A 確認用）**")
            _bm_dbg = st.session_state.get("building_model")
            if _bm_dbg is None:
                st.info("Building Model 未生成（図面PDFが解析されていません）")
            elif "_error" in _bm_dbg:
                st.error("Building Model 生成エラー: " + str(_bm_dbg.get("_error")))
            else:
                _bm_faces = _bm_dbg.get("faces", {})
                _bm_roof  = _bm_dbg.get("roof", {})
                _bm_meta  = _bm_dbg.get("_meta", {})
                st.caption("annotations取得件数: {} | GPT全体confidence: {}".format(
                    _bm_meta.get("annotation_count", "?"),
                    _bm_meta.get("gpt_overall_confidence", "?"),
                ))
                _bm_rows = []
                for _fn, _fd in _bm_faces.items():
                    _w = _fd.get("width", {})
                    _h = _fd.get("eave_height", {})
                    _bm_rows.append({
                        "面": _fn,
                        "面幅value": _w.get("value"),
                        "面幅source": _w.get("source"),
                        "面幅confidence": _w.get("confidence"),
                        "軒高value": _h.get("value"),
                    })
                import pandas as pd
                st.dataframe(pd.DataFrame(_bm_rows), hide_index=True, use_container_width=True)
                _bm_rh = _bm_roof.get("ridge_height", {})
                _bm_rs = _bm_roof.get("shape", {})
                _bm_wc = _bm_dbg.get("water_cutoff", {}).get("perimeter_m", {})
                st.markdown("**棟高さ**: {} ({}) | **屋根形状**: {} ({}) | **外周(水切参考)**: {}m".format(
                    _bm_rh.get("value"), _bm_rh.get("confidence"),
                    _bm_rs.get("value"), _bm_rs.get("confidence"),
                    _bm_wc.get("value"),
                ))
                with st.expander("Building Model フルJSON"):
                    st.json(_bm_dbg)

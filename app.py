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
    "theme":                 "スタンダード",
}
for _k, _v in DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

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
    step_labels = ["① 現場メモ入力", "② AI自動積算", "③ 詳細確認（任意）", "④ 見積書出力"]
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
        for k in ["step", "project", "drawing_data", "image_data",
                  "quantities", "estimation", "voice_memo",
                  "voice_extras", "voice_raw", "auto_done",
                  "correction_history", "last_correction",
                  "correction_input", "pdf_bytes", "photo_bytes_list"]:
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
            st.success("保存しました")

    if st.button("💰 単価設定", use_container_width=True, key="open_price_settings"):
        st.session_state.show_price_settings = not st.session_state.get("show_price_settings", False)

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
                            st.session_state.step = 4
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
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

st.title("🏠 AI塗装積算システム")

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
            st.session_state.unit_prices = _new_prices
            st.session_state.show_price_settings = False
            from core.auth import save_unit_prices
            save_unit_prices(st.session_state.company_id, _new_prices)
            st.success("単価を保存しました")
            st.rerun()
    with c2:
        if st.button("✕ キャンセル", use_container_width=True):
            st.session_state.show_price_settings = False
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
                    st.success("文字起こし完了！右の欄に反映しました。")
                    st.rerun()
                except Exception as e:
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
            opt_soffit_sqm  = st.number_input("軒天（玄関・バルコニー ㎡）", min_value=0.0,
                                value=float(eo.get("soffit_sqm", 0)), step=0.5)
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
            "soffit_sqm":         opt_soffit_sqm,
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
            if photo_files:
                st.session_state["photo_bytes_list"] = [f.getvalue() for f in photo_files]
            elif "photo_bytes_list" in st.session_state:
                del st.session_state["photo_bytes_list"]
            st.session_state.voice_memo = voice_memo
            st.session_state.auto_done  = False
            st.session_state.step = 2
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

    def _merge_drawing(q, drawing_data):
        """図面で得た面積を、音声で未入力(0)の項目だけ補完する。"""
        wall = drawing_data.get("exterior_wall_area")
        roof = drawing_data.get("roof_area")
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
            st.session_state.step = 3
            st.rerun()
        if st.button("← 入力に戻る"):
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
                        quantities = _merge_drawing(quantities, drawing_data)

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
                    if eo.get("soffit_sqm", 0):
                        quantities["soffit_sqm"]        = eo["soffit_sqm"]
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
                    st.rerun()

                except Exception as e:
                    st.error(f"自動積算エラー: {e}")
                    st.info("APIキー未設定などの場合は、下のボタンで手動入力に切り替えできます。")

        if st.button("✏️ 手動入力で進める（AIを使わない）"):
            from core.voice_extractor import build_quantities
            st.session_state.quantities = build_quantities({})
            st.session_state.step = 3
            st.rerun()
        if st.button("← 入力に戻る"):
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
                            st.session_state[_k_pts].append({
                                "label": p["label"], "x1": p["x1"], "y1": p["y1"],
                                "x2": cx, "y2": cy,
                                "px_disp": round(px_len, 1),
                                "px_orig": round(px_len * _scale_r, 1),
                            })
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
                                        for _lab, _key in _reflect.items():
                                            if _lab in _label_vals:
                                                st.session_state[_key] = _label_vals[_lab]
                                        st.success("✅ 幾何学計算フォームに反映しました")
                                        # 下の計算フォームへ反映するためページ全体を再実行
                                        st.rerun()
                        else:
                            st.info("最初に「縮尺基準線」を計測してください（既知の寸法線の上）")

                    # リセットボタン
                    if st.button("🗑️ 計測をリセット", use_container_width=True, key=f"{ns}_reset"):
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
                        with st.expander("🏗 AI 3D変換（Beta）— GPT-4oが図面を読んで3Dモデルを生成", expanded=False):
                            st.caption("図面画像をGPT-4o Visionに送信 → 壁・屋根・開口部を推定 → Three.jsで3D建物を表示。処理時間: 15〜30秒")
                            if st.button("🔮 3D変換開始", type="primary", key="btn_3d_convert"):
                                with st.spinner("GPT-4oが図面を解析中…（壁・屋根・窓の位置を推定しています）"):
                                    try:
                                        from core.building_3d_generator import analyze_drawing_3d, generate_building_3d_html
                                        from modules.llm_client import _get_api_key
                                        _api_key = _get_api_key()
                                        _bldg_data = analyze_drawing_3d(drawing_img_bytes, _api_key)
                                        if "error" in _bldg_data:
                                            st.error(f"解析エラー: {_bldg_data['error']}")
                                        else:
                                            st.session_state["building_3d_data"] = _bldg_data
                                            st.success(f"解析完了: {_bldg_data.get('building_type','')} / {_bldg_data.get('note','')}")
                                    except Exception as _e3d:
                                        st.error(f"3D変換エラー: {_e3d}")
                            _bdata = st.session_state.get("building_3d_data")
                            if _bdata and "error" not in _bdata:
                                from core.building_3d_generator import generate_building_3d_html
                                _html3d = generate_building_3d_html(_bdata, canvas_height=600)
                                import streamlit.components.v1 as _comp3d
                                _comp3d.html(_html3d, height=620, scrolling=False)
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
        edit_soffit = ec4.number_input("軒天（m）",           min_value=0.0, value=float(q.get("soffit_length", 0)),     step=0.5)
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
            q["soffit_length"]      = edit_soffit
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
                            st.rerun()
                        else:
                            st.info(
                                "変更点が見つかりませんでした"
                                f"（{result.get('explanation', '')}）"
                            )
                    except Exception as e:
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
        b1, b2 = st.columns(2)
        with b1:
            if st.button("📝 詳細を確認・修正する", use_container_width=True):
                st.session_state.step = 3
                st.rerun()
        with b2:
            if st.button("✅ この内容で見積書へ →", type="primary", use_container_width=True):
                st.session_state.step = 4
                st.rerun()
        if st.button("← 入力に戻る"):
            st.session_state.step = 1
            st.rerun()


# ═════════════════════════════════════════════════════════════
# STEP 3: 数量確認フォーム
# ═════════════════════════════════════════════════════════════
elif st.session_state.step == 3:
    st.header("③ 数量確認フォーム")
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
            soffit_length       = st.number_input("軒天（m換算）",
                min_value=0.0, value=float(q.get("soffit_length", 0)), step=0.5)
            soffit_sqm          = st.number_input("軒天（玄関・バルコニー ㎡）",
                min_value=0.0, value=float(q.get("soffit_sqm", 0)), step=0.5)
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
                "soffit_length":      soffit_length,
                "soffit_sqm":         soffit_sqm,
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
            st.session_state.step = 4
            st.rerun()

    if st.button("← 自動積算に戻る"):
        st.session_state.step = 2
        st.rerun()


# ═════════════════════════════════════════════════════════════
# STEP 4: 見積書出力
# ═════════════════════════════════════════════════════════════
elif st.session_state.step == 4:
    st.header("④ 見積書完成")

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
                    st.success(f"✅ 見積書・積算集計表を生成しました！")

                except Exception as e:
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
        _eid = _save_est(
            company_id=st.session_state.company_id,
            project=st.session_state.get("project", {}),
            quantities=st.session_state.get("quantities", {}),
            estimation=st.session_state.get("estimation", {}),
            estimation_sheet_data=st.session_state.get("estimation_sheet_data"),
        )
        st.session_state[_saved_key] = _eid
        st.success(f"✅ 案件を保存しました")

    # ── アクションボタン ─────────────────────────────────────
    st.markdown("---")
    b1, b2 = st.columns(2)
    with b1:
        if st.button("← 数量を確認・修正する", use_container_width=True):
            st.session_state.step = 3
            st.rerun()
    with b2:
        if st.button("🆕 新しい案件を作成", type="primary", use_container_width=True):
            for k in ["step", "project", "drawing_data", "image_data",
                      "quantities", "estimation", "pdf_bytes",
                      "photo_bytes_list", "voice_memo",
                      "voice_extras", "voice_raw", "auto_done",
                      "correction_history", "last_correction",
                      "correction_input"]:
                if k in st.session_state:
                    del st.session_state[k]
            st.session_state.step = 1
            st.rerun()

    # ── デバッグ ─────────────────────────────────────────────
    with st.expander("🔍 デバッグ情報"):
        st.json(estimation)
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

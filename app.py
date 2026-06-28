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
        "基礎塗装":         ("基礎塗装（式）", "塗装工事（付帯部）"),
        "目地シーリング":   ("目地シーリング（m）", "シーリング工事"),
        "雑シーリング":     ("雑シーリング（式）", "シーリング工事"),
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
            elif "pdf_bytes" in st.session_state:
                del st.session_state["pdf_bytes"]
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
                        from core.drawing_analyzer import DrawingAnalyzer
                        da = DrawingAnalyzer(llm.api_key)
                        drawing_data = da.analyze(st.session_state.pdf_bytes)
                        st.session_state.drawing_data = drawing_data
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

        cc1, cc2, cc3 = st.columns(3)
        cc1.metric("外壁面積",      f"{q.get('wall_area', 0)} ㎡")
        cc2.metric("屋根面積",      f"{q.get('roof_area', 0)} ㎡")
        cc3.metric("合計（税込）",  f"¥{est.get('total', 0):,}")
        sc1, sc2, sc3 = st.columns(3)
        sc1.metric("外部足場",       f"{q.get('scaffold_area', 0)} ㎡")
        sc2.metric("破風 / 軒天",    f"{q.get('fascia_length', 0)} / {q.get('soffit_length', 0)} m")
        sc3.metric("目地シーリング", f"{q.get('joint_seal_length', 0)} m")

        if extras.get("notes"):
            st.info(f"📝 音声メモ補足: {extras['notes']}")
        st.caption(
            "※ 足場・軒天・シーリング等の未入力項目は塗装業の経験則で自動補完しています。"
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

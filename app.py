"""
塗装会社専用 AI積算・見積りシステム
メインアプリケーション（Streamlit）
"""

import json
import os
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

# パス設定
sys.path.insert(0, str(Path(__file__).parent))
load_dotenv()

CONFIG_PATH = Path(__file__).parent / "data" / "config.json"

# ─────────────────────────────────────────
# 設定ファイルの読み書き
# ─────────────────────────────────────────
def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_config(config: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

def get_api_key() -> str:
    try:
        secret_key = st.secrets.get("OPENAI_API_KEY", "")
        if secret_key:
            return secret_key
    except Exception:
        pass
    if st.session_state.get("api_key"):
        return st.session_state["api_key"]
    config = load_config()
    if config.get("openai_api_key"):
        return config["openai_api_key"]
    return os.getenv("OPENAI_API_KEY", "")

# ─────────────────────────────────────────
# ページ設定
# ─────────────────────────────────────────
st.set_page_config(
    page_title="AI積算・見積りシステム",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─────────────────────────────────────────
# ログイン画面
# ─────────────────────────────────────────
def show_login_page():
    st.markdown("""
    <style>
        [data-testid="stSidebar"] { display: none; }
        .login-title {
            text-align: center;
            color: #1a73e8;
            font-size: 1.8rem;
            font-weight: bold;
            margin-bottom: 4px;
        }
        .login-subtitle {
            text-align: center;
            color: #888;
            font-size: 0.95rem;
            margin-bottom: 32px;
        }
        .login-icon {
            text-align: center;
            font-size: 3rem;
            margin-bottom: 12px;
        }
    </style>
    """, unsafe_allow_html=True)

    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        st.markdown("")
        st.markdown("")
        st.markdown('<div class="login-icon">🏠</div>', unsafe_allow_html=True)
        st.markdown('<div class="login-title">AI積算・見積りシステム</div>', unsafe_allow_html=True)
        st.markdown('<div class="login-subtitle">塗装会社専用</div>', unsafe_allow_html=True)

        with st.form("login_form"):
            company_id = st.text_input("会社ID", placeholder="会社IDを入力")
            password   = st.text_input("パスワード", type="password", placeholder="パスワードを入力")
            submitted  = st.form_submit_button("ログイン", use_container_width=True, type="primary")

        if submitted:
            from core.auth import login as auth_login
            company = auth_login(company_id.strip(), password)
            if company:
                st.session_state["logged_in"] = True
                st.session_state["company"]    = company
                st.rerun()
            else:
                st.error("会社IDまたはパスワードが違います")

        st.markdown("---")
        st.caption("アカウント発行はシステム管理者までお問い合わせください。")

# ログイン状態チェック
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    show_login_page()
    st.stop()

# ─────────────────────────────────────────
# カスタムCSS
# ─────────────────────────────────────────
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #1a73e8 0%, #0d47a1 100%);
        color: white;
        padding: 20px 30px;
        border-radius: 12px;
        margin-bottom: 24px;
    }
    .question-card {
        background: #fff3e0;
        border-left: 4px solid #ff9800;
        padding: 12px 16px;
        border-radius: 4px;
        margin-bottom: 12px;
    }
    .total-box {
        background: #e8f5e9;
        border: 2px solid #4caf50;
        border-radius: 12px;
        padding: 20px;
        text-align: center;
    }
    .stButton > button {
        border-radius: 8px;
        font-size: 1.1rem;
        font-weight: 600;
        padding: 10px 24px;
    }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────
# セッション初期化
# ─────────────────────────────────────────
def init_session():
    defaults = {
        "step": "input",
        "project_data": {},
        "questions": [],
        "answers": {},
        "estimation": {},
        "image_bytes_list": [],
        "description": "",
        "client_name": "",
        "site_address": "",
        "sales_rep": "",
        "company_name": "",
        "template_id": "standard",
        "api_key": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_session()

if not st.session_state["api_key"]:
    saved = load_config().get("openai_api_key", "")
    if saved:
        st.session_state["api_key"] = saved

# ─────────────────────────────────────────
# サイドバー
# ─────────────────────────────────────────
company_info = st.session_state.get("company", {})

with st.sidebar:
    st.markdown(f"### 🏢 {company_info.get('company_name', '')}")
    st.caption(f"{company_info.get('department', '')}　{company_info.get('contact_name', '')}")

    if st.button("🚪 ログアウト", use_container_width=True):
        st.session_state["logged_in"] = False
        st.session_state["company"]   = {}
        st.rerun()

    st.markdown("---")

    # 会社情報編集
    with st.expander("🏢 会社情報を編集"):
        from core.auth import update_company_info
        cid = company_info.get("id", "")
        f_company  = st.text_input("会社名",   company_info.get("company_name", ""), key="s_company")
        f_dept     = st.text_input("部署名",   company_info.get("department", ""),   key="s_dept")
        f_contact  = st.text_input("担当者名", company_info.get("contact_name", ""), key="s_contact")
        f_tel      = st.text_input("TEL",      company_info.get("tel", ""),           key="s_tel")
        f_fax      = st.text_input("FAX",      company_info.get("fax", ""),           key="s_fax")
        f_address  = st.text_input("住所",     company_info.get("address", ""),       key="s_addr")
        if st.button("💾 保存", use_container_width=True, key="save_company"):
            updates = {
                "company_name": f_company,
                "department":   f_dept,
                "contact_name": f_contact,
                "tel":          f_tel,
                "fax":          f_fax,
                "address":      f_address,
            }
            update_company_info(cid, updates)
            st.session_state["company"].update(updates)
            st.success("保存しました")
            st.rerun()

    # パスワード変更
    with st.expander("🔑 パスワード変更"):
        from core.auth import change_password
        old_pw  = st.text_input("現在のパスワード",       type="password", key="old_pw")
        new_pw  = st.text_input("新しいパスワード",       type="password", key="new_pw")
        new_pw2 = st.text_input("新しいパスワード（確認）", type="password", key="new_pw2")
        if st.button("変更する", use_container_width=True, key="change_pw"):
            if new_pw != new_pw2:
                st.error("パスワードが一致しません")
            elif len(new_pw) < 6:
                st.error("6文字以上で設定してください")
            elif change_password(cid, old_pw, new_pw):
                st.success("パスワードを変更しました")
            else:
                st.error("現在のパスワードが違います")

    st.markdown("---")

    # APIキー設定
    st.markdown("### 🔑 OpenAI APIキー")
    _secret_key_set = False
    try:
        _secret_key_set = bool(st.secrets.get("OPENAI_API_KEY", ""))
    except Exception:
        pass

    if _secret_key_set:
        st.success("✅ APIキー設定済み（管理者設定）")
    else:
        current_key = st.session_state.get("api_key", "")
        if current_key:
            st.success(f"✅ 設定済み（sk-...{current_key[-6:]}）")
        else:
            st.warning("⚠️ 未設定")
        new_key = st.text_input("APIキーを入力", type="password", placeholder="sk-xxxxxxxxxxxxxxxx")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("💾 保存", use_container_width=True, disabled=not new_key, key="save_api"):
                if new_key.startswith("sk-"):
                    st.session_state["api_key"] = new_key
                    cfg = load_config(); cfg["openai_api_key"] = new_key; save_config(cfg)
                    st.success("保存しました"); st.rerun()
                else:
                    st.error("sk- で始まるキーを入力してください")
        with c2:
            if st.button("🗑️ 削除", use_container_width=True, disabled=not current_key, key="del_api"):
                st.session_state["api_key"] = ""
                cfg = load_config(); cfg.pop("openai_api_key", None); save_config(cfg)
                st.rerun()

    st.markdown("---")
    st.caption("塗装会社専用 AI積算システム v1.0")


# ─────────────────────────────────────────
# ヘッダー
# ─────────────────────────────────────────
st.markdown("""
<div class="main-header">
    <h2 style="margin:0">🏠 AI積算・見積りシステム</h2>
    <p style="margin:4px 0 0 0; opacity:0.85">写真と説明だけで見積書を自動作成</p>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────
# APIキー未設定ガード
# ─────────────────────────────────────────
api_key = get_api_key()
if not api_key:
    st.error("⚠️ OpenAI APIキーが設定されていません。")
    st.info("👈 左のサイドバーを開いて「設定」からAPIキーを入力してください。")
    st.stop()


# ─────────────────────────────────────────
# モジュール遅延インポート
# ─────────────────────────────────────────
@st.cache_resource(hash_funcs={str: lambda x: x})
def load_modules(api_key: str):
    from modules.llm_client import LLMClient
    from modules.image_analyzer import ImageAnalyzer
    from modules.question_engine import QuestionEngine
    from core.estimation_engine import EstimationEngine
    from core.quote_generator import QuoteGenerator

    llm = LLMClient(api_key=api_key)
    return {
        "analyzer":  ImageAnalyzer(llm),
        "questions": QuestionEngine(llm),
        "estimator": EstimationEngine(llm),
        "generator": QuoteGenerator(),
    }


# ─────────────────────────────────────────
# ステップ表示バー
# ─────────────────────────────────────────
STEPS = {
    "input":      ("① 入力",     "📸"),
    "analyzing":  ("② 解析中",   "🔍"),
    "questions":  ("③ 確認",     "❓"),
    "estimating": ("④ 積算中",   "📊"),
    "result":     ("⑤ 見積完成", "✅"),
}
step_cols = st.columns(len(STEPS))
for i, (key, (label, icon)) in enumerate(STEPS.items()):
    with step_cols[i]:
        is_current = st.session_state.step == key
        style = "background:#1a73e8;color:white;padding:8px;border-radius:8px;text-align:center" \
            if is_current else "background:#f0f0f0;color:#888;padding:8px;border-radius:8px;text-align:center"
        st.markdown(f'<div style="{style}">{icon} {label}</div>', unsafe_allow_html=True)

st.markdown("---")


# ═══════════════════════════════════════════
# STEP 1: 入力画面
# ═══════════════════════════════════════════
if st.session_state.step == "input":

    st.markdown("### 📸 現場情報を入力してください")
    col1, col2 = st.columns([3, 2])

    with col1:
        # テンプレート選択
        from core.template_manager import list_templates
        templates   = list_templates()
        tmpl_ids    = [t["id"]   for t in templates]
        tmpl_labels = [t["name"] for t in templates]
        cur_idx     = tmpl_ids.index(st.session_state.template_id) if st.session_state.template_id in tmpl_ids else 0
        sel_label   = st.selectbox("📋 見積テンプレート", tmpl_labels, index=cur_idx)
        st.session_state.template_id = tmpl_ids[tmpl_labels.index(sel_label)]

        # 案件基本情報
        st.markdown("**案件情報**（任意）")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.session_state.client_name  = st.text_input("お客様名", st.session_state.client_name,  placeholder="山田太郎様")
        with c2:
            st.session_state.company_name = st.text_input("受注先",   st.session_state.company_name, placeholder="〇〇建設㈱")
        with c3:
            st.session_state.site_address = st.text_input("現場住所", st.session_state.site_address, placeholder="東京都〇〇区...")
        with c4:
            st.session_state.sales_rep    = st.text_input("担当者",   st.session_state.sales_rep,    placeholder="鈴木")

        st.markdown("**現場写真**（10〜30枚推奨）")
        uploaded_files = st.file_uploader(
            "写真をアップロード",
            type=["jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True,
            help="外壁・屋根・軒天・雨樋など各部位の写真をまとめてアップロード",
        )
        if uploaded_files:
            st.session_state.image_bytes_list = [f.read() for f in uploaded_files]
            st.success(f"✅ {len(uploaded_files)}枚の写真を読み込みました")
            thumb_cols = st.columns(min(6, len(uploaded_files)))
            for col, file in zip(thumb_cols, uploaded_files[:6]):
                with col:
                    st.image(file, use_container_width=True)
            if len(uploaded_files) > 6:
                st.caption(f"他 {len(uploaded_files) - 6} 枚")

    with col2:
        st.markdown("**営業担当からの説明**")
        st.session_state.description = st.text_area(
            "施工内容・要望を入力",
            st.session_state.description,
            height=280,
            placeholder="例：\n・外壁のみ塗装\n・屋根は塗らない\n・雨樋全部塗る\n・2階建て木造\n・外壁面積は約120㎡くらい",
            help="音声入力後にテキストをペーストも可能",
        )

        st.markdown("**入力チェック**")
        has_images = len(st.session_state.image_bytes_list) > 0
        has_desc   = len(st.session_state.description.strip()) > 10

        if has_images:
            st.success(f"📸 写真: {len(st.session_state.image_bytes_list)}枚")
        else:
            st.warning("📸 写真: 未アップロード（テキストのみでも可）")

        if has_desc:
            st.success("📝 説明: 入力済み")
        else:
            st.warning("📝 説明: 未入力（写真のみでも可）")

        if st.button("🚀 AI解析スタート", type="primary", disabled=not (has_images or has_desc), use_container_width=True):
            st.session_state.step = "analyzing"
            st.rerun()


# ═══════════════════════════════════════════
# STEP 2: 解析中
# ═══════════════════════════════════════════
elif st.session_state.step == "analyzing":
    st.markdown("### 🔍 現場情報を解析中...")
    modules = load_modules(get_api_key())

    with st.spinner("写真と説明をAIが解析しています（30秒〜1分）..."):
        try:
            result = modules["analyzer"].analyze(
                image_bytes_list=st.session_state.image_bytes_list,
                description=st.session_state.description,
            )
            st.session_state.project_data = result
            q_result = modules["questions"].generate_questions(result)
            st.session_state.questions = q_result.get("questions", [])

            if q_result.get("ready_to_estimate"):
                st.session_state.step = "estimating"
            else:
                st.session_state.step = "questions"
            st.rerun()

        except Exception as e:
            st.error(f"解析エラー: {e}")
            if st.button("最初に戻る"):
                st.session_state.step = "input"; st.rerun()


# ═══════════════════════════════════════════
# STEP 3: 不足情報の質問
# ═══════════════════════════════════════════
elif st.session_state.step == "questions":
    st.markdown("### ❓ 確認が必要な項目があります")
    st.info("以下の項目を確認して積算精度を上げてください。すべてスキップすることもできます。")

    project = st.session_state.project_data
    scope   = project.get("scope", {})

    with st.expander("📋 解析済み情報を確認", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**建物概要**")
            overview = project.get("building_overview", {})
            st.write(f"種別: {overview.get('type', '不明')}")
            st.write(f"構造: {overview.get('structure', '不明')}")
            st.write(f"階数: {overview.get('floors', '不明')}")
        with c2:
            st.markdown("**施工範囲**")
            scope_labels = {
                "exterior_wall": "外壁", "roof": "屋根", "soffit": "軒天",
                "fascia": "破風", "gutters": "雨樋", "sealing": "シーリング",
                "scaffold": "足場", "high_pressure_wash": "高圧洗浄",
            }
            for key, label in scope_labels.items():
                val = scope.get(key)
                if val is True:  st.write(f"✅ {label}")
                elif val is False: st.write(f"❌ {label}")

    questions = st.session_state.questions
    if not questions:
        st.session_state.step = "estimating"; st.rerun()

    answers = {}
    st.markdown(f"**{len(questions)}件の確認事項**")

    for i, q in enumerate(questions):
        st.markdown(f'<div class="question-card">❓ {q.get("question", "")}</div>', unsafe_allow_html=True)
        q_type    = q.get("type", "text")
        field_key = q.get("field_key", f"q{i}")
        cur_val   = st.session_state.answers.get(field_key, "")

        if q_type == "yes_no":
            options = ["未回答", "はい（する）", "いいえ（しない）"]
            sel = st.selectbox("", options, key=f"q_{i}", label_visibility="collapsed")
            if sel == "はい（する）":   answers[field_key] = True
            elif sel == "いいえ（しない）": answers[field_key] = False
        elif q_type == "number":
            val = st.number_input("", min_value=0.0, value=float(cur_val) if cur_val else 0.0, step=0.5, key=f"q_{i}", label_visibility="collapsed")
            if val > 0: answers[field_key] = val
        elif q_type == "select":
            opts = ["未回答"] + q.get("options", [])
            sel = st.selectbox("", opts, key=f"q_{i}", label_visibility="collapsed")
            if sel != "未回答": answers[field_key] = sel
        else:
            val = st.text_input("", cur_val, key=f"q_{i}", label_visibility="collapsed")
            if val: answers[field_key] = val
        st.markdown("")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("⏭️ スキップして積算する", use_container_width=True):
            st.session_state.step = "estimating"; st.rerun()
    with c2:
        if st.button("✅ 回答を確定して積算する", type="primary", use_container_width=True):
            st.session_state.answers.update(answers)
            modules  = load_modules(get_api_key())
            updated  = modules["questions"].apply_answers(st.session_state.project_data, answers)
            st.session_state.project_data = updated
            st.session_state.step = "estimating"; st.rerun()


# ═══════════════════════════════════════════
# STEP 4: 積算中
# ═══════════════════════════════════════════
elif st.session_state.step == "estimating":
    st.markdown("### 📊 積算中...")
    modules = load_modules(get_api_key())

    with st.spinner("数量・金額を計算しています（30秒〜1分）..."):
        try:
            estimation = modules["estimator"].calculate(st.session_state.project_data)
            st.session_state.estimation = estimation
            st.session_state.step = "result"; st.rerun()
        except Exception as e:
            st.error(f"積算エラー: {e}")
            if st.button("確認ステップに戻る"):
                st.session_state.step = "questions"; st.rerun()


# ═══════════════════════════════════════════
# STEP 5: 結果表示
# ═══════════════════════════════════════════
elif st.session_state.step == "result":
    estimation = st.session_state.estimation
    items      = estimation.get("estimation_items", [])

    st.markdown("### ✅ 積算・見積書")
    info_cols = st.columns(3)
    with info_cols[0]: st.metric("お客様", st.session_state.client_name or "未設定")
    with info_cols[1]: st.metric("現場",   st.session_state.site_address or "未設定")
    with info_cols[2]: st.metric("担当",   st.session_state.sales_rep or company_info.get("contact_name", "未設定"))

    st.markdown("---")

    total    = estimation.get("total",    0)
    subtotal = estimation.get("subtotal", 0)
    tax      = estimation.get("tax_amount", 0)

    sum_cols = st.columns(3)
    with sum_cols[0]: st.metric("小計（税抜）",  f"¥{subtotal:,}")
    with sum_cols[1]: st.metric("消費税（10%）", f"¥{tax:,}")
    with sum_cols[2]:
        st.markdown(f"""
<div class="total-box">
    <div style="font-size:0.9rem;color:#555">税込合計</div>
    <div style="font-size:2rem;font-weight:bold;color:#2e7d32">¥{total:,}</div>
</div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 📋 積算明細")

    if items:
        import pandas as pd
        df_data = []
        for item in items:
            estimated  = item.get("estimated", False)
            needs_conf = item.get("needs_confirmation", False)
            status = "⚠️ 要確認" if needs_conf else ("📊 推定" if estimated else "✅ 確定")
            df_data.append({
                "工種":      item.get("category", ""),
                "品目":      item.get("item_name", ""),
                "数量":      item.get("quantity", 0),
                "単位":      item.get("unit", ""),
                "単価（円）": f"¥{item.get('unit_price', 0):,}",
                "金額（円）": f"¥{item.get('amount', 0):,}",
                "ステータス": status,
                "備考":      item.get("notes", "") or item.get("basis", ""),
            })
        st.dataframe(pd.DataFrame(df_data), use_container_width=True, hide_index=True)

    confirm_items = estimation.get("confirmation_items", [])
    if confirm_items:
        st.markdown("### ⚠️ 要確認事項")
        for ci in confirm_items:
            st.warning(ci)

    st.markdown("---")
    st.markdown("### 📥 見積書出力")
    out_cols = st.columns(3)

    with out_cols[0]:
        if st.button("📊 テンプレートExcel出力", type="primary", use_container_width=True):
            try:
                modules = load_modules(get_api_key())
                ci = st.session_state.get("company", {})
                excel_path = modules["generator"].generate_from_template(
                    template_id  = st.session_state.get("template_id", "standard"),
                    estimation   = st.session_state.estimation,
                    project_data = st.session_state.project_data,
                    client_name  = st.session_state.client_name,
                    site_address = st.session_state.site_address,
                    sales_rep    = st.session_state.sales_rep or ci.get("contact_name", ""),
                    company_name = st.session_state.company_name or ci.get("company_name", ""),
                )
                with open(excel_path, "rb") as f:
                    st.download_button(
                        "⬇️ Excelをダウンロード", f.read(),
                        file_name=Path(excel_path).name,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                st.success("✅ テンプレート形式でExcel見積書を作成しました")
            except Exception as e:
                st.error(f"Excel出力エラー: {e}")

    with out_cols[1]:
        if st.button("📄 PDF出力", use_container_width=True):
            try:
                modules = load_modules(get_api_key())
                pdf_path = modules["generator"].generate_pdf(
                    estimation   = st.session_state.estimation,
                    project_data = st.session_state.project_data,
                    client_name  = st.session_state.client_name,
                    site_address = st.session_state.site_address,
                    sales_rep    = st.session_state.sales_rep,
                )
                with open(pdf_path, "rb") as f:
                    st.download_button(
                        "⬇️ PDFをダウンロード", f.read(),
                        file_name=Path(pdf_path).name,
                        mime="application/pdf",
                    )
                st.success("PDF見積書を作成しました")
            except Exception as e:
                st.error(f"PDF出力エラー: {e}")

    with out_cols[2]:
        if st.button("🔄 新規案件を入力", use_container_width=True):
            for key in list(st.session_state.keys()):
                if key not in ("logged_in", "company", "api_key"):
                    del st.session_state[key]
            st.rerun()

    with st.expander("🔧 詳細データ（デバッグ用）"):
        import json as _json
        st.json(estimation)

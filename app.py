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
from core.template_filler import fill_template

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
}
for _k, _v in DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ─────────────────────────────────────────────────────────────
# ログイン
# ─────────────────────────────────────────────────────────────
if not st.session_state.logged_in:
    show_login_page()
    st.stop()

# ─────────────────────────────────────────────────────────────
# サイドバー
# ─────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"### 🏢 {st.session_state.company_name or ''}様")
    st.markdown("---")
    step_labels = ["① 案件情報入力", "② AI解析", "③ 数量確認", "④ 見積書出力"]
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
                  "pdf_bytes", "photo_bytes_list"]:
            if k in st.session_state:
                del st.session_state[k]
        st.session_state.step = 1
        st.rerun()
    if st.button("🚪 ログアウト", use_container_width=True):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

st.title("🏠 AI塗装積算システム")


# ═════════════════════════════════════════════════════════════
# STEP 1: 案件情報入力
# ═════════════════════════════════════════════════════════════
if st.session_state.step == 1:
    st.header("① 案件情報入力")
    st.caption("お客様情報・建物情報・資料をご入力ください")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("👤 お客様・案件情報")
        client_name   = st.text_input("お客様名 ＊", placeholder="例：住吉屋 栄子 様")
        site_address  = st.text_input("現場住所 ＊", placeholder="例：東京都世田谷区…")
        sales_rep     = st.text_input("担当者名",    placeholder="例：山田 太郎")
        project_name  = st.text_input("工事件名",    placeholder="例：外壁・屋根塗装工事")

        st.subheader("🏗️ 建物基本情報")
        building_type   = st.selectbox("建物種別",
                            ["戸建て", "共同住宅", "マンション", "店舗・工場"])
        building_floors = st.number_input("階数", min_value=1, max_value=10, value=2, step=1)
        building_area   = st.number_input("建築面積（㎡）", min_value=0.0,
                            value=0.0, step=1.0,
                            help="わかる場合のみ入力。AI解析時に参照します。")

    with col2:
        st.subheader("📄 図面・写真のアップロード")
        pdf_file = st.file_uploader(
            "図面PDF（任意）", type=["pdf"],
            help="平面図・立面図等をアップロードするとAIが面積を自動計算します",
        )
        photo_files = st.file_uploader(
            "現場写真（任意・複数可）",
            type=["jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True,
            help="外壁・屋根・付帯部の写真をアップロードすると劣化状況も解析します",
        )

        st.subheader("🎤 音声メモ（任意）")
        audio_input = st.audio_input("現地調査メモを音声で入力")
        if audio_input is not None:
            if st.button("文字起こし実行"):
                with st.spinner("音声を文字起こし中…"):
                    try:
                        from modules.llm_client import LLMClient
                        llm = LLMClient()
                        text = llm.transcribe_audio(audio_input.getvalue(), "memo.webm")
                        st.session_state.voice_memo = text
                        st.success("文字起こし完了！")
                    except Exception as e:
                        st.error(f"文字起こし失敗: {e}")

        voice_memo = st.text_area(
            "現地メモ（音声文字起こし or 手入力）",
            value=st.session_state.voice_memo,
            height=120,
            placeholder="外壁の劣化状況、施工範囲、特記事項など自由に入力",
        )

    st.markdown("---")
    st.subheader("🔧 施工範囲（該当するものにチェック）")
    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        do_roof        = st.checkbox("屋根塗装",       value=True)
        do_wall        = st.checkbox("外壁塗装",       value=True)
        do_fascia      = st.checkbox("破風・鼻隠し",   value=True)
        do_soffit      = st.checkbox("軒天",           value=True)
    with sc2:
        do_gutter      = st.checkbox("雨樋",           value=True)
        do_sealing     = st.checkbox("シーリング",     value=True)
        do_foundation  = st.checkbox("基礎塗装",       value=False)
        do_shutter_box = st.checkbox("シャッターボックス", value=False)
    with sc3:
        do_protection  = st.checkbox("防護管",         value=False)
        do_guardman    = st.checkbox("ガードマン",     value=False)
        do_water_cutoff = st.checkbox("土台水切",      value=True)
        do_window_top  = st.checkbox("出窓天端",       value=False)

    if st.button("次へ → AI解析開始", type="primary", use_container_width=True):
        if not client_name:
            st.error("お客様名を入力してください")
        elif not site_address:
            st.error("現場住所を入力してください")
        else:
            st.session_state.project = {
                "client_name":     client_name,
                "site_address":    site_address,
                "sales_rep":       sales_rep,
                "project_name":    project_name or f"{client_name}邸 塗装工事",
                "building_type":   building_type,
                "building_floors": building_floors,
                "building_area":   building_area,
                "voice_memo":      voice_memo,
                "scope": {
                    "roof":         do_roof,
                    "wall":         do_wall,
                    "fascia":       do_fascia,
                    "soffit":       do_soffit,
                    "gutter":       do_gutter,
                    "sealing":      do_sealing,
                    "foundation":   do_foundation,
                    "shutter_box":  do_shutter_box,
                    "protection":   do_protection,
                    "guardman":     do_guardman,
                    "water_cutoff": do_water_cutoff,
                    "window_top":   do_window_top,
                },
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
            st.session_state.step = 2
            st.rerun()


# ═════════════════════════════════════════════════════════════
# STEP 2: AI解析
# ═════════════════════════════════════════════════════════════
elif st.session_state.step == 2:
    st.header("② AI解析")
    proj       = st.session_state.project
    has_pdf    = "pdf_bytes" in st.session_state
    has_photos = bool(st.session_state.get("photo_bytes_list"))

    def _build_quantities_from_analysis(drawing_data, image_data, proj):
        scope = proj.get("scope", {})
        q = {
            "do_roof":            scope.get("roof",      True),
            "do_wall":            scope.get("wall",      True),
            "do_foundation":      scope.get("foundation", False),
            "do_lifting":         True,
            "do_transport":       True,
            "do_road_permit":     True,
            "do_misc_seal":       scope.get("sealing",   True),
            "do_protection_pipe": scope.get("protection", False),
            "guardman_count":     1 if scope.get("guardman") else 0,
        }
        if drawing_data:
            wall = drawing_data.get("exterior_wall_area")
            roof = drawing_data.get("roof_area")
            if wall:
                q["wall_area"]          = float(wall)
                q["scaffold_area"]      = round(float(wall) * 1.1, 1)
                q["joint_seal_length"]  = round(float(wall) * 0.8, 1)
            if roof:
                q["roof_area"]          = float(roof)
                q["roof_scaffold_area"] = float(roof)
        if image_data and "quantities" in image_data:
            iq = image_data["quantities"]
            for src, dst in [
                ("exterior_wall_area", "wall_area"),
                ("roof_area",          "roof_area"),
                ("fascia_length",      "fascia_length"),
                ("gutter_length",      "gutter_length"),
                ("sealing_length",     "joint_seal_length"),
                ("scaffold_area",      "scaffold_area"),
            ]:
                v = iq.get(src, {})
                val = v.get("value") if isinstance(v, dict) else None
                if val and dst not in q:
                    q[dst] = float(val)
        return q

    if not has_pdf and not has_photos:
        st.info("📋 図面・写真のアップロードなし → 数量入力フォームに直接進みます")
        if st.button("数量入力フォームへ →", type="primary"):
            scope = proj.get("scope", {})
            st.session_state.quantities = _build_quantities_from_analysis({}, {}, proj)
            st.session_state.step = 3
            st.rerun()
    else:
        analyze_done = bool(st.session_state.get("drawing_data") or st.session_state.get("image_data"))

        if not analyze_done:
            if st.button("▶️ AI解析を開始する", type="primary", use_container_width=True):
                with st.spinner("AIが資料を解析中…（30秒〜1分程度）"):
                    drawing_data = {}
                    image_data   = {}
                    try:
                        from modules.llm_client import LLMClient
                        llm = LLMClient()

                        if has_pdf:
                            st.info("📐 図面PDFを解析中…")
                            from core.drawing_analyzer import DrawingAnalyzer
                            da = DrawingAnalyzer(llm)
                            drawing_data = da.analyze(st.session_state.pdf_bytes)
                            st.success(f"図面解析完了: {drawing_data.get('building_type','')} {drawing_data.get('floors','')}階")

                        if has_photos:
                            st.info("📸 現場写真を解析中…")
                            from modules.image_analyzer import ImageAnalyzer
                            ia = ImageAnalyzer(llm)
                            desc = proj.get("voice_memo", "") + f"\n建物種別: {proj.get('building_type','')}"
                            image_data = ia.analyze(st.session_state.photo_bytes_list, desc)
                            st.success("写真解析完了")

                        st.session_state.drawing_data = drawing_data
                        st.session_state.image_data   = image_data
                        st.session_state.quantities   = _build_quantities_from_analysis(
                            drawing_data, image_data, proj)
                        st.rerun()

                    except Exception as e:
                        st.error(f"AI解析エラー: {e}")
                        st.info("スキップして手動入力できます")
                        if st.button("手動入力で続行 →"):
                            st.session_state.quantities = _build_quantities_from_analysis({}, {}, proj)
                            st.session_state.step = 3
                            st.rerun()
        else:
            drawing_data = st.session_state.drawing_data
            image_data   = st.session_state.image_data
            st.success("✅ AI解析完了！")

            if drawing_data:
                st.subheader("📐 図面解析結果")
                dc1, dc2, dc3 = st.columns(3)
                dc1.metric("建物種別",     drawing_data.get("building_type", "不明"))
                dc2.metric("外壁面積（推定）", f"{drawing_data.get('exterior_wall_area', '?')} ㎡")
                dc3.metric("屋根面積（推定）", f"{drawing_data.get('roof_area', '?')} ㎡")
                if drawing_data.get("notes"):
                    st.caption(drawing_data["notes"])

            if image_data and not image_data.get("parse_error"):
                st.subheader("📸 写真解析結果")
                cond = image_data.get("conditions", {})
                if cond:
                    st.caption(f"劣化状況: {cond.get('deterioration_level','不明')} / {cond.get('notes','')}")
                missing = image_data.get("missing_info", [])
                if missing:
                    with st.expander("⚠️ 要確認事項"):
                        for m in missing:
                            st.write(f"• {m}")

            if st.button("数量確認フォームへ →", type="primary", use_container_width=True):
                st.session_state.step = 3
                st.rerun()

    if st.button("← 案件情報に戻る"):
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

    if st.button("← AI解析に戻る"):
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

                    st.download_button(
                        label=f"⬇️ {filename} をダウンロード",
                        data=excel_bytes,
                        file_name=filename,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                    )
                    st.success(f"✅ {filename} を生成しました！")

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
        if st.button("← 数量修正に戻る", use_container_width=True):
            st.session_state.step = 3
            st.rerun()
    with b2:
        if st.button("🆕 新しい案件を作成", type="primary", use_container_width=True):
            for k in ["step", "project", "drawing_data", "image_data",
                      "quantities", "estimation", "pdf_bytes",
                      "photo_bytes_list", "voice_memo"]:
                if k in st.session_state:
                    del st.session_state[k]
            st.session_state.step = 1
            st.rerun()

    # ── デバッグ ─────────────────────────────────────────────
    with st.expander("🔍 デバッグ情報"):
        st.json(estimation)

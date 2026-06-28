"""
認証モジュール
会社アカウント（会社ID＋パスワード）でのログイン管理
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

ACCOUNTS_PATH = Path(__file__).parent.parent / "data" / "accounts.json"


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _load_accounts() -> dict:
    if ACCOUNTS_PATH.exists():
        with open(ACCOUNTS_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"companies": []}


def _save_accounts(data: dict):
    ACCOUNTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ACCOUNTS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def init_default_accounts():
    """デフォルトアカウント（日紘建装）を初期登録"""
    data = _load_accounts()
    ids = [c["id"] for c in data["companies"]]
    if "nikko" not in ids:
        data["companies"].append({
            "id": "nikko",
            "company_name": "日紘建装株式会社",
            "department": "工事部",
            "contact_name": "伊藤隆一",
            "tel": "03-3417-1341",
            "fax": "03-3416-1065",
            "address": "〒157-0074 東京都世田谷区大蔵6-1-3",
            "password_hash": _hash_password("0000"),
            "created_at": datetime.now().isoformat(),
        })
        _save_accounts(data)


def login(company_id: str, password: str) -> Optional[dict]:
    """
    ログイン認証。成功時は会社情報dictを返す。失敗時はNone。
    スマホキーボードの大文字化・全角・末尾スペースに対応。
    """
    init_default_accounts()
    data = _load_accounts()
    # スマホ対応：全角→半角変換、大文字→小文字、前後スペース除去
    import unicodedata
    company_id = unicodedata.normalize("NFKC", company_id).strip().lower()
    password   = unicodedata.normalize("NFKC", password).strip()
    pw_hash = _hash_password(password)
    for company in data["companies"]:
        if company["id"] == company_id and company["password_hash"] == pw_hash:
            return company
    return None


def get_company(company_id: str) -> Optional[dict]:
    """会社IDから会社情報を取得"""
    data = _load_accounts()
    for company in data["companies"]:
        if company["id"] == company_id:
            return company
    return None


def update_company_info(company_id: str, updates: dict) -> bool:
    """会社情報を更新する（パスワード以外）"""
    data = _load_accounts()
    for company in data["companies"]:
        if company["id"] == company_id:
            # パスワードハッシュは上書きしない
            updates.pop("password_hash", None)
            updates.pop("id", None)
            company.update(updates)
            _save_accounts(data)
            return True
    return False


def change_password(company_id: str, old_password: str, new_password: str) -> bool:
    """パスワード変更"""
    data = _load_accounts()
    old_hash = _hash_password(old_password)
    for company in data["companies"]:
        if company["id"] == company_id and company["password_hash"] == old_hash:
            company["password_hash"] = _hash_password(new_password)
            _save_accounts(data)
            return True
    return False


def list_companies() -> list:
    """全会社一覧（管理者用）"""
    return _load_accounts().get("companies", [])


def add_company(company_id: str, company_name: str, password: str, **kwargs) -> bool:
    """新会社を追加"""
    data = _load_accounts()
    ids = [c["id"] for c in data["companies"]]
    if company_id in ids:
        return False
    data["companies"].append({
        "id": company_id,
        "company_name": company_name,
        "password_hash": _hash_password(password),
        "created_at": datetime.now().isoformat(),
        **kwargs,
    })
    _save_accounts(data)
    return True


def show_login_page():
    """Streamlitログイン画面を表示する"""
    import streamlit as st

    st.title("🏠 AI塗装積算システム")
    st.subheader("ログイン")

    with st.form("login_form"):
        company_id = st.text_input("会社ID", placeholder="例：nikko")
        password   = st.text_input("パスワード", type="password", placeholder="パスワードを入力")
        submitted  = st.form_submit_button("ログイン", use_container_width=True, type="primary")

        if submitted:
            if not company_id or not password:
                st.error("会社IDとパスワードを入力してください")
            else:
                company = login(company_id, password)
                if company:
                    st.session_state.logged_in    = True
                    st.session_state.company_id   = company["id"]
                    st.session_state.company_name = company.get("company_name", company_id)
                    st.rerun()
            
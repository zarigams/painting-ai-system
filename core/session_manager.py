"""
セッションマネージャー
案件ごとのデータを管理する。Streamlitのsession_stateと連携。
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional


class ProjectSession:
    """
    1案件のデータを管理するクラス
    """

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or str(uuid.uuid4())[:8]
        self.created_at = datetime.now()
        self.status = "初期入力"  # 初期入力 → 解析中 → 質問中 → 積算中 → 完了

        # 入力データ
        self.image_bytes_list: list[bytes] = []
        self.description: str = ""

        # 解析・積算結果
        self.project_data: dict = {}
        self.questions: list[dict] = []
        self.answers: dict = {}
        self.estimation_result: dict = {}

        # メタデータ
        self.client_name: str = ""
        self.site_address: str = ""
        self.sales_rep: str = ""

    def to_dict(self) -> dict:
        """セッションデータをdict化（シリアライズ用）"""
        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "status": self.status,
            "client_name": self.client_name,
            "site_address": self.site_address,
            "sales_rep": self.sales_rep,
            "description": self.description,
            "project_data": self.project_data,
            "questions": self.questions,
            "answers": self.answers,
            "estimation_result": self.estimation_result,
            "image_count": len(self.image_bytes_list),
        }

    def save_to_file(self, output_dir: str = "output") -> str:
        """案件データをJSONファイルに保存"""
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        filename = f"{output_dir}/session_{self.session_id}_{self.created_at.strftime('%Y%m%d')}.json"
        data = self.to_dict()
        # imagesはバイナリなので除外
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return filename

    @property
    def client_display_name(self) -> str:
        return self.client_name or f"案件_{self.session_id}"


class SessionManager:
    """
    複数案件セッションの管理クラス（Streamlit session_stateで使用）
    """

    def __init__(self):
        self.sessions: dict[str, ProjectSession] = {}
        self.current_session_id: Optional[str] = None

    def new_session(self) -> ProjectSession:
        """新規案件セッションを作成"""
        session = ProjectSession()
        self.sessions[session.session_id] = session
        self.current_session_id = session.session_id
        return session

    @property
    def current(self) -> Optional[ProjectSession]:
        if self.current_session_id:
            return self.sessions.get(self.current_session_id)
        return None

    def get_session(self, session_id: str) -> Optional[ProjectSession]:
        return self.sessions.get(session_id)

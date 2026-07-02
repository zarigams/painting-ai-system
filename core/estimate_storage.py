"""
案件保存・履歴管理モジュール
data/estimates/{company_id}/ 以下にJSONで保存する
"""
from __future__ import annotations
import json, uuid, os
from datetime import datetime
from pathlib import Path

_ESTIMATES_DIR = Path(__file__).parent.parent / "data" / "estimates"


def _company_dir(company_id: str) -> Path:
    d = _ESTIMATES_DIR / company_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_estimate(company_id: str, project: dict, quantities: dict,
                  estimation: dict, estimation_sheet_data: dict | None = None) -> str:
    """
    見積りデータをJSONに保存する。
    Returns: estimate_id (str)
    """
    estimate_id = uuid.uuid4().hex[:12]
    created_at  = datetime.now().strftime("%Y-%m-%d %H:%M")

    data = {
        "id":                    estimate_id,
        "created_at":            created_at,
        "company_id":            company_id,
        "project":               project,
        "quantities":            quantities,
        "estimation":            estimation,
        "estimation_sheet_data": estimation_sheet_data,
    }

    path = _company_dir(company_id) / f"{estimate_id}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return estimate_id


def list_estimates(company_id: str) -> list[dict]:
    """
    会社の保存済み案件を created_at 降順で返す（概要のみ）。
    Returns: [{"id", "created_at", "client_name", "total"}]
    """
    d = _company_dir(company_id)
    results = []
    for f in d.glob("*.json"):
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
            results.append({
                "id":          raw["id"],
                "created_at":  raw.get("created_at", ""),
                "client_name": raw.get("project", {}).get("client_name", "（不明）"),
                "address":     raw.get("project", {}).get("address", ""),
                "total":       raw.get("estimation", {}).get("total", 0),
            })
        except Exception:
            pass
    results.sort(key=lambda x: x["created_at"], reverse=True)
    return results


def load_estimate(company_id: str, estimate_id: str) -> dict | None:
    """
    estimate_id に対応するJSONを返す（フル）。見つからなければ None。
    """
    path = _company_dir(company_id) / f"{estimate_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def delete_estimate(company_id: str, estimate_id: str) -> bool:
    """
    指定案件を削除。成功なら True。
    """
    path = _company_dir(company_id) / f"{estimate_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False

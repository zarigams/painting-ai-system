"""
ロギングモジュール
全操作・GPT呼び出し・計算・エラーを記録する。

保存先:
  - st.session_state["_app_logs"]  → 管理画面ログビューアで表示
  - data/logs/{company_id}/YYYY-MM-DD.jsonl → ファイル（Claude・ローカルで直読み可）
"""

import json
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

LOG_DIR = Path(__file__).parent.parent / "data" / "logs"

try:
    import streamlit as st
    _HAS_STREAMLIT = True
except ImportError:
    _HAS_STREAMLIT = False


def _get_company_id() -> str:
    if _HAS_STREAMLIT:
        try:
            return st.session_state.get("company_id", "unknown") or "unknown"
        except Exception:
            pass
    return "unknown"


def _get_session_logs() -> list:
    if _HAS_STREAMLIT:
        try:
            if "_app_logs" not in st.session_state:
                st.session_state["_app_logs"] = []
            return st.session_state["_app_logs"]
        except Exception:
            pass
    return []


def _write_file(entry: dict) -> None:
    try:
        company_id = entry.get("company_id", "unknown")
        log_dir = LOG_DIR / company_id
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def log(event: str, category: str, data: Optional[dict] = None, level: str = "INFO") -> None:
    entry: dict = {
        "ts":         datetime.now().isoformat(timespec="milliseconds"),
        "level":      level,
        "category":   category,
        "event":      event,
        "company_id": _get_company_id(),
    }
    if data:
        entry["data"] = data

    try:
        logs = _get_session_logs()
        logs.append(entry)
        if len(logs) > 2000:
            logs[:] = logs[-2000:]
    except Exception:
        pass

    _write_file(entry)


def log_gpt_call(
    func_name: str,
    model: str,
    system_prompt: str,
    user_message_summary: str,
    response_text: str,
    tokens_prompt: int = None,
    tokens_completion: int = None,
    tokens_total: int = None,
    error: str = None,
) -> None:
    data = {
        "func":                 func_name,
        "model":                model,
        "system_prompt":        system_prompt[:800] if system_prompt else "",
        "user_message_summary": user_message_summary[:800] if user_message_summary else "",
        "response_full":        response_text if response_text else "",
        "response_length":      len(response_text) if response_text else 0,
    }
    if tokens_prompt is not None:
        data["tokens_prompt"]     = tokens_prompt
        data["tokens_completion"] = tokens_completion
        data["tokens_total"]      = tokens_total
    if error:
        data["error"] = error
    log(
        f"GPT呼び出し: {func_name}",
        "GPT",
        data,
        level="ERROR" if error else "INFO",
    )


def log_whisper(
    transcript: str,
    audio_size_bytes: int = None,
    error: str = None,
) -> None:
    data = {
        "transcript":     transcript if transcript else "",
        "transcript_len": len(transcript) if transcript else 0,
    }
    if audio_size_bytes is not None:
        data["audio_size_bytes"] = audio_size_bytes
    if error:
        data["error"] = error
    log(
        "Whisper文字起こし",
        "WHISPER",
        data,
        level="ERROR" if error else "INFO",
    )


def log_ui(event: str, data: Optional[dict] = None) -> None:
    log(event, "UI", data)


def log_auth(
    event: str,
    company_id: str,
    success: bool,
    detail: str = None,
) -> None:
    data: dict = {"target_company_id": company_id, "success": success}
    if detail:
        data["detail"] = detail
    log(event, "AUTH", data, level="INFO" if success else "WARN")


def log_calc(quantities: dict, result: dict) -> None:
    items = result.get("estimation_items", [])
    data = {
        "input_quantities": {
            "wall_area":           quantities.get("wall_area"),
            "roof_area":           quantities.get("roof_area"),
            "scaffold_area":       quantities.get("scaffold_area"),
            "fascia_length":       quantities.get("fascia_length"),
            "gutter_length":       quantities.get("gutter_length"),
            "water_cutoff_length": quantities.get("water_cutoff_length"),
            "joint_seal_length":   quantities.get("joint_seal_length"),
            "discount":            quantities.get("discount"),
        },
        "items_count":          len(items),
        "subtotal_before_disc": result.get("subtotal_before_discount"),
        "discount":             result.get("discount"),
        "subtotal":             result.get("subtotal"),
        "tax_amount":           result.get("tax_amount"),
        "total":                result.get("total"),
        "items_summary": [
            {
                "name":       it.get("item_name"),
                "qty":        it.get("quantity"),
                "unit_price": it.get("unit_price"),
                "amount":     it.get("amount"),
            }
            for it in items
        ],
    }
    log("計算実行", "CALC", data)


def log_error(event: str, exc: Exception, category: str = "ERROR") -> None:
    data = {
        "error_type": type(exc).__name__,
        "error_msg":  str(exc),
        "traceback":  traceback.format_exc(),
    }
    log(event, category, data, level="ERROR")


def log_measure(
    event: str,
    segments: Optional[list] = None,
    reflected_values: Optional[dict] = None,
    zoom_pct: Optional[int] = None,
) -> None:
    data: dict = {}
    if segments is not None:
        data["segment_count"] = len(segments)
        data["segments"] = segments
    if reflected_values is not None:
        data["reflected_values"] = reflected_values
    if zoom_pct is not None:
        data["zoom_pct"] = zoom_pct
    log(event, "MEASURE", data)


def log_admin(event: str, changes: Optional[dict] = None) -> None:
    log(event, "ADMIN", changes or {})


def log_file(
    event: str,
    filename: str,
    size_bytes: int = None,
    error: str = None,
) -> None:
    data: dict = {"filename": filename}
    if size_bytes is not None:
        data["size_bytes"] = size_bytes
    if error:
        data["error"] = error
    log(event, "FILE", data, level="ERROR" if error else "INFO")


def log_geo_calc(event: str, inputs: dict = None, result: dict = None) -> None:
    data: dict = {}
    if inputs:
        data["inputs"] = inputs
    if result:
        data["result"] = result
    log(event, "GEO", data)


def get_session_logs() -> list:
    try:
        return list(_get_session_logs())
    except Exception:
        return []


def get_file_logs(company_id: str, date_str: str = None) -> list:
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = LOG_DIR / company_id / f"{date_str}.jsonl"
    if not log_file.exists():
        return []
    entries = []
    try:
        with open(log_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        pass
    except Exception:
        pass
    return entries


def list_log_dates(company_id: str) -> list:
    log_dir = LOG_DIR / company_id
    if not log_dir.exists():
        return []
    return sorted([p.stem for p in log_dir.glob("*.jsonl")], reverse=True)


def export_session_logs_json() -> str:
    logs = get_session_logs()
    return json.dumps(logs, ensure_ascii=False, indent=2)

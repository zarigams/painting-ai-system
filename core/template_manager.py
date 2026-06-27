"""
テンプレート管理モジュール
Excelテンプレートを登録・選択・管理する
"""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

TEMPLATES_DIR = Path(__file__).parent.parent / "data" / "templates"
TEMPLATES_META = TEMPLATES_DIR / "templates.json"


def _load_meta() -> dict:
    if TEMPLATES_META.exists():
        with open(TEMPLATES_META, encoding="utf-8") as f:
            return json.load(f)
    return {"templates": []}


def _save_meta(meta: dict):
    TEMPLATES_META.parent.mkdir(parents=True, exist_ok=True)
    with open(TEMPLATES_META, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def init_default_templates():
    """デフォルトテンプレートをメタデータに登録する（初回のみ）"""
    meta = _load_meta()
    ids = [t["id"] for t in meta["templates"]]
    if "standard" not in ids:
        meta["templates"].append({
            "id": "standard",
            "name": "標準テンプレート（住宅塗装）",
            "description": "外壁・屋根・シーリング・諸経費を含む標準的な住宅塗装見積書",
            "file": "standard.xlsx",
            "created_at": datetime.now().isoformat(),
        })
        _save_meta(meta)


def list_templates() -> list:
    """登録済みテンプレート一覧を返す"""
    init_default_templates()
    return _load_meta()["templates"]


def get_template_path(template_id: str) -> Optional[Path]:
    """テンプレートIDからファイルパスを返す"""
    meta = _load_meta()
    for t in meta["templates"]:
        if t["id"] == template_id:
            path = TEMPLATES_DIR / t["file"]
            return path if path.exists() else None
    return None


def add_template(name: str, description: str, source_file_bytes: bytes, file_ext: str = ".xlsx") -> str:
    """
    新しいテンプレートを登録する

    Returns:
        str: 新しいテンプレートのID
    """
    meta = _load_meta()
    new_id = f"tmpl_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    filename = f"{new_id}{file_ext}"
    dest = TEMPLATES_DIR / filename
    dest.write_bytes(source_file_bytes)

    meta["templates"].append({
        "id": new_id,
        "name": name,
        "description": description,
        "file": filename,
        "created_at": datetime.now().isoformat(),
    })
    _save_meta(meta)
    return new_id


def delete_template(template_id: str) -> bool:
    """テンプレートを削除する（standardは削除不可）"""
    if template_id == "standard":
        return False
    meta = _load_meta()
    for i, t in enumerate(meta["templates"]):
        if t["id"] == template_id:
            path = TEMPLATES_DIR / t["file"]
            if path.exists():
                path.unlink()
            meta["templates"].pop(i)
            _save_meta(meta)
            return True
    return False


def copy_template_to_output(template_id: str, output_dir: Path, filename: str) -> Optional[Path]:
    """テンプレートを出力ディレクトリにコピーして返す"""
    src = get_template_path(template_id)
    if src is None:
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / filename
    shutil.copy2(src, dest)
    return dest

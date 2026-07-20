"""
案件保存・履歴管理モジュール
data/estimates/{company_id}/ 以下にJSONで保存する
data/estimate_files/{company_id}/{estimate_id}/ 以下に図面等の実体ファイルを保存する（A3-0b-1）
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

_ESTIMATES_DIR = Path(__file__).parent.parent / "data" / "estimates"
_ESTIMATE_FILES_DIR = Path(__file__).parent.parent / "data" / "estimate_files"

# estimate_id は uuid.uuid4().hex[:12] 由来（英数字のみ）と保証されているため、
# 正規表現による厳格な検証で問題ない。
_ESTIMATE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _validate_estimate_id(estimate_id: str) -> str:
    """estimate_id が安全な形式（英数字・-・_のみ）であることを検証する。"""
    if not isinstance(estimate_id, str) or not _ESTIMATE_ID_RE.fullmatch(estimate_id):
        raise ValueError(f"不正なestimate_idです: {estimate_id!r}")
    return estimate_id


def _safe_subdir(base: Path, component: str, label: str) -> Path:
    """
    company_id 用のパス検証ヘルパー。

    company_id は会社名等をそのまま使う運用のため文字種を制限できない
    （英数字保証はない）。そのため以下の方式で安全性を担保する:
      1. 空文字・None・"."・".." を拒否
      2. パス区切り文字（"/" "\\"）を含む場合は拒否
      3. 絶対パスの場合は拒否
      4. (base / component).resolve() が base.resolve() 配下であることを確認
    """
    if not isinstance(component, str) or not component:
        raise ValueError(f"不正な{label}です: {component!r}")
    if component in (".", ".."):
        raise ValueError(f"不正な{label}です: {component!r}")
    if "/" in component or "\\" in component:
        raise ValueError(f"不正な{label}です（パス区切り文字は使用できません）: {component!r}")
    if os.path.isabs(component):
        raise ValueError(f"不正な{label}です（絶対パスは使用できません）: {component!r}")

    base_resolved = base.resolve()
    candidate = (base / component).resolve()
    try:
        candidate.relative_to(base_resolved)
    except ValueError:
        raise ValueError(f"不正な{label}です（許可された親ディレクトリ外）: {component!r}")
    return candidate


def _company_dir(company_id: str) -> Path:
    d = _safe_subdir(_ESTIMATES_DIR, company_id, "company_id")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _estimate_files_dir(company_id: str, estimate_id: str) -> Path:
    """
    data/estimate_files/{company_id}/{estimate_id}/ のPathを返す。
    ディレクトリは作成しない（保存対象が無い案件で空フォルダが残るのを避けるため）。
    """
    _validate_estimate_id(estimate_id)
    company_dir = _safe_subdir(_ESTIMATE_FILES_DIR, company_id, "company_id")
    return _safe_subdir(company_dir, estimate_id, "estimate_id")


def _empty_files_meta() -> dict:
    """JSON "files" キーの空スキーマ。呼び出しごとに新しいdictを返す（共有可変オブジェクト禁止）。"""
    return {
        "pdf": None,
        "floor_plan": None,
        "photos": [],
        "drawing_annotated": None,
        "drawing_page1_raw": None,
        "trace_3d": None,
        "step3_drawings": [],
    }


def _atomic_write_bytes(path: Path, data: bytes) -> tuple[str, int]:
    """
    同一ディレクトリ内の一時ファイルへ書き込み→サイズ/SHA-256検証→os.replace()。
    Returns: (sha256_hex, size_bytes)
    検証・書き込みに失敗した場合は一時ファイルを削除して例外を送出する。
    保存先に既にファイルが存在する場合も異常として扱う（新規保存のみを前提とするため）。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"保存先に既にファイルが存在します: {path}")

    tmp_path = path.with_name(f"{path.name}.tmp-{uuid.uuid4().hex[:8]}")
    try:
        tmp_path.write_bytes(data)
        actual_size = tmp_path.stat().st_size
        if actual_size != len(data):
            raise IOError(
                f"書き込みサイズ不一致: expected={len(data)} actual={actual_size} path={path}"
            )
        expected_sha256 = hashlib.sha256(data).hexdigest()
        actual_sha256 = hashlib.sha256(tmp_path.read_bytes()).hexdigest()
        if actual_sha256 != expected_sha256:
            raise IOError(f"書き込み後のSHA-256が一致しません: path={path}")
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise
    return expected_sha256, actual_size


_IMAGE_EXT_MIME = {
    "JPEG": (".jpg", "image/jpeg"),
    "PNG":  (".png", "image/png"),
    "WEBP": (".webp", "image/webp"),
    "BMP":  (".bmp", "image/bmp"),
    "TIFF": (".tiff", "image/tiff"),
}


def _detect_image_content_type(data: bytes) -> tuple[str, str]:
    """実バイナリ（Pillowでの判定）から (拡張子, content_type) を返す。判定不能時はバイナリ扱い。"""
    try:
        import io
        from PIL import Image
        with Image.open(io.BytesIO(data)) as img:
            fmt = img.format
        return _IMAGE_EXT_MIME.get(fmt, (".bin", "application/octet-stream"))
    except Exception:
        return (".bin", "application/octet-stream")


def _sniff_content_type(data: bytes) -> tuple[str, str]:
    """PDF・画像が混在しうるファイル（STEP3追加図面）向け。PDFマジックバイト→Pillow判定の順で検出する。"""
    if isinstance(data, (bytes, bytearray)) and bytes(data[:5]) == b"%PDF-":
        return (".pdf", "application/pdf")
    return _detect_image_content_type(data)


def _sanitize_display_name(name, fallback: str) -> str:
    """表示用ファイル名を安全化する（パス構成には使わない。表示・記録専用）。"""
    if not name or not isinstance(name, str):
        return fallback
    base = os.path.basename(name.replace("\\", "/")).strip()
    if not base or base in (".", ".."):
        return fallback
    return base[:200]


def save_estimate_files(company_id: str, estimate_id: str, materials: dict) -> dict:
    """
    図面等の実体ファイルを data/estimate_files/{company_id}/{estimate_id}/ へ保存する。

    materials = {
        "pdf": bytes | None,
        "floor_plan": bytes | None,
        "photos": list[bytes],
        "drawing_annotated": bytes | None,
        "drawing_page1_raw": bytes | None,
        "trace_3d": bytes | None,
        "step3_drawings": list[bytes | {"filename": str, "bytes": bytes}],
    }

    Returns: JSON "files" キーに格納する軽量メタデータdict
    （filename / relative_path / content_type / size / sha256）。
    失敗時は例外を送出する（ここではディレクトリのcleanupを行わない。呼び出し元の責務）。
    """
    files_dir = _estimate_files_dir(company_id, estimate_id)
    meta = _empty_files_meta()

    def _write_one(data: bytes, rel_name: str, content_type: str, display_name: str) -> dict:
        target = files_dir / rel_name
        sha256, size = _atomic_write_bytes(target, data)
        rel_path = "/".join(["estimate_files", company_id, estimate_id, rel_name])
        return {
            "filename": display_name,
            "relative_path": rel_path,
            "content_type": content_type,
            "size": size,
            "sha256": sha256,
        }

    if materials.get("pdf"):
        meta["pdf"] = _write_one(
            materials["pdf"], "drawing_source.pdf", "application/pdf", "drawing_source.pdf"
        )

    if materials.get("floor_plan"):
        meta["floor_plan"] = _write_one(
            materials["floor_plan"], "floor_plan.pdf", "application/pdf", "floor_plan.pdf"
        )

    for idx, photo_bytes in enumerate(materials.get("photos") or [], start=1):
        if not photo_bytes:
            continue
        ext, ctype = _detect_image_content_type(photo_bytes)
        rel_name = f"photo_{idx:02d}{ext}"
        meta["photos"].append(_write_one(photo_bytes, rel_name, ctype, rel_name))

    if materials.get("drawing_annotated"):
        meta["drawing_annotated"] = _write_one(
            materials["drawing_annotated"], "drawing_annotated.png", "image/png", "drawing_annotated.png"
        )

    if materials.get("drawing_page1_raw"):
        meta["drawing_page1_raw"] = _write_one(
            materials["drawing_page1_raw"], "drawing_page1_raw.png", "image/png", "drawing_page1_raw.png"
        )

    if materials.get("trace_3d"):
        meta["trace_3d"] = _write_one(
            materials["trace_3d"], "trace_3d.png", "image/png", "trace_3d.png"
        )

    for idx, item in enumerate(materials.get("step3_drawings") or [], start=1):
        data = item.get("bytes") if isinstance(item, dict) else item
        if not data:
            continue
        ext, ctype = _sniff_content_type(data)
        rel_name = f"step3_drawing_{idx:02d}{ext}"
        original_name = item.get("filename") if isinstance(item, dict) else None
        display_name = _sanitize_display_name(original_name, rel_name)
        meta["step3_drawings"].append(_write_one(data, rel_name, ctype, display_name))

    return meta


def save_estimate(company_id: str, project: dict, quantities: dict,
                  estimation: dict, estimation_sheet_data: dict | None = None,
                  drawing_materials: dict | None = None) -> str:
    """
    見積りデータをJSONに保存する。drawing_materials が渡された場合は図面等の実体ファイルも
    data/estimate_files/{company_id}/{estimate_id}/ へ保存する。

    A3-0b-1では新規保存のみを対象とする：
      - estimate_id は毎回新規発行（上書きは行わない）
      - 発行したestimate_idと同名のJSON・ファイルディレクトリが既に存在する場合は
        保存を開始する前に異常として検出し、既存データには一切触れない
      - ファイル保存・メタデータ生成・JSON生成・JSON書き込みのいずれかで失敗した場合は、
        「この呼び出しが新規作成した」estimate_files/{company_id}/{estimate_id}/ と
        JSONファイルのみを削除し、例外を再送出する

    Returns: estimate_id (str)
    """
    estimate_id = uuid.uuid4().hex[:12]
    created_at  = datetime.now().strftime("%Y-%m-%d %H:%M")

    company_dir = _company_dir(company_id)
    json_path   = company_dir / f"{estimate_id}.json"
    files_dir   = _estimate_files_dir(company_id, estimate_id)

    # ── 衝突検出（保存開始前）。以降のtry節で作るものは全て新規作成分であることが保証される ──
    if json_path.exists() or files_dir.exists():
        raise FileExistsError(
            f"estimate_id が衝突しました。既存データ保護のため保存を中断します: {estimate_id}"
        )

    try:
        files_meta = _empty_files_meta()
        if drawing_materials:
            files_meta = save_estimate_files(company_id, estimate_id, drawing_materials)

        data = {
            "id":                    estimate_id,
            "created_at":            created_at,
            "company_id":            company_id,
            "project":               project,
            "quantities":            quantities,
            "estimation":            estimation,
            "estimation_sheet_data": estimation_sheet_data,
            "files":                 files_meta,
        }
        json_text = json.dumps(data, ensure_ascii=False, indent=2)
        json_path.write_text(json_text, encoding="utf-8")
    except Exception:
        # このsave_estimate()呼び出しが新規作成した分のみを削除する
        # （衝突検出により、ここに到達する時点でfiles_dir/json_pathはこの呼び出し以前には
        #   存在していなかったことが保証されている）
        if files_dir.exists():
            shutil.rmtree(files_dir, ignore_errors=True)
        if json_path.exists():
            json_path.unlink(missing_ok=True)
        raise

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
    estimate_id が不正な形式（パストラバーサル文字列等）の場合は ValueError を送出する。
    """
    _validate_estimate_id(estimate_id)
    path = _company_dir(company_id) / f"{estimate_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def delete_estimate(company_id: str, estimate_id: str) -> bool:
    """
    指定案件を削除。JSONに加え、対応する
    data/estimate_files/{company_id}/{estimate_id}/ が存在すればあわせて削除する
    （JSON書き込み失敗等で孤立したファイルディレクトリが残っているケースの自己修復も兼ねる）。
    他のestimate_id・company_idの上位ディレクトリには一切触れない。

    成功なら True（JSONが存在し削除できた場合）。
    """
    _validate_estimate_id(estimate_id)
    path = _company_dir(company_id) / f"{estimate_id}.json"
    existed = path.exists()
    if existed:
        path.unlink()

    files_dir = _estimate_files_dir(company_id, estimate_id)
    if files_dir.exists():
        shutil.rmtree(files_dir)

    return existed

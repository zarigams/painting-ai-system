"""
案件保存・履歴管理モジュール
data/estimates/{company_id}/ 以下にJSONで保存する
data/estimate_files/{company_id}/{estimate_id}/ 以下に図面等の実体ファイルを保存する（A3-0b-1）
canvas_states（Fabric.js手動計測キャンバスの状態）はJSON内の"canvas_states"キーへ保存する（A3-0b-2、保存側のみ）
saved_step・drawing_data・image_data・drawing_scale・original_paperの保存、および既存案件への
安全な上書き保存（update_estimate）・保存済みファイルの読込（load_estimate_file）はA3-0b-3-1で追加
（保存層のみ。session_stateへの復元・画面制御はA3-0b-3の別フェーズで対応）
canvas_states内の各線オブジェクトへのcategory（積算属性、CANVAS_CATEGORIES）はA3-1で追加。
省略時はNone（未分類）で後方互換（categoryフィールドの無い既存canvas_statesもそのまま読み込める）

test_baseline（AI初期値スナップショット、write-once）はtest_baseline機能で追加。
- app.py は STEP2 の自動積算が成功した直後に build_test_baseline() を呼び出し、
  その戻り値をそのまま st.session_state.test_baseline へ代入する
  （build_test_baseline() 内部で ai_initial_quantities を直ちにJSON round-trip
  複製するため、後続のquantities変更から独立している＝write-once実現の核）
- save_estimate() のみが test_baseline を受け取り、新規保存時に一度だけ
  _validate_test_baseline_for_storage() で再検証したうえで書き込む
- update_estimate() は test_baseline 引数を持たない。既存JSONにキーが存在する場合のみ
  そのままコピーし、存在しない場合は新JSONにもキー自体を追加しない（後付け禁止）
- app.py側はStreamlitに依存しない should_create_test_baseline() / get_app_commit() を
  呼び出して生成要否・app_commitを判定する（本モジュールはStreamlitへ依存しない）
"""
from __future__ import annotations
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
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


def _write_estimate_files(target_dir: Path, company_id: str, estimate_id: str, materials: dict) -> dict:
    """
    materials の実体を target_dir へ書き込み、JSON "files" キー用メタデータを返す。

    relative_path は常に本番パス形式（"estimate_files/{company_id}/{estimate_id}/{rel_name}"）で
    記録する。target_dir が一時ディレクトリ（update_estimate()の一時領域等）であっても、
    メタデータ上のrelative_pathは最終的な本番配置場所を指す文字列にする
    （呼び出し元がその後target_dirを本番の場所へ配置し直すことを前提とするため）。

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
    meta = _empty_files_meta()

    def _write_one(data: bytes, rel_name: str, content_type: str, display_name: str) -> dict:
        target = target_dir / rel_name
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


def save_estimate_files(company_id: str, estimate_id: str, materials: dict) -> dict:
    """
    図面等の実体ファイルを data/estimate_files/{company_id}/{estimate_id}/ へ保存する。

    materials の形式・戻り値は _write_estimate_files() のdocstringを参照。
    失敗時は例外を送出する（ここではディレクトリのcleanupを行わない。呼び出し元の責務）。
    """
    files_dir = _estimate_files_dir(company_id, estimate_id)
    return _write_estimate_files(files_dir, company_id, estimate_id, materials)


_CANVAS_PAGE_ALLOWED_KEYS = {"page_key", "viewport_transform", "objects"}
_CANVAS_OBJECT_ALLOWED_KEYS = {
    "type", "orig_x1", "orig_y1", "orig_x2", "orig_y2", "length_px", "category",
}
_CANVAS_OBJECT_NUMERIC_KEYS = ("orig_x1", "orig_y1", "orig_x2", "orig_y2", "length_px")

# A3-1: カテゴリは「色分け」ではなく積算属性として設計する（線の色はcategoryからの表示専用の派生値であり、
# 保存データには含めない）。この一覧が唯一の正本であり、core/drawing_canvas/__init__.py はここから
# CANVAS_CATEGORIESをimportしてフロントエンドへpropsとして渡す（フロント側にリストを二重管理させない）。
CANVAS_CATEGORIES = (
    "外壁", "軒天", "破風", "鼻隠し", "雨樋", "シャッターボックス",
    "水切り", "幕板", "ベランダ床", "シーリング", "その他",
)
_CANVAS_CATEGORY_SET = set(CANVAS_CATEGORIES)


def _sorted_key_reprs(keys) -> list[str]:
    """
    エラーメッセージ組み立て用：キー集合をrepr()した文字列へ変換してからソートする。
    未知キーにstr・int等の異なる型が混在していても、元のキー同士を直接比較しない
    （repr()後の文字列同士を比較する）ため、TypeErrorにならず必ずValueErrorを構築できる。
    """
    return sorted(repr(k) for k in keys)


def _require_finite_number(value, label: str) -> float:
    """bool ではない int/float かつ有限値であることを検証し、float へ正規化して返す。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"canvas_states: {label} が数値ではありません: {value!r}")
    if not math.isfinite(value):
        raise ValueError(f"canvas_states: {label} が有限数値ではありません: {value!r}")
    return float(value)


def _validate_and_normalize_canvas_states(canvas_states: dict) -> dict:
    """
    canvas_states 全体を検証し、新しいdictとして正規化して返す。
    入力dict・その内部のdict/listは一切変更しない（ホワイトリスト方式で新規構築する）。

    許可するキーは以下のみ。未知・余分なキーが1件でも存在する場合は、
    黙って除外せず ValueError を送出して保存全体を失敗させる。
      - 各ページ value: "page_key", "viewport_transform", "objects"
      - 各 line object: "type", "orig_x1", "orig_y1", "orig_x2", "orig_y2", "length_px", "category"

    "category"はA3-1で追加したオプショナルキー（積算属性、線の色分けはこの値からの表示専用の派生）。
    省略時はNone（未分類）として扱う。指定する場合はCANVAS_CATEGORIESに含まれる文字列のみを許可し、
    それ以外（bool・未知の文字列・数値等）はValueErrorとする。

    期待する形式:
        {
            page_key(str, 非空): {
                "page_key": page_keyと同一のstr,
                "viewport_transform": [float x6]（bool不可・有限値のみ）,
                "objects": [
                    {"type": "line",
                     "orig_x1": float, "orig_y1": float,
                     "orig_x2": float, "orig_y2": float,
                     "length_px": float,（数値はいずれもbool不可・有限値のみ）
                     "category": strまたは省略可（省略時はNone。指定時はCANVAS_CATEGORIESのいずれか）},
                    ...
                ]
            },
            ...
        }

    不正な形式が見つかった場合は ValueError を送出する（部分的な正規化結果は返さない）。
    """
    if not isinstance(canvas_states, dict):
        raise ValueError(f"canvas_states は dict である必要があります: {type(canvas_states)!r}")

    normalized: dict = {}

    for page_key, page_value in canvas_states.items():
        if not isinstance(page_key, str) or page_key == "":
            raise ValueError(f"canvas_states: 不正なpage_keyです: {page_key!r}")

        if not isinstance(page_value, dict):
            raise ValueError(
                f"canvas_states[{page_key!r}] は dict である必要があります: {type(page_value)!r}"
            )

        unknown_page_keys = set(page_value.keys()) - _CANVAS_PAGE_ALLOWED_KEYS
        if unknown_page_keys:
            raise ValueError(
                f"canvas_states[{page_key!r}] に未知のキーがあります: "
                f"{_sorted_key_reprs(unknown_page_keys)}"
            )

        inner_page_key = page_value.get("page_key")
        if not isinstance(inner_page_key, str) or inner_page_key != page_key:
            raise ValueError(
                f"canvas_states[{page_key!r}] の内部page_keyが外側のキーと一致しません: "
                f"{inner_page_key!r}"
            )

        raw_vt = page_value.get("viewport_transform")
        if not isinstance(raw_vt, list) or len(raw_vt) != 6:
            raise ValueError(
                f"canvas_states[{page_key!r}].viewport_transform は長さ6のlistである必要があります: "
                f"{raw_vt!r}"
            )
        normalized_vt = [
            _require_finite_number(v, f"canvas_states[{page_key!r}].viewport_transform[{i}]")
            for i, v in enumerate(raw_vt)
        ]

        raw_objects = page_value.get("objects")
        if not isinstance(raw_objects, list):
            raise ValueError(
                f"canvas_states[{page_key!r}].objects は list である必要があります: {raw_objects!r}"
            )

        normalized_objects = []
        for obj_idx, obj in enumerate(raw_objects):
            obj_label = f"canvas_states[{page_key!r}].objects[{obj_idx}]"
            if not isinstance(obj, dict):
                raise ValueError(f"{obj_label} は dict である必要があります: {type(obj)!r}")

            unknown_obj_keys = set(obj.keys()) - _CANVAS_OBJECT_ALLOWED_KEYS
            if unknown_obj_keys:
                raise ValueError(
                    f"{obj_label} に未知のキーがあります: {_sorted_key_reprs(unknown_obj_keys)}"
                )

            if obj.get("type") != "line":
                raise ValueError(f"{obj_label}.type は 'line' である必要があります: {obj.get('type')!r}")

            normalized_obj = {"type": "line"}
            for numeric_key in _CANVAS_OBJECT_NUMERIC_KEYS:
                if numeric_key not in obj:
                    raise ValueError(f"{obj_label} に必須キー {numeric_key!r} がありません")
                normalized_obj[numeric_key] = _require_finite_number(
                    obj[numeric_key], f"{obj_label}.{numeric_key}"
                )

            # A3-1: category はオプショナル（省略時はNone=未分類）。指定時はCANVAS_CATEGORIESのみ許可。
            if "category" in obj:
                category_value = obj["category"]
                if category_value is not None and (
                    isinstance(category_value, bool)
                    or not isinstance(category_value, str)
                    or category_value not in _CANVAS_CATEGORY_SET
                ):
                    raise ValueError(
                        f"{obj_label}.category が不正です（許可カテゴリ外）: {category_value!r}"
                    )
                normalized_obj["category"] = category_value
            else:
                normalized_obj["category"] = None

            normalized_objects.append(normalized_obj)

        normalized[page_key] = {
            "page_key": page_key,
            "viewport_transform": normalized_vt,
            "objects": normalized_objects,
        }

    return normalized


# ─────────────────────────────────────────────────────────────
# test_baseline（AI初期値スナップショット、write-once）
# ─────────────────────────────────────────────────────────────
# input_sources の許可値。「実際に解析処理が成功し、その結果が初期quantitiesの
# 生成に使用されたソース」のみを記録する（試行しただけで失敗したものは含めない）。
_TEST_BASELINE_INPUT_SOURCES = ("voice", "drawing_pdf", "floor_plan", "photos")

# input_sources の要素 → prompt_versions / models のキーへの対応表。
# 名称が一致しない（drawing_pdf→drawing、photos→photo）ため、単一のソースとして
# ここに定義し、app.py側もこの対応表を経由する。
_INPUT_SOURCE_TO_VERSION_KEY = {
    "voice":       "voice",
    "drawing_pdf": "drawing",
    "floor_plan":  "floor_plan",
    "photos":      "photo",
}

# prompt_versions の許可値（唯一の正本）。将来プロンプトを変更した場合はここを更新する。
_PROMPT_VERSION_ALLOWED = {
    "voice":      "voice_extractor_v1",
    "drawing":    "drawing_analyzer_v1",
    "floor_plan": "floor_plan_analyzer_v1",
    "photo":      "image_analyzer_v1",
}

# models の許可値（唯一の正本）。
# voice/photoは modules/llm_client.py の LLMClient.model、
# drawing/floor_plan は core/drawing_analyzer.py の DrawingAnalyzer.model が実際の発生源であり、
# 現状はどちらも "gpt-4o" だが定義箇所が独立しているため、単一のmodel文字列ではなく
# ソースごとのdictとして記録する（どちらか一方だけ将来変更されても正しく記録できるようにするため）。
_MODEL_ALLOWED = {
    "voice":      "gpt-4o",
    "drawing":    "gpt-4o",
    "floor_plan": "gpt-4o",
    "photo":      "gpt-4o",
}

_TEST_BASELINE_PIPELINE_VERSION = "legacy_analysis_v1"
_TEST_BASELINE_RULE_VERSION = "NESESTYLE_rule_v1.0"

# build_test_baseline() が返す正規化済みdict、および save_estimate() が
# _validate_test_baseline_for_storage() で再検証するdictに要求するキー集合。
_TEST_BASELINE_NORMALIZED_KEYS = {
    "ai_initial_quantities", "app_commit", "models", "input_sources",
    "pipeline_version", "prompt_versions", "rule_version",
    "analysis_started_at", "analysis_completed_at",
}

_APP_COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")
_ISO8601_JST_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?\+09:00$"
)


def should_create_test_baseline(current_case_id, test_baseline, ai_analysis_used) -> bool:
    """
    test_baselineを新規生成してよいかを判定する（Streamlit非依存の純粋関数）。

    Trueを返すのは次のすべてを満たす場合のみ:
      - current_case_id が None（まだ一度も保存されていない新規案件）
      - test_baseline が None（このセッションでまだ生成されていない）
      - ai_analysis_used が真値（実際に成功して初期quantitiesへ寄与した
        入力ソースが1件以上ある。呼び出し側は
        `bool(successful_input_sources)` をそのまま渡すことを想定する）

    いずれか1つでも満たさない場合はFalse（＝生成しない）。
    これにより「既存案件（baselineの有無を問わない）への後付け」
    「同一セッション内での再生成」「AI解析を使っていない手動経路での生成」を
    すべて構造的に防ぐ。
    """
    return current_case_id is None and test_baseline is None and bool(ai_analysis_used)


def _normalize_commit_candidate(value) -> str | None:
    """
    commit hash候補を strip・小文字化し、[0-9a-f]{7,40} に一致する場合のみ返す。
    一致しない場合（None・空文字列・不正な形式等）は None を返す
    （＝「この候補は使えない、次の取得手段へ進む」ことを示す）。
    """
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if _APP_COMMIT_RE.fullmatch(normalized):
        return normalized
    return None


def get_app_commit(secret_value=None, env_value=None, repo_root: Path | None = None) -> str:
    """
    app_commit（デプロイされているコードのgit commit hash相当）を取得する。
    Streamlitへは一切依存しない（st.secrets等はapp.py側で取得し、引数として渡すこと）。

    優先順位:
      1. secret_value（呼び出し側がst.secrets.get("APP_COMMIT_SHA")等で取得した値）
      2. env_value（呼び出し側がos.getenv("APP_COMMIT_SHA")等で取得した値）
      3. `git rev-parse HEAD`（repo_root、未指定時はこのファイルの2階層上をリポジトリルートとみなす）
      4. 上記いずれも取得できない場合は "unknown"

    各候補は strip・小文字化のうえ [0-9a-f]{7,40} 形式であることを検証し、
    不正な値（空文字列・形式不一致等）はその段階で採用せず次の手段へフォールバックする。
    """
    for candidate in (secret_value, env_value):
        normalized = _normalize_commit_candidate(candidate)
        if normalized:
            return normalized

    git_value = _get_app_commit_from_git(repo_root)
    if git_value:
        return git_value

    return "unknown"


def _get_app_commit_from_git(repo_root: Path | None = None) -> str | None:
    """`git rev-parse HEAD` を安全に実行する。失敗時はNoneを返す（例外を送出しない）。"""
    try:
        cwd = repo_root if repo_root is not None else Path(__file__).parent.parent
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        return _normalize_commit_candidate(result.stdout)
    except Exception:
        return None


def _validate_test_baseline_core_fields(
    ai_initial_quantities, app_commit, input_sources,
    analysis_started_at, analysis_completed_at,
):
    """
    test_baseline の「素材」フィールド5点（ai_initial_quantities・app_commit・
    input_sources・analysis_started_at・analysis_completed_at）を検証する。
    build_test_baseline() と _validate_test_baseline_for_storage() の共通ロジック
    （検証規則を単一箇所にまとめ、二重実装によるズレを防ぐ）。

    ai_initial_quantities は json.loads(json.dumps(...)) によりJSONとして独立した
    コピーを作成して返す（呼び出し元が保持している元のdictへの参照を返さない。
    呼び出し元が本関数の呼び出し後に元のdictをin-place変更しても、
    戻り値には一切影響しない）。

    戻り値: (normalized_quantities, app_commit, input_sources_list, started, completed)
    不正な形式が見つかった場合は ValueError を送出する。
    """
    if not isinstance(ai_initial_quantities, dict):
        raise ValueError(
            f"test_baseline.ai_initial_quantities は dict である必要があります: "
            f"{type(ai_initial_quantities)!r}"
        )
    try:
        normalized_quantities = json.loads(json.dumps(ai_initial_quantities, ensure_ascii=False))
    except (TypeError, ValueError) as e:
        raise ValueError(
            f"test_baseline.ai_initial_quantities をJSONへ変換できません: {e!r}"
        ) from e

    if not isinstance(app_commit, str) or not (
        app_commit == "unknown" or _APP_COMMIT_RE.fullmatch(app_commit)
    ):
        raise ValueError(f"test_baseline.app_commit が不正です: {app_commit!r}")

    if not isinstance(input_sources, list) or any(
        not isinstance(s, str) for s in input_sources
    ):
        raise ValueError(
            f"test_baseline.input_sources は str の list である必要があります: {input_sources!r}"
        )
    if len(set(input_sources)) != len(input_sources):
        raise ValueError(f"test_baseline.input_sources に重複があります: {input_sources!r}")
    unknown_sources = set(input_sources) - set(_TEST_BASELINE_INPUT_SOURCES)
    if unknown_sources:
        raise ValueError(
            f"test_baseline.input_sources に未知の値があります: "
            f"{_sorted_key_reprs(unknown_sources)}"
        )

    if not isinstance(analysis_started_at, str) or not _ISO8601_JST_RE.fullmatch(analysis_started_at):
        raise ValueError(
            f"test_baseline.analysis_started_at はJST付きISO8601形式である必要があります: "
            f"{analysis_started_at!r}"
        )
    if not isinstance(analysis_completed_at, str) or not _ISO8601_JST_RE.fullmatch(analysis_completed_at):
        raise ValueError(
            f"test_baseline.analysis_completed_at はJST付きISO8601形式である必要があります: "
            f"{analysis_completed_at!r}"
        )
    try:
        started_dt = datetime.fromisoformat(analysis_started_at)
        completed_dt = datetime.fromisoformat(analysis_completed_at)
    except ValueError as e:
        raise ValueError(f"test_baselineの時刻文字列を解析できません: {e!r}") from e
    if completed_dt < started_dt:
        raise ValueError(
            f"test_baseline.analysis_completed_at が analysis_started_at より前です: "
            f"completed={analysis_completed_at!r} started={analysis_started_at!r}"
        )

    return (
        normalized_quantities, app_commit, list(input_sources),
        analysis_started_at, analysis_completed_at,
    )


def _derive_models_and_prompt_versions(input_sources):
    """input_sources から models・prompt_versions を導出する（唯一の導出経路）。"""
    models = {}
    prompt_versions = {}
    for source in input_sources:
        version_key = _INPUT_SOURCE_TO_VERSION_KEY[source]
        models[version_key] = _MODEL_ALLOWED[version_key]
        prompt_versions[version_key] = _PROMPT_VERSION_ALLOWED[version_key]
    return models, prompt_versions


def build_test_baseline(
    ai_initial_quantities: dict,
    input_sources: list,
    app_commit: str,
    analysis_started_at: str,
    analysis_completed_at: str,
) -> dict:
    """
    test_baseline を新規構築する（Streamlit非依存の純粋関数）。

    app.py はSTEP2の自動積算（自動積算を実行する）が全ソースの解析・初期quantities
    生成まで成功した直後、この関数の戻り値をそのまま st.session_state.test_baseline
    へ代入すること。これにより session_state 上の test_baseline と保存JSONの
    test_baseline は常に同一の構造・同一の値になる。

    重要（write-once実現の核心部分）: ai_initial_quantities は本関数の内部で直ちに
    json.loads(json.dumps(...)) によりJSONとして独立したコピーを作成する。
    呼び出し元（app.py）がこの関数を呼び出した「後」に、元のquantities dict
    （またはst.session_state.quantities）を再計算・幾何学計算値の反映・
    数量確認フォームでの編集等によりin-place変更しても、本関数が返したdict
    （および代入先のsession_state.test_baseline）は一切影響を受けない。
    そのため、この関数は「quantitiesが将来変更される可能性がある」タイミングでは
    なく、値が確定した瞬間（もしくはそれ以前）に呼び出しさえすれば安全である。

    models・prompt_versions・pipeline_version・rule_version はinput_sourcesから
    導出し、呼び出し側に二重計算・二重指定させない。

    不正な形式が見つかった場合は ValueError を送出する（部分的な結果は返さない。
    呼び出し元はこの場合 st.session_state.test_baseline へ代入してはならない）。
    """
    (
        normalized_quantities, normalized_app_commit, normalized_input_sources,
        started, completed,
    ) = _validate_test_baseline_core_fields(
        ai_initial_quantities=ai_initial_quantities,
        app_commit=app_commit,
        input_sources=input_sources,
        analysis_started_at=analysis_started_at,
        analysis_completed_at=analysis_completed_at,
    )
    models, prompt_versions = _derive_models_and_prompt_versions(normalized_input_sources)

    return {
        "ai_initial_quantities": normalized_quantities,
        "app_commit":            normalized_app_commit,
        "models":                models,
        "input_sources":         normalized_input_sources,
        "pipeline_version":      _TEST_BASELINE_PIPELINE_VERSION,
        "prompt_versions":       prompt_versions,
        "rule_version":          _TEST_BASELINE_RULE_VERSION,
        "analysis_started_at":   started,
        "analysis_completed_at": completed,
    }


def _validate_test_baseline_for_storage(test_baseline: dict) -> dict:
    """
    save_estimate() 内部専用の防御的な再検証。

    build_test_baseline() が既に正規化した9キーのdict（session_state.test_baseline
    と同一の構造）を入力として受け取り、以下を確認したうえで、入力から独立した
    新しいdictを構築して返す（入力dictを変更せず、戻り値は入力dictへの参照も
    一切保持しない）:

      - キー集合が正規化済みの9キーとちょうど一致すること（未知キー・不足キーは
        いずれもエラー）
      - ai_initial_quantities・app_commit・input_sources・
        analysis_started_at/analysis_completed_at が build_test_baseline() と
        同一の検証規則を満たすこと（ai_initial_quantitiesはここでも念のため
        再度JSON round-tripで独立コピーする）
      - models・prompt_versions・pipeline_version・rule_version が、
        input_sourcesから導出される期待値と完全に一致すること
        （改ざん・不整合の検出。例えばinput_sourcesに含まれないソースの
        modelsキーが紛れ込んでいる、pipeline_versionが書き換えられている等を検出する）

    不正な場合は ValueError を送出する。
    """
    if not isinstance(test_baseline, dict):
        raise ValueError(f"test_baseline は dict である必要があります: {type(test_baseline)!r}")

    unknown_keys = set(test_baseline.keys()) - _TEST_BASELINE_NORMALIZED_KEYS
    if unknown_keys:
        raise ValueError(
            f"test_baseline に未知のキーがあります: {_sorted_key_reprs(unknown_keys)}"
        )
    missing_keys = _TEST_BASELINE_NORMALIZED_KEYS - set(test_baseline.keys())
    if missing_keys:
        raise ValueError(
            f"test_baseline に必須キーが不足しています: {_sorted_key_reprs(missing_keys)}"
        )

    (
        normalized_quantities, normalized_app_commit, normalized_input_sources,
        started, completed,
    ) = _validate_test_baseline_core_fields(
        ai_initial_quantities=test_baseline["ai_initial_quantities"],
        app_commit=test_baseline["app_commit"],
        input_sources=test_baseline["input_sources"],
        analysis_started_at=test_baseline["analysis_started_at"],
        analysis_completed_at=test_baseline["analysis_completed_at"],
    )
    expected_models, expected_prompt_versions = _derive_models_and_prompt_versions(
        normalized_input_sources
    )

    if test_baseline.get("models") != expected_models:
        raise ValueError(
            f"test_baseline.models が input_sources から導出される値と一致しません: "
            f"実際={test_baseline.get('models')!r} 期待={expected_models!r}"
        )
    if test_baseline.get("prompt_versions") != expected_prompt_versions:
        raise ValueError(
            f"test_baseline.prompt_versions が input_sources から導出される値と一致しません: "
            f"実際={test_baseline.get('prompt_versions')!r} 期待={expected_prompt_versions!r}"
        )
    if test_baseline.get("pipeline_version") != _TEST_BASELINE_PIPELINE_VERSION:
        raise ValueError(
            f"test_baseline.pipeline_version が不正です: {test_baseline.get('pipeline_version')!r}"
        )
    if test_baseline.get("rule_version") != _TEST_BASELINE_RULE_VERSION:
        raise ValueError(
            f"test_baseline.rule_version が不正です: {test_baseline.get('rule_version')!r}"
        )

    return {
        "ai_initial_quantities": normalized_quantities,
        "app_commit":            normalized_app_commit,
        "models":                expected_models,
        "input_sources":         normalized_input_sources,
        "pipeline_version":      _TEST_BASELINE_PIPELINE_VERSION,
        "prompt_versions":       expected_prompt_versions,
        "rule_version":          _TEST_BASELINE_RULE_VERSION,
        "analysis_started_at":   started,
        "analysis_completed_at": completed,
    }


_SAVED_STEP_MIN = 1
_SAVED_STEP_MAX = 5


def _validate_saved_step(saved_step) -> int:
    """
    saved_step が 1〜5 の int（bool不可）であることを検証する。
    不正な場合は ValueError を送出する。None はこの関数では扱わない
    （呼び出し元が「未指定」を意味するNoneかどうかを先に判定すること）。
    """
    if isinstance(saved_step, bool) or not isinstance(saved_step, int):
        raise ValueError(f"不正なsaved_stepです（int以外）: {saved_step!r}")
    if not (_SAVED_STEP_MIN <= saved_step <= _SAVED_STEP_MAX):
        raise ValueError(
            f"不正なsaved_stepです（{_SAVED_STEP_MIN}〜{_SAVED_STEP_MAX}の範囲外）: {saved_step!r}"
        )
    return saved_step


def save_estimate(company_id: str, project: dict, quantities: dict,
                  estimation: dict, estimation_sheet_data: dict | None = None,
                  drawing_materials: dict | None = None,
                  canvas_states: dict | None = None,
                  saved_step: int | None = None,
                  drawing_data: dict | None = None,
                  image_data: dict | None = None,
                  drawing_scale: str | None = None,
                  original_paper: str | None = None,
                  test_baseline: dict | None = None) -> str:
    """
    見積りデータをJSONに保存する。drawing_materials が渡された場合は図面等の実体ファイルも
    data/estimate_files/{company_id}/{estimate_id}/ へ保存する。
    canvas_states が渡された場合は検証・正規化のうえJSON内へそのまま保存する（A3-0b-2）。
    未指定時は null ではなく空dict {} を保存する。

    test_baseline が渡された場合、それは呼び出し側（app.py）が既に
    build_test_baseline() で正規化済みの9キーdictであることを前提とし、
    _validate_test_baseline_for_storage() でさらに防御的に再検証したうえで保存する
    （write-once）。この関数（save_estimate）は新規estimate_id発行時にしか呼ばれない
    ため、test_baselineの「初回だけ書き込む」という制約は update_estimate() に
    test_baseline引数を持たせない設計によって満たされる
    （save_estimateはそもそも新規案件専用であり、常に「初回」として扱ってよい）。
    未指定時（None）は"test_baseline": null として保存する。
    不正な形式の場合はValueErrorを送出し、既存のcleanup経路（このsave_estimate()呼び出しが
    新規作成した分のみを削除）がそのまま機能する。

    A3-0b-1では新規保存のみを対象とする：
      - estimate_id は毎回新規発行（上書きは行わない）
      - 発行したestimate_idと同名のJSON・ファイルディレクトリが既に存在する場合は
        保存を開始する前に異常として検出し、既存データには一切触れない
      - ファイル保存・メタデータ生成・JSON生成・JSON書き込みのいずれかで失敗した場合は、
        「この呼び出しが新規作成した」estimate_files/{company_id}/{estimate_id}/ と
        JSONファイルのみを削除し、例外を再送出する

    A3-0b-2ではcanvas_statesについても同じcleanup方針を適用する：
      - canvas_states が不正な形式（未知のキーを含む場合も含む）の場合は ValueError を送出し、
        drawing_materials により既に書き込まれたファイルがあれば同じcleanup経路で削除する
      - 保存側のみを対象とし、読込・session_stateへの復元（A3-0b-3）は行わない

    A3-0b-3-1ではsaved_step・drawing_data・image_data・drawing_scale・original_paperを
    JSONへ追加保存する：
      - saved_step は 1〜5 のint（bool不可）のみ許可し、不正な場合は ValueError を送出する
        （未指定＝Noneの場合は検証をスキップし、JSON内は null になる）
      - drawing_data・image_data・drawing_scale・original_paper は検証を行わず、
        estimation_sheet_data と同様にそのままJSONへ格納する（未指定時は null）
      - saved_step が不正な場合も、canvas_states同様に既存のcleanup経路（この呼び出しが
        新規作成したファイル・JSONのみを削除）がそのまま機能する

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

        # canvas_states の検証・正規化はファイル保存の後、JSON組み立て・書き込みの前に行う。
        # drawing_materialsにより既にファイルが書き込まれた後で不正が発覚した場合でも、
        # 以下のexceptブロック（A3-0b-1実装済み・変更なし）がfiles_dirを正しく削除する。
        _canvas_states_input = canvas_states if canvas_states is not None else {}
        normalized_canvas_states = _validate_and_normalize_canvas_states(_canvas_states_input)

        normalized_saved_step = None
        if saved_step is not None:
            normalized_saved_step = _validate_saved_step(saved_step)

        normalized_test_baseline = None
        if test_baseline is not None:
            normalized_test_baseline = _validate_test_baseline_for_storage(test_baseline)

        data = {
            "id":                    estimate_id,
            "created_at":            created_at,
            "company_id":            company_id,
            "project":               project,
            "quantities":            quantities,
            "estimation":            estimation,
            "estimation_sheet_data": estimation_sheet_data,
            "files":                 files_meta,
            "canvas_states":         normalized_canvas_states,
            "saved_step":            normalized_saved_step,
            "drawing_data":          drawing_data,
            "image_data":            image_data,
            "drawing_scale":         drawing_scale,
            "original_paper":        original_paper,
            "test_baseline":         normalized_test_baseline,
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


class BackupCleanupError(RuntimeError):
    """
    update_estimate() が本番データの切替に成功した後、バックアップ（.bak-*）の削除に
    失敗した場合に送出する（A3-0b-3-1修正）。

    この例外が送出された時点で、新JSON・新ファイルは既に本番パスへ反映済みであり、
    旧データへのrollbackは行っていない（切替自体は成功しているため）。
    削除に失敗した .bak-* パスが残存している可能性があるため、手動確認・削除が必要になりうる。
    """


def update_estimate(company_id: str, estimate_id: str, project: dict, quantities: dict,
                    estimation: dict, estimation_sheet_data: dict | None = None,
                    drawing_materials: dict | None = None,
                    canvas_states: dict | None = None,
                    saved_step: int | None = None,
                    drawing_data: dict | None = None,
                    image_data: dict | None = None,
                    drawing_scale: str | None = None,
                    original_paper: str | None = None) -> None:
    """
    既存案件（estimate_id）へ安全に上書き保存する（A3-0b-3-1）。

    save_estimate() とは異なり、新規作成にはフォールバックしない：
    対象のJSONが実在しない場合は FileNotFoundError を送出する。

    drawing_materials は毎回「その時点で保持したい添付ファイルの完全な状態」を表す
    （save_estimate()と同じ仕様）。前回保存した添付ファイルのうち、今回materialsに
    含まれないものは削除される（「差し替え」「全削除」はこの完全上書き挙動の結果として実現する）。

    既存の estimate_id・created_at は維持し、新たに updated_at を追加する。

    ── 切替手順（このモジュールで最も重要な安全設計） ──
    1. 新JSON・新ファイル一式を、本番パスとは別の一時パス（.newtmp-<uuid>）へ完全に作成・検証する
       （この段階で失敗した場合、一時パスのみを削除し、既存のJSON・ファイルディレクトリには一切触れない）
    2. 既存JSON・既存ファイルディレクトリを、それぞれ一意なバックアップパス（.bak-<uuid>）へ退避する
    3. 新ファイルディレクトリ・新JSONを、退避によって空いた本番パスへ配置する
    4. 2〜3のいずれかの手順で失敗した場合は、実行済みの手順を逆順に取り消すロールバックを行い、
       既存データを退避前の状態へ完全に復元してから、元の例外を再送出する
       （ロールバック自体が失敗した場合は、元の例外とロールバック失敗の例外の両方が分かる形で
       RuntimeError を送出する。既存データが中途半端な状態のまま放置されないよう、
       この場合は手動確認が必要である旨を示す）
    5. 2〜3がすべて成功した場合、バックアップ（.bak-<uuid>）を削除する。
       この削除に失敗した場合は黙殺せず、BackupCleanupError を送出する（A3-0b-3-1修正）。
       この時点で新JSON・新ファイルの本番配置は既に成功しているため、旧データへのrollback・
       新データの取り消しは行わない。削除できたバックアップは削除したうえで、削除できなかった
       .bak-* パスのみを例外メッセージに含める。

    このモジュールでは .tmp-*・.bak-* の自動削除・自動復旧（前回の異常終了分の後始末）は行わない。
    想定外の状態（例：本番パスと衝突する一時/バックアップパスが既に存在する等）を検出した場合は、
    既存案件を一切変更せずエラーで停止する。

    test_baseline（write-once）: この関数はtest_baseline引数を一切持たない。
    既存JSON（existing_data）に"test_baseline"キーが存在する場合のみ、その値を
    そのまま新JSONへコピーする。既存JSONにキー自体が存在しない場合は、
    新JSONにもキーを一切追加しない（後付けしない）。これにより、
    どのような呼び出し方をしても既存のtest_baselineが上書き・後付けされることは
    構造的に発生しない。

    Returns: None
    """
    _validate_estimate_id(estimate_id)
    company_dir = _company_dir(company_id)
    json_path = company_dir / f"{estimate_id}.json"
    files_dir = _estimate_files_dir(company_id, estimate_id)

    if not json_path.exists():
        raise FileNotFoundError(
            f"更新対象の案件が見つかりません（新規作成にはフォールバックしません）: {estimate_id}"
        )

    # ── 既存JSONの内容を検証（想定外の状態なら変更せずエラー） ──
    try:
        existing_data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(
            f"既存JSONの読み込みに失敗しました（想定外の状態のため変更を中止します）: {estimate_id}"
        ) from e

    if not isinstance(existing_data, dict):
        raise ValueError(f"既存JSONの内容が想定外です（変更を中止します）: {estimate_id}")
    existing_estimate_id = existing_data.get("id")
    existing_created_at = existing_data.get("created_at")
    if existing_estimate_id != estimate_id or not isinstance(existing_created_at, str) or not existing_created_at:
        raise ValueError(f"既存JSONの内容が想定外です（変更を中止します）: {estimate_id}")

    if files_dir.exists() and not files_dir.is_dir():
        raise ValueError(
            f"既存のファイルディレクトリの状態が想定外です（変更を中止します）: {files_dir}"
        )

    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ── 一時パス・バックアップパスを決定（本番パスとの衝突を事前検出） ──
    tmp_suffix = uuid.uuid4().hex[:8]
    tmp_files_dir = files_dir.with_name(f"{files_dir.name}.newtmp-{tmp_suffix}")
    tmp_json_path = json_path.with_name(f"{json_path.name}.newtmp-{tmp_suffix}")
    bak_files_dir = files_dir.with_name(f"{files_dir.name}.bak-{tmp_suffix}")
    bak_json_path = json_path.with_name(f"{json_path.name}.bak-{tmp_suffix}")

    for p in (tmp_files_dir, tmp_json_path, bak_files_dir, bak_json_path):
        if p.exists():
            raise FileExistsError(
                f"一時/バックアップ用のパスが既に存在します。変更を中止します: {p}"
            )

    def _cleanup_new_only():
        """一時領域（このupdate_estimate()呼び出しが新規作成した分）のみを削除する。"""
        if tmp_files_dir.exists():
            shutil.rmtree(tmp_files_dir, ignore_errors=True)
        if tmp_json_path.exists():
            tmp_json_path.unlink(missing_ok=True)

    # ── 1. 新JSON・新ファイル一式を一時領域へ完全に作成・検証する ──
    try:
        files_meta = _empty_files_meta()
        if drawing_materials:
            files_meta = _write_estimate_files(tmp_files_dir, company_id, estimate_id, drawing_materials)

        _canvas_states_input = canvas_states if canvas_states is not None else {}
        normalized_canvas_states = _validate_and_normalize_canvas_states(_canvas_states_input)

        normalized_saved_step = None
        if saved_step is not None:
            normalized_saved_step = _validate_saved_step(saved_step)

        new_data = {
            "id":                    existing_estimate_id,
            "created_at":            existing_created_at,
            "updated_at":            updated_at,
            "company_id":            company_id,
            "project":               project,
            "quantities":            quantities,
            "estimation":            estimation,
            "estimation_sheet_data": estimation_sheet_data,
            "files":                 files_meta,
            "canvas_states":         normalized_canvas_states,
            "saved_step":            normalized_saved_step,
            "drawing_data":          drawing_data,
            "image_data":            image_data,
            "drawing_scale":         drawing_scale,
            "original_paper":        original_paper,
        }
        # test_baseline（write-once）: 既存JSONにキーが存在する場合のみ、そのままコピーする。
        # 引数として受け取らず、新規に生成・上書きすることは一切行わない。
        # 既存JSONにキー自体が無ければ、新JSONにもキーを追加しない（後付け禁止）。
        if "test_baseline" in existing_data:
            new_data["test_baseline"] = existing_data["test_baseline"]

        json_text = json.dumps(new_data, ensure_ascii=False, indent=2)
        json_bytes = json_text.encode("utf-8")

        tmp_json_path.parent.mkdir(parents=True, exist_ok=True)
        # write_text()はテキストモード書き込みのため、Windowsでは既定でuniversal newlines変換が
        # 働き、json_text中の"\n"が書き込み時に"\r\n"へ変換される。その結果、変換前の"\n"のままの
        # json_bytesとの直後の一致検証が常に失敗するバグがあったため、write_bytes()でバイト列を
        # 直接書き込む（改行コード変換を発生させない）方式へ修正した。
        tmp_json_path.write_bytes(json_bytes)
        if tmp_json_path.read_bytes() != json_bytes:
            raise IOError(f"一時JSONの書込内容が一致しません: {tmp_json_path}")
    except Exception:
        _cleanup_new_only()
        raise

    # ── 2〜3. 既存をbakへ退避し、新を本番名へ配置する。失敗時は逆順にロールバックする ──
    existing_files_dir_existed = files_dir.exists()
    completed: list[str] = []
    try:
        if existing_files_dir_existed:
            os.replace(files_dir, bak_files_dir)
            completed.append("files_backed_up")

        os.replace(json_path, bak_json_path)
        completed.append("json_backed_up")

        if tmp_files_dir.exists():
            os.replace(tmp_files_dir, files_dir)
            completed.append("files_swapped")

        os.replace(tmp_json_path, json_path)
        completed.append("json_swapped")

    except Exception as swap_error:
        try:
            if "json_swapped" in completed:
                os.replace(json_path, tmp_json_path)
            if "files_swapped" in completed:
                os.replace(files_dir, tmp_files_dir)
            if "json_backed_up" in completed:
                os.replace(bak_json_path, json_path)
            if "files_backed_up" in completed:
                os.replace(bak_files_dir, files_dir)
        except Exception as rollback_error:
            raise RuntimeError(
                "update_estimate() の切替に失敗し、さらにrollbackにも失敗しました。"
                "既存案件が中途半端な状態の可能性があるため手動確認が必要です。"
                f" estimate_id={estimate_id!r} 元エラー={swap_error!r} rollbackエラー={rollback_error!r}"
            ) from rollback_error

        # ロールバック成功：既存データは退避前の状態へ復元済み。新規側の一時ファイルのみ削除する。
        _cleanup_new_only()
        raise

    # ── 4. 切替成功：バックアップを削除する ──
    # この時点で新JSON・新ファイルは既に本番パスへ反映済み（切替自体は成功している）。
    # 削除失敗を黙殺しない。削除できたバックアップは削除したうえで、削除できなかった
    # .bak-* パスのみを例外に含める。旧データへのrollback・新データの取り消しは行わない。
    cleanup_errors: list[str] = []
    remaining_bak_paths: list[Path] = []

    if bak_files_dir.exists():
        try:
            shutil.rmtree(bak_files_dir)
        except Exception as e:
            cleanup_errors.append(
                f"ファイルバックアップの削除に失敗しました: {bak_files_dir} ({e!r})"
            )
            remaining_bak_paths.append(bak_files_dir)

    if bak_json_path.exists():
        try:
            bak_json_path.unlink()
        except Exception as e:
            cleanup_errors.append(
                f"JSONバックアップの削除に失敗しました: {bak_json_path} ({e!r})"
            )
            remaining_bak_paths.append(bak_json_path)

    if cleanup_errors:
        raise BackupCleanupError(
            "update_estimate() の切替（本番データの更新）自体は成功しましたが、"
            "バックアップ（.bak-*）の削除に失敗しました。新JSON・新ファイルは既に"
            "本番パスへ反映済みであり、旧データへのrollback・新データの取り消しは行っていません。"
            "残存したバックアップについては手動での確認・削除が必要な可能性があります。"
            f" estimate_id={estimate_id!r}"
            f" 残存バックアップパス={[str(p) for p in remaining_bak_paths]!r}"
            f" 詳細={cleanup_errors!r}"
        )


def load_estimate_file(file_meta: dict) -> dict:
    """
    save_estimate_files() / update_estimate() が生成したJSON "files" キーの1エントリ
    （filename / relative_path / content_type / size / sha256 を持つdict）を受け取り、
    実体ファイルを読み込んで返す（A3-0b-3-1、app.py側での利用を想定）。

    安全対策（A3-0b-3-1修正：許可範囲を data/estimate_files/ 配下へ限定）：
      - relative_path は絶対パスを拒否する
      - relative_path をパス区切り文字（"/"・"\\"）で分解したパス部品に ".." が1つでも
        含まれる場合は拒否する（resolve後にestimate_files配下へ戻る特殊なケースであっても、
        単純かつ厳格に拒否する）
      - 解決後のパス（candidate）が _ESTIMATE_FILES_DIR（data/estimate_files/）配下で
        あることを resolve()ベースの包含確認で検証する。relative_pathの先頭が文字列上
        "estimate_files/" であることには依存しない。改ざんされたfile_metaが
        data/estimates 等、estimate_files以外のdata配下を指す場合はValueErrorとする
      - ファイルが存在しない場合は FileNotFoundError を送出する
      - 読み込んだ実体のsize・sha256がメタデータの値と一致することを検証する
        （メタデータ自体が不正・欠落している場合も含め、一致しなければ ValueError）

    Returns: {"bytes": bytes, "filename": str | None, "content_type": str | None}
             （app.py側でst.session_stateへそのまま代入しやすい形式）
    """
    if not isinstance(file_meta, dict):
        raise ValueError(f"file_meta は dict である必要があります: {type(file_meta)!r}")

    relative_path = file_meta.get("relative_path")
    if not isinstance(relative_path, str) or not relative_path:
        raise ValueError(f"不正なrelative_pathです: {relative_path!r}")
    if os.path.isabs(relative_path):
        raise ValueError(f"relative_pathは絶対パスであってはいけません: {relative_path!r}")

    path_parts = relative_path.replace("\\", "/").split("/")
    if ".." in path_parts:
        raise ValueError(f"relative_pathに'..'を含めることはできません: {relative_path!r}")

    files_root = _ESTIMATE_FILES_DIR
    files_root_resolved = files_root.resolve()
    candidate = (files_root.parent / relative_path).resolve()
    try:
        candidate.relative_to(files_root_resolved)
    except ValueError:
        raise ValueError(
            f"relative_pathがestimate_files配下を指していません: {relative_path!r}"
        )

    if not candidate.exists():
        raise FileNotFoundError(f"保存済みファイルが見つかりません: {relative_path!r}")
    if not candidate.is_file():
        raise ValueError(f"保存済みファイルの実体が想定外の種類です: {relative_path!r}")

    data = candidate.read_bytes()

    expected_size = file_meta.get("size")
    if isinstance(expected_size, bool) or not isinstance(expected_size, int):
        raise ValueError(f"file_meta.size が不正です: {expected_size!r}")
    if len(data) != expected_size:
        raise ValueError(
            f"保存済みファイルのサイズがメタデータと一致しません: {relative_path!r} "
            f"(expected={expected_size}, actual={len(data)})"
        )

    expected_sha256 = file_meta.get("sha256")
    if not isinstance(expected_sha256, str) or not expected_sha256:
        raise ValueError(f"file_meta.sha256 が不正です: {expected_sha256!r}")
    actual_sha256 = hashlib.sha256(data).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError(f"保存済みファイルのSHA-256がメタデータと一致しません: {relative_path!r}")

    return {
        "bytes": data,
        "filename": file_meta.get("filename"),
        "content_type": file_meta.get("content_type"),
    }


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

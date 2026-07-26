# -*- coding: utf-8 -*-
"""
A3-0b-1: 図面ファイル永続化（core/estimate_storage.py）の検証。

data/estimates・data/estimate_files の実データを汚さないよう、
monkeypatchでモジュール定数を tmp_path 配下に差し替えて検証する。
"""
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import estimate_storage as es


@pytest.fixture(autouse=True)
def _isolated_data_dirs(tmp_path, monkeypatch):
    """各テストごとに data/estimates・data/estimate_files を tmp_path 配下へ差し替える。"""
    monkeypatch.setattr(es, "_ESTIMATES_DIR", tmp_path / "estimates")
    monkeypatch.setattr(es, "_ESTIMATE_FILES_DIR", tmp_path / "estimate_files")
    yield tmp_path


def _png_bytes() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color=(255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color=(0, 255, 0)).save(buf, format="JPEG")
    return buf.getvalue()


def _pdf_bytes() -> bytes:
    # 本物のPDFである必要はない（マジックバイト判定のみ確認するため）
    return b"%PDF-1.4\n%mock pdf for tests\n%%EOF"


PROJECT = {"client_name": "テスト太郎", "site_address": "東京都テスト区1-2-3"}
QUANTITIES = {"wall_area": 100.0}
ESTIMATION = {"total": 123456}


# ── 1. 保存対象なし ──────────────────────────────────────────
def test_save_estimate_without_drawing_materials_creates_no_files_dir(tmp_path):
    eid = es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION)
    files_dir = es._estimate_files_dir("nikko", eid)
    assert not files_dir.exists()

    saved = es.load_estimate("nikko", eid)
    assert saved["files"] == es._empty_files_meta()


# ── 2. pdf保存とメタデータ ──────────────────────────────────
def test_save_estimate_writes_pdf_and_metadata():
    pdf = _pdf_bytes()
    eid = es.save_estimate(
        "nikko", PROJECT, QUANTITIES, ESTIMATION,
        drawing_materials={"pdf": pdf},
    )
    saved = es.load_estimate("nikko", eid)
    meta = saved["files"]["pdf"]
    assert meta["content_type"] == "application/pdf"
    assert meta["filename"] == "drawing_source.pdf"
    assert meta["size"] == len(pdf)

    import hashlib
    assert meta["sha256"] == hashlib.sha256(pdf).hexdigest()

    on_disk = es._ESTIMATE_FILES_DIR / "nikko" / eid / "drawing_source.pdf"
    assert on_disk.read_bytes() == pdf
    assert meta["relative_path"] == f"estimate_files/nikko/{eid}/drawing_source.pdf"


# ── 3. 複数写真の連番採番・拡張子判定 ────────────────────────
def test_save_estimate_writes_multiple_photos_with_detected_extension():
    png = _png_bytes()
    jpeg = _jpeg_bytes()
    eid = es.save_estimate(
        "nikko", PROJECT, QUANTITIES, ESTIMATION,
        drawing_materials={"photos": [png, jpeg]},
    )
    saved = es.load_estimate("nikko", eid)
    photos = saved["files"]["photos"]
    assert len(photos) == 2
    assert photos[0]["relative_path"].endswith("photo_01.png")
    assert photos[0]["content_type"] == "image/png"
    assert photos[1]["relative_path"].endswith("photo_02.jpg")
    assert photos[1]["content_type"] == "image/jpeg"


# ── 4. STEP3追加図面：元ファイル名はパスに使われず表示名のみに残る ──
def test_save_estimate_step3_drawings_ignore_original_filename_in_path():
    pdf = _pdf_bytes()
    eid = es.save_estimate(
        "nikko", PROJECT, QUANTITIES, ESTIMATION,
        drawing_materials={
            "step3_drawings": [{"filename": "住吉屋邸 図面.pdf", "bytes": pdf}],
        },
    )
    saved = es.load_estimate("nikko", eid)
    entry = saved["files"]["step3_drawings"][0]
    assert entry["relative_path"] == f"estimate_files/nikko/{eid}/step3_drawing_01.pdf"
    assert "住吉屋邸" not in entry["relative_path"]
    assert entry["filename"] == "住吉屋邸 図面.pdf"  # 表示名としては保持


# ── 5. 派生画像（PNG保証）は固定拡張子 ──────────────────────
def test_save_estimate_derived_images_use_fixed_png_name():
    eid = es.save_estimate(
        "nikko", PROJECT, QUANTITIES, ESTIMATION,
        drawing_materials={
            "drawing_annotated": _png_bytes(),
            "drawing_page1_raw": _png_bytes(),
            "trace_3d": _png_bytes(),
        },
    )
    saved = es.load_estimate("nikko", eid)
    f = saved["files"]
    assert f["drawing_annotated"]["relative_path"].endswith("drawing_annotated.png")
    assert f["drawing_page1_raw"]["relative_path"].endswith("drawing_page1_raw.png")
    assert f["trace_3d"]["relative_path"].endswith("trace_3d.png")
    for key in ("drawing_annotated", "drawing_page1_raw", "trace_3d"):
        assert f[key]["content_type"] == "image/png"


# ── 6. 書き込み失敗時：新規作成分のcleanup ───────────────────
def test_save_estimate_failure_cleans_up_newly_created_files_dir(monkeypatch):
    call_count = {"n": 0}
    original = es._atomic_write_bytes

    def _flaky_write(path, data):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise IOError("simulated disk failure")
        return original(path, data)

    monkeypatch.setattr(es, "_atomic_write_bytes", _flaky_write)

    with pytest.raises(IOError):
        es.save_estimate(
            "nikko", PROJECT, QUANTITIES, ESTIMATION,
            drawing_materials={"pdf": _pdf_bytes(), "floor_plan": _pdf_bytes()},
        )

    # company配下にJSONが1件も残っていない（新規作成分のみ削除されたことの確認）
    assert list((es._ESTIMATES_DIR / "nikko").glob("*.json")) == []
    # estimate_files/nikko 配下にも孤立ディレクトリが残っていない
    nikko_files_root = es._ESTIMATE_FILES_DIR / "nikko"
    if nikko_files_root.exists():
        assert list(nikko_files_root.iterdir()) == []


# ── 7. UUID衝突時：既存データを一切消さない ──────────────────
def test_save_estimate_collision_does_not_touch_existing_data(monkeypatch):
    eid = es.save_estimate(
        "nikko", PROJECT, QUANTITIES, ESTIMATION,
        drawing_materials={"pdf": _pdf_bytes()},
    )
    existing_json = (es._ESTIMATES_DIR / "nikko" / f"{eid}.json").read_text(encoding="utf-8")
    existing_pdf = (es._ESTIMATE_FILES_DIR / "nikko" / eid / "drawing_source.pdf").read_bytes()

    class _FixedUUID:
        hex = eid + "0" * (32 - len(eid))  # uuid4().hex は32文字。先頭12文字がeidと一致するように細工

    monkeypatch.setattr(es.uuid, "uuid4", lambda: _FixedUUID())

    with pytest.raises(FileExistsError):
        es.save_estimate(
            "nikko", {"client_name": "衝突テスト"}, QUANTITIES, ESTIMATION,
            drawing_materials={"pdf": _pdf_bytes()},
        )

    # 既存データが変化していないことを確認
    assert (es._ESTIMATES_DIR / "nikko" / f"{eid}.json").read_text(encoding="utf-8") == existing_json
    assert (es._ESTIMATE_FILES_DIR / "nikko" / eid / "drawing_source.pdf").read_bytes() == existing_pdf


# ── 8. delete_estimate: JSON+ファイルディレクトリ両方削除、他案件は無傷 ──
def test_delete_estimate_removes_files_directory_and_json():
    eid = es.save_estimate(
        "nikko", PROJECT, QUANTITIES, ESTIMATION,
        drawing_materials={"pdf": _pdf_bytes()},
    )
    files_dir = es._estimate_files_dir("nikko", eid)
    assert files_dir.exists()

    ok = es.delete_estimate("nikko", eid)
    assert ok is True
    assert es.load_estimate("nikko", eid) is None
    assert not files_dir.exists()


def test_delete_estimate_does_not_touch_other_estimates_or_parent_dir():
    eid1 = es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION,
                            drawing_materials={"pdf": _pdf_bytes()})
    eid2 = es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION,
                            drawing_materials={"pdf": _pdf_bytes()})

    es.delete_estimate("nikko", eid1)

    # eid2は無傷
    assert es.load_estimate("nikko", eid2) is not None
    assert es._estimate_files_dir("nikko", eid2).exists()
    # company_id上位ディレクトリ自体は残っている
    assert (es._ESTIMATE_FILES_DIR / "nikko").exists()


def test_delete_estimate_cleans_up_orphaned_files_dir_without_json():
    """JSON書き込み失敗等で孤立したファイルディレクトリだけが残っているケースの自己修復。"""
    eid = "orphan000001"
    files_dir = es._estimate_files_dir("nikko", eid)
    files_dir.mkdir(parents=True)
    (files_dir / "dummy.pdf").write_bytes(b"dummy")

    ok = es.delete_estimate("nikko", eid)
    assert ok is False  # JSONは元々存在しなかった
    assert not files_dir.exists()


# ── 9. company_id のパス検証（既存の正常系に影響がないこと含む） ──
def test_company_dir_accepts_existing_normal_company_id():
    # 既存の正常なcompany_id（"nikko"）で従来通り動作すること
    d = es._company_dir("nikko")
    assert d.is_dir()
    assert d.name == "nikko"


@pytest.mark.parametrize("bad_id", ["../evil", "..", ".", "a/b", "a\\b", "/etc/passwd", ""])
def test_company_dir_rejects_unsafe_company_id(bad_id):
    with pytest.raises(ValueError):
        es._company_dir(bad_id)


@pytest.mark.parametrize("bad_id", ["../evil", "..", ".", "a/b", "a\\b", "/etc/passwd", ""])
def test_estimate_files_dir_rejects_unsafe_company_id(bad_id):
    with pytest.raises(ValueError):
        es._estimate_files_dir(bad_id, "abcdef012345")


@pytest.mark.parametrize("bad_id", ["", "a" * 65, "with space", "with/slash", "with\\backslash"])
def test_estimate_files_dir_rejects_unsafe_estimate_id(bad_id):
    with pytest.raises(ValueError):
        es._estimate_files_dir("nikko", bad_id)


# estimate_id検証が必要な不正値の共通セット（load_estimate/delete_estimate/_estimate_files_dirで共用）。
# "../xxx" 等のパストラバーサル文字列を含む。
UNSAFE_ESTIMATE_IDS = [
    "", "..", ".", "../evil", "../../etc/passwd",
    "a" * 65, "with space", "with/slash", "with\\backslash",
]


@pytest.mark.parametrize("bad_id", UNSAFE_ESTIMATE_IDS)
def test_load_estimate_rejects_unsafe_estimate_id(bad_id):
    """load_estimate() が estimate_id を検証せずにパスを組み立てていた問題の修正確認。"""
    with pytest.raises(ValueError):
        es.load_estimate("nikko", bad_id)


@pytest.mark.parametrize("bad_id", UNSAFE_ESTIMATE_IDS)
def test_delete_estimate_rejects_unsafe_estimate_id(bad_id):
    with pytest.raises(ValueError):
        es.delete_estimate("nikko", bad_id)


@pytest.mark.parametrize("bad_id", UNSAFE_ESTIMATE_IDS)
def test_estimate_files_dir_rejects_unsafe_estimate_id_full_set(bad_id):
    """_estimate_files_dir() 単体でも同じ不正値セットが拒否されることを確認
    （load_estimate/delete_estimate/_estimate_files_dirの3箇所すべてで検証が有効であることの確認）。"""
    with pytest.raises(ValueError):
        es._estimate_files_dir("nikko", bad_id)


def test_load_estimate_succeeds_for_normal_existing_estimate_id():
    """正常なestimate_id（save_estimate()が発行した実在id）での既存読込が引き続き成功すること。"""
    eid = es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION,
                           drawing_materials={"pdf": _pdf_bytes()})
    loaded = es.load_estimate("nikko", eid)
    assert loaded is not None
    assert loaded["id"] == eid
    assert loaded["project"] == PROJECT
    assert loaded["files"]["pdf"]["content_type"] == "application/pdf"


def test_load_estimate_returns_none_for_wellformed_but_nonexistent_id():
    """形式は正しいが存在しないestimate_idはValueErrorではなくNoneを返す（従来通り）。"""
    assert es.load_estimate("nikko", "abcdef012345") is None


# ── 10. list_estimates / load_estimate が既存company_idで従来通り動作 ──
def test_list_and_load_estimate_still_work_for_normal_company_id():
    eid = es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION)
    lst = es.list_estimates("nikko")
    assert any(e["id"] == eid for e in lst)
    loaded = es.load_estimate("nikko", eid)
    assert loaded["id"] == eid
    assert loaded["project"] == PROJECT


# ── 11. _EMPTY_FILES_META相当のdictが呼び出しごとに独立していること ──
def test_empty_files_meta_returns_independent_dict_each_call():
    a = es._empty_files_meta()
    b = es._empty_files_meta()
    a["photos"].append({"dummy": True})
    assert b["photos"] == []


# ── 12. JSONに生bytes・絶対パスが混入しないこと ──────────────
def test_json_file_has_no_raw_bytes_or_absolute_path(tmp_path):
    eid = es.save_estimate(
        "nikko", PROJECT, QUANTITIES, ESTIMATION,
        drawing_materials={"pdf": _pdf_bytes(), "photos": [_png_bytes()]},
    )
    json_path = es._ESTIMATES_DIR / "nikko" / f"{eid}.json"
    text = json_path.read_text(encoding="utf-8")
    # tmp_path配下の絶対パス文字列が紛れ込んでいないこと
    assert str(tmp_path) not in text
    data = json.loads(text)
    assert data["files"]["pdf"]["relative_path"].startswith("estimate_files/")


# ── 13. 書き込み成功後、一時ファイルが残らないこと ──────────
def test_no_leftover_tmp_files_after_success():
    eid = es.save_estimate(
        "nikko", PROJECT, QUANTITIES, ESTIMATION,
        drawing_materials={"pdf": _pdf_bytes(), "photos": [_png_bytes()]},
    )
    files_dir = es._estimate_files_dir("nikko", eid)
    leftovers = list(files_dir.glob("*.tmp-*"))
    assert leftovers == []


# ═════════════════════════════════════════════════════════════════
# A3-0b-2: canvas_states 検証・正規化・保存の検証
# ═════════════════════════════════════════════════════════════════

def _valid_canvas_states() -> dict:
    return {
        "abc123:p1": {
            "page_key": "abc123:p1",
            "viewport_transform": [1, 0, 0, 1, 0, 0],
            "objects": [
                {
                    "type": "line",
                    "orig_x1": 1,
                    "orig_y1": 2,
                    "orig_x2": 3,
                    "orig_y2": 4,
                    "length_px": 2.8284271247461903,
                },
            ],
        },
        "abc123:p2": {
            "page_key": "abc123:p2",
            "viewport_transform": [1.5, 0, 0, 1.5, 10, 20],
            "objects": [],
        },
    }


# ── 14. 正常系：canvas_statesがJSONへそのまま保存される ────────
def test_save_estimate_stores_canvas_states_matching_input():
    cs = _valid_canvas_states()
    eid = es.save_estimate(
        "nikko", PROJECT, QUANTITIES, ESTIMATION,
        canvas_states=cs,
    )
    saved = es.load_estimate("nikko", eid)
    assert saved["canvas_states"]["abc123:p1"]["objects"][0]["orig_x1"] == 1.0
    assert saved["canvas_states"]["abc123:p1"]["viewport_transform"] == [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    assert saved["canvas_states"]["abc123:p2"]["objects"] == []
    assert set(saved["canvas_states"].keys()) == {"abc123:p1", "abc123:p2"}


# ── 15. canvas_states未指定時：JSON内はnullではなく空dict ──────
def test_save_estimate_defaults_canvas_states_to_empty_dict_when_not_provided():
    eid = es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION)
    saved = es.load_estimate("nikko", eid)
    assert saved["canvas_states"] == {}


# ── 16. 数値はfloatへ正規化される ───────────────────────────────
def test_save_estimate_canvas_states_normalizes_ints_to_float():
    normalized = es._validate_and_normalize_canvas_states(_valid_canvas_states())
    page = normalized["abc123:p1"]
    assert all(isinstance(v, float) for v in page["viewport_transform"])
    obj = page["objects"][0]
    for key in ("orig_x1", "orig_y1", "orig_x2", "orig_y2", "length_px"):
        assert isinstance(obj[key], float)


# ── 17. 入力dictを直接変更しないこと ────────────────────────────
def test_validate_and_normalize_canvas_states_does_not_mutate_input():
    cs = _valid_canvas_states()
    import copy
    cs_copy = copy.deepcopy(cs)
    es._validate_and_normalize_canvas_states(cs)
    assert cs == cs_copy


def test_save_estimate_does_not_mutate_input_canvas_states_dict():
    cs = _valid_canvas_states()
    import copy
    cs_copy = copy.deepcopy(cs)
    es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION, canvas_states=cs)
    assert cs == cs_copy


# ── 18. 単体：空dict・複数ページを正常に受理 ────────────────────
def test_validate_and_normalize_canvas_states_accepts_empty_dict():
    assert es._validate_and_normalize_canvas_states({}) == {}


def test_validate_and_normalize_canvas_states_accepts_multiple_pages_and_objects():
    cs = _valid_canvas_states()
    normalized = es._validate_and_normalize_canvas_states(cs)
    assert len(normalized) == 2
    assert normalized["abc123:p1"]["page_key"] == "abc123:p1"


# ── 19. 異常系：トップレベル・page_key・valueの型 ───────────────
@pytest.mark.parametrize("bad_value", [[], "not a dict", 123, None])
def test_validate_and_normalize_canvas_states_rejects_non_dict_top_level(bad_value):
    with pytest.raises(ValueError):
        es._validate_and_normalize_canvas_states(bad_value)


def test_validate_and_normalize_canvas_states_rejects_non_string_page_key():
    with pytest.raises(ValueError):
        es._validate_and_normalize_canvas_states({123: {"page_key": "abc", "viewport_transform": [1, 0, 0, 1, 0, 0], "objects": []}})


def test_validate_and_normalize_canvas_states_rejects_empty_string_page_key():
    with pytest.raises(ValueError):
        es._validate_and_normalize_canvas_states({"": {"page_key": "", "viewport_transform": [1, 0, 0, 1, 0, 0], "objects": []}})


def test_validate_and_normalize_canvas_states_rejects_non_dict_value():
    with pytest.raises(ValueError):
        es._validate_and_normalize_canvas_states({"p1": ["not", "a", "dict"]})


def test_validate_and_normalize_canvas_states_rejects_mismatched_inner_page_key():
    with pytest.raises(ValueError):
        es._validate_and_normalize_canvas_states({
            "p1": {"page_key": "p2", "viewport_transform": [1, 0, 0, 1, 0, 0], "objects": []},
        })


def test_validate_and_normalize_canvas_states_rejects_missing_inner_page_key():
    with pytest.raises(ValueError):
        es._validate_and_normalize_canvas_states({
            "p1": {"viewport_transform": [1, 0, 0, 1, 0, 0], "objects": []},
        })


# ── 20. 異常系：ページvalueの未知キー（部分破棄はしない） ──────
def test_validate_and_normalize_canvas_states_rejects_unknown_page_key_field():
    with pytest.raises(ValueError):
        es._validate_and_normalize_canvas_states({
            "p1": {
                "page_key": "p1",
                "viewport_transform": [1, 0, 0, 1, 0, 0],
                "objects": [],
                "unexpected_field": "value",
            },
        })


def test_validate_and_normalize_canvas_states_rejects_unknown_page_key_field_with_bytes_value():
    """未知キーの値がbytesであっても黙って削除せずValueErrorにする。"""
    with pytest.raises(ValueError):
        es._validate_and_normalize_canvas_states({
            "p1": {
                "page_key": "p1",
                "viewport_transform": [1, 0, 0, 1, 0, 0],
                "objects": [],
                "raw_bytes": b"should not be silently dropped",
            },
        })


def test_validate_and_normalize_canvas_states_rejects_mixed_type_unknown_page_keys_without_typeerror():
    """未知キーにstrとintが混在していても、エラーメッセージ組み立て中にTypeErrorを起こさず
    ValueErrorとして拒否できること（sorted()でのキー同士の直接比較を避けている確認）。"""
    with pytest.raises(ValueError):
        es._validate_and_normalize_canvas_states({
            "p1": {
                "page_key": "p1",
                "viewport_transform": [1, 0, 0, 1, 0, 0],
                "objects": [],
                "unexpected_field": "value",
                42: "int key value",
            },
        })


def test_validate_and_normalize_canvas_states_rejects_int_only_unknown_page_key():
    """未知キーが整数キーのみの場合もValueErrorになること。"""
    with pytest.raises(ValueError):
        es._validate_and_normalize_canvas_states({
            "p1": {
                "page_key": "p1",
                "viewport_transform": [1, 0, 0, 1, 0, 0],
                "objects": [],
                99: "int only unknown key",
            },
        })


# ── 21. 異常系：viewport_transform ───────────────────────────────
@pytest.mark.parametrize("bad_vt", [
    [1, 0, 0, 1, 0],            # 長さ5
    [1, 0, 0, 1, 0, 0, 0],      # 長さ7
    "not a list",
    None,
])
def test_validate_and_normalize_canvas_states_rejects_viewport_transform_wrong_shape(bad_vt):
    with pytest.raises(ValueError):
        es._validate_and_normalize_canvas_states({
            "p1": {"page_key": "p1", "viewport_transform": bad_vt, "objects": []},
        })


@pytest.mark.parametrize("bad_element", [float("nan"), float("inf"), float("-inf")])
def test_validate_and_normalize_canvas_states_rejects_viewport_transform_non_finite(bad_element):
    with pytest.raises(ValueError):
        es._validate_and_normalize_canvas_states({
            "p1": {"page_key": "p1", "viewport_transform": [bad_element, 0, 0, 1, 0, 0], "objects": []},
        })


def test_validate_and_normalize_canvas_states_rejects_viewport_transform_bool_element():
    with pytest.raises(ValueError):
        es._validate_and_normalize_canvas_states({
            "p1": {"page_key": "p1", "viewport_transform": [True, 0, 0, 1, 0, 0], "objects": []},
        })


# ── 22. 異常系：objects / 各object ───────────────────────────────
def test_validate_and_normalize_canvas_states_rejects_objects_not_list():
    with pytest.raises(ValueError):
        es._validate_and_normalize_canvas_states({
            "p1": {"page_key": "p1", "viewport_transform": [1, 0, 0, 1, 0, 0], "objects": "not a list"},
        })


def test_validate_and_normalize_canvas_states_rejects_object_not_dict():
    with pytest.raises(ValueError):
        es._validate_and_normalize_canvas_states({
            "p1": {"page_key": "p1", "viewport_transform": [1, 0, 0, 1, 0, 0], "objects": ["not a dict"]},
        })


def test_validate_and_normalize_canvas_states_rejects_object_type_not_line():
    with pytest.raises(ValueError):
        es._validate_and_normalize_canvas_states({
            "p1": {
                "page_key": "p1",
                "viewport_transform": [1, 0, 0, 1, 0, 0],
                "objects": [{"type": "polygon", "orig_x1": 0, "orig_y1": 0, "orig_x2": 1, "orig_y2": 1, "length_px": 1.0}],
            },
        })


@pytest.mark.parametrize("missing_key", ["orig_x1", "orig_y1", "orig_x2", "orig_y2", "length_px"])
def test_validate_and_normalize_canvas_states_rejects_object_missing_numeric_field(missing_key):
    obj = {"type": "line", "orig_x1": 0, "orig_y1": 0, "orig_x2": 1, "orig_y2": 1, "length_px": 1.0}
    del obj[missing_key]
    with pytest.raises(ValueError):
        es._validate_and_normalize_canvas_states({
            "p1": {"page_key": "p1", "viewport_transform": [1, 0, 0, 1, 0, 0], "objects": [obj]},
        })


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_validate_and_normalize_canvas_states_rejects_object_non_finite_numeric_field(bad_value):
    obj = {"type": "line", "orig_x1": bad_value, "orig_y1": 0, "orig_x2": 1, "orig_y2": 1, "length_px": 1.0}
    with pytest.raises(ValueError):
        es._validate_and_normalize_canvas_states({
            "p1": {"page_key": "p1", "viewport_transform": [1, 0, 0, 1, 0, 0], "objects": [obj]},
        })


def test_validate_and_normalize_canvas_states_rejects_object_bool_numeric_field():
    obj = {"type": "line", "orig_x1": True, "orig_y1": 0, "orig_x2": 1, "orig_y2": 1, "length_px": 1.0}
    with pytest.raises(ValueError):
        es._validate_and_normalize_canvas_states({
            "p1": {"page_key": "p1", "viewport_transform": [1, 0, 0, 1, 0, 0], "objects": [obj]},
        })


# ── 23. 異常系：line objectの未知キー（部分破棄はしない） ──────
def test_validate_and_normalize_canvas_states_rejects_unknown_object_field():
    obj = {
        "type": "line", "orig_x1": 0, "orig_y1": 0, "orig_x2": 1, "orig_y2": 1, "length_px": 1.0,
        "color": "red",
    }
    with pytest.raises(ValueError):
        es._validate_and_normalize_canvas_states({
            "p1": {"page_key": "p1", "viewport_transform": [1, 0, 0, 1, 0, 0], "objects": [obj]},
        })


def test_validate_and_normalize_canvas_states_rejects_unknown_object_field_with_bytes_value():
    """line objectの未知キーの値がbytesであっても黙って削除せずValueErrorにする。"""
    obj = {
        "type": "line", "orig_x1": 0, "orig_y1": 0, "orig_x2": 1, "orig_y2": 1, "length_px": 1.0,
        "raw_bytes": b"should not be silently dropped",
    }
    with pytest.raises(ValueError):
        es._validate_and_normalize_canvas_states({
            "p1": {"page_key": "p1", "viewport_transform": [1, 0, 0, 1, 0, 0], "objects": [obj]},
        })


def test_validate_and_normalize_canvas_states_rejects_mixed_type_unknown_object_keys_without_typeerror():
    """line objectの未知キーにstrとintが混在していても、エラーメッセージ組み立て中に
    TypeErrorを起こさずValueErrorとして拒否できること。"""
    obj = {
        "type": "line", "orig_x1": 0, "orig_y1": 0, "orig_x2": 1, "orig_y2": 1, "length_px": 1.0,
        "color": "red",
        7: "int key value",
    }
    with pytest.raises(ValueError):
        es._validate_and_normalize_canvas_states({
            "p1": {"page_key": "p1", "viewport_transform": [1, 0, 0, 1, 0, 0], "objects": [obj]},
        })


# ── 24. 統合：save_estimate()経由でも不正canvas_statesはValueError＋残骸なし ──
def test_save_estimate_raises_valueerror_and_leaves_no_residue_when_canvas_states_invalid():
    bad_cs = {"p1": {"page_key": "p1", "viewport_transform": "not a list", "objects": []}}
    with pytest.raises(ValueError):
        es.save_estimate(
            "nikko", PROJECT, QUANTITIES, ESTIMATION,
            drawing_materials={"pdf": _pdf_bytes(), "photos": [_png_bytes()]},
            canvas_states=bad_cs,
        )
    assert list((es._ESTIMATES_DIR / "nikko").glob("*.json")) == []
    nikko_files_root = es._ESTIMATE_FILES_DIR / "nikko"
    if nikko_files_root.exists():
        assert list(nikko_files_root.iterdir()) == []


def test_save_estimate_raises_valueerror_and_leaves_no_residue_when_canvas_states_has_unknown_key():
    """未知のキーを含むcanvas_statesを渡した場合も、JSON・案件ファイルディレクトリの両方が残らないこと。"""
    bad_cs = {
        "p1": {
            "page_key": "p1",
            "viewport_transform": [1, 0, 0, 1, 0, 0],
            "objects": [],
            "unexpected_field": "value",
        },
    }
    with pytest.raises(ValueError):
        es.save_estimate(
            "nikko", PROJECT, QUANTITIES, ESTIMATION,
            drawing_materials={"pdf": _pdf_bytes(), "photos": [_png_bytes()]},
            canvas_states=bad_cs,
        )
    assert list((es._ESTIMATES_DIR / "nikko").glob("*.json")) == []
    nikko_files_root = es._ESTIMATE_FILES_DIR / "nikko"
    if nikko_files_root.exists():
        assert list(nikko_files_root.iterdir()) == []


# ── 25. 後方互換：canvas_statesキーの無い既存JSONもload_estimate()で読める ──
def test_load_estimate_existing_json_without_canvas_states_key_still_loads():
    eid = es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION)
    json_path = es._ESTIMATES_DIR / "nikko" / f"{eid}.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert "canvas_states" in data
    del data["canvas_states"]  # 既存（A3-0b-2以前）形式を再現
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    loaded = es.load_estimate("nikko", eid)
    assert loaded is not None
    assert "canvas_states" not in loaded  # {}を補完する変更はまだ行わない（A3-0b-3の対象）
    assert loaded["id"] == eid


# ═════════════════════════════════════════════════════════════════
# A3-0b-3-1: saved_step等の保存 / update_estimate() / load_estimate_file()
# ═════════════════════════════════════════════════════════════════

def _flaky_replace(monkeypatch, module, should_fail):
    """
    os.replace() をパターンマッチで選択的に失敗させるヘルパー。

    should_fail(src_name: str, dst_name: str) -> bool を満たす呼び出しのみ失敗させる。
    _atomic_write_bytes() 内部の一時ファイル名は ".tmp-<uuid>" 接尾辞（".newtmp-"は含まない）
    のため、update_estimate() 自身のswap/backup操作（".newtmp-" / ".bak-"接尾辞）とは
    名前で明確に区別できる。呼び出し回数のカウントには依存しない。
    """
    original_replace = module.os.replace

    def _fake(src, dst):
        src_name = Path(src).name
        dst_name = Path(dst).name
        if should_fail(src_name, dst_name):
            raise OSError(f"simulated os.replace failure: {src_name} -> {dst_name}")
        return original_replace(src, dst)

    monkeypatch.setattr(module.os, "replace", _fake)


PROJECT2 = {"client_name": "テスト次郎", "site_address": "東京都テスト区9-9-9"}
QUANTITIES2 = {"wall_area": 200.0}
ESTIMATION2 = {"total": 654321}


# ── 26. save_estimate(): saved_step等5項目の保存 ────────────────
def test_save_estimate_stores_saved_step_and_extra_fields():
    eid = es.save_estimate(
        "nikko", PROJECT, QUANTITIES, ESTIMATION,
        saved_step=3,
        drawing_data={"lines": [1, 2, 3]},
        image_data={"width": 100, "height": 200},
        drawing_scale="1:100",
        original_paper="A3",
    )
    saved = es.load_estimate("nikko", eid)
    assert saved["saved_step"] == 3
    assert saved["drawing_data"] == {"lines": [1, 2, 3]}
    assert saved["image_data"] == {"width": 100, "height": 200}
    assert saved["drawing_scale"] == "1:100"
    assert saved["original_paper"] == "A3"


def test_save_estimate_defaults_saved_step_and_extra_fields_to_null_when_not_provided():
    eid = es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION)
    saved = es.load_estimate("nikko", eid)
    assert saved["saved_step"] is None
    assert saved["drawing_data"] is None
    assert saved["image_data"] is None
    assert saved["drawing_scale"] is None
    assert saved["original_paper"] is None


@pytest.mark.parametrize("step", [1, 2, 3, 4, 5])
def test_save_estimate_accepts_saved_step_in_valid_range(step):
    eid = es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION, saved_step=step)
    saved = es.load_estimate("nikko", eid)
    assert saved["saved_step"] == step


@pytest.mark.parametrize("bad_step", [0, 6, -1, True, False, "3", 3.0, 3.5])
def test_save_estimate_rejects_invalid_saved_step(bad_step):
    with pytest.raises(ValueError):
        es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION, saved_step=bad_step)


def test_save_estimate_invalid_saved_step_leaves_no_residue():
    with pytest.raises(ValueError):
        es.save_estimate(
            "nikko", PROJECT, QUANTITIES, ESTIMATION,
            drawing_materials={"pdf": _pdf_bytes()},
            saved_step=99,
        )
    assert list((es._ESTIMATES_DIR / "nikko").glob("*.json")) == []
    nikko_files_root = es._ESTIMATE_FILES_DIR / "nikko"
    if nikko_files_root.exists():
        assert list(nikko_files_root.iterdir()) == []


def test_validate_saved_step_directly_rejects_bool():
    """boolはintのサブクラスであるため、明示的にbool除外を確認する。"""
    with pytest.raises(ValueError):
        es._validate_saved_step(True)


# ── 27. update_estimate(): 正常系ラウンドトリップ ────────────────
def test_update_estimate_roundtrip_updates_fields_and_preserves_id_and_created_at():
    eid = es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION, saved_step=1)
    original = es.load_estimate("nikko", eid)

    es.update_estimate(
        "nikko", eid, PROJECT2, QUANTITIES2, ESTIMATION2,
        saved_step=4,
    )
    updated = es.load_estimate("nikko", eid)

    assert updated["id"] == original["id"] == eid
    assert updated["created_at"] == original["created_at"]
    assert "updated_at" in updated and updated["updated_at"]
    assert updated["project"] == PROJECT2
    assert updated["quantities"] == QUANTITIES2
    assert updated["estimation"] == ESTIMATION2
    assert updated["saved_step"] == 4


# ── 28. update_estimate(): JSONのみ（ファイル無し→無し） ────────
def test_update_estimate_json_only_when_no_files_ever_existed():
    eid = es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION)
    files_dir = es._estimate_files_dir("nikko", eid)
    assert not files_dir.exists()

    es.update_estimate("nikko", eid, PROJECT2, QUANTITIES2, ESTIMATION2)

    assert not files_dir.exists()
    updated = es.load_estimate("nikko", eid)
    assert updated["files"] == es._empty_files_meta()


# ── 29. update_estimate(): 添付ファイルの差し替え ────────────────
def test_update_estimate_replaces_attachments():
    eid = es.save_estimate(
        "nikko", PROJECT, QUANTITIES, ESTIMATION,
        drawing_materials={"pdf": _pdf_bytes()},
    )
    files_dir = es._estimate_files_dir("nikko", eid)
    old_pdf_path = files_dir / "drawing_source.pdf"
    assert old_pdf_path.exists()

    # 旧pdfと内容が異なることが分かるよう、_pdf_bytes()に追加バイトを付けたPDFを使う
    new_pdf = _pdf_bytes() + b"\n%EXTRA-CONTENT-FOR-DIFF\n"
    es.update_estimate(
        "nikko", eid, PROJECT2, QUANTITIES2, ESTIMATION2,
        drawing_materials={"floor_plan": new_pdf},
    )

    updated = es.load_estimate("nikko", eid)
    assert updated["files"]["pdf"] is None
    floor_plan_meta = updated["files"]["floor_plan"]
    assert floor_plan_meta is not None

    floor_plan_path = files_dir / "floor_plan.pdf"
    assert not old_pdf_path.exists()
    assert floor_plan_path.exists()
    assert floor_plan_path.read_bytes() == new_pdf

    assert floor_plan_meta["content_type"] == "application/pdf"
    assert floor_plan_meta["size"] == len(new_pdf)
    import hashlib
    assert floor_plan_meta["sha256"] == hashlib.sha256(new_pdf).hexdigest()


# ── 30. update_estimate(): 添付ファイルの全削除 ──────────────────
def test_update_estimate_removes_all_attachments_when_materials_not_given():
    eid = es.save_estimate(
        "nikko", PROJECT, QUANTITIES, ESTIMATION,
        drawing_materials={"pdf": _pdf_bytes()},
    )
    files_dir = es._estimate_files_dir("nikko", eid)
    assert files_dir.exists()

    es.update_estimate("nikko", eid, PROJECT2, QUANTITIES2, ESTIMATION2)

    assert not files_dir.exists()
    updated = es.load_estimate("nikko", eid)
    assert updated["files"] == es._empty_files_meta()


# ── 31. update_estimate(): 更新対象が存在しない ──────────────────
def test_update_estimate_raises_filenotfounderror_when_target_missing():
    with pytest.raises(FileNotFoundError):
        es.update_estimate("nikko", "doesnotexist1", PROJECT2, QUANTITIES2, ESTIMATION2)


# ── 32. update_estimate(): Phase1（一時領域作成）失敗→既存データ無変更 ──
def test_update_estimate_invalid_saved_step_leaves_existing_data_untouched():
    eid = es.save_estimate(
        "nikko", PROJECT, QUANTITIES, ESTIMATION,
        drawing_materials={"pdf": _pdf_bytes()}, saved_step=1,
    )
    files_dir = es._estimate_files_dir("nikko", eid)
    json_path = es._ESTIMATES_DIR / "nikko" / f"{eid}.json"
    original_json_text = json_path.read_text(encoding="utf-8")
    original_pdf = (files_dir / "drawing_source.pdf").read_bytes()

    with pytest.raises(ValueError):
        es.update_estimate(
            "nikko", eid, PROJECT2, QUANTITIES2, ESTIMATION2,
            drawing_materials={"floor_plan": _pdf_bytes()},
            saved_step=999,
        )

    assert json_path.read_text(encoding="utf-8") == original_json_text
    assert (files_dir / "drawing_source.pdf").read_bytes() == original_pdf
    # 一時領域の残骸が残っていないこと
    leftovers = list(files_dir.parent.glob(f"{eid}.newtmp-*")) if files_dir.parent.exists() else []
    assert leftovers == []
    leftover_json = list(json_path.parent.glob(f"{eid}.json.newtmp-*"))
    assert leftover_json == []


def test_update_estimate_atomic_write_failure_leaves_existing_data_untouched(monkeypatch):
    """drawing_materials書込中の失敗（_atomic_write_bytesレベル）でも既存データが無変更のこと。"""
    eid = es.save_estimate(
        "nikko", PROJECT, QUANTITIES, ESTIMATION,
        drawing_materials={"pdf": _pdf_bytes()},
    )
    files_dir = es._estimate_files_dir("nikko", eid)
    json_path = es._ESTIMATES_DIR / "nikko" / f"{eid}.json"
    original_json_text = json_path.read_text(encoding="utf-8")
    original_pdf = (files_dir / "drawing_source.pdf").read_bytes()

    def _always_fail(path, data):
        raise IOError("simulated disk failure during update")

    monkeypatch.setattr(es, "_atomic_write_bytes", _always_fail)

    with pytest.raises(IOError):
        es.update_estimate(
            "nikko", eid, PROJECT2, QUANTITIES2, ESTIMATION2,
            drawing_materials={"floor_plan": _pdf_bytes()},
        )

    assert json_path.read_text(encoding="utf-8") == original_json_text
    assert (files_dir / "drawing_source.pdf").read_bytes() == original_pdf
    leftover_tmp_dirs = list(files_dir.parent.glob(f"{eid}.newtmp-*"))
    assert leftover_tmp_dirs == []


# ── 33. update_estimate(): Phase2（ファイルswap）失敗→rollbackで既存復元 ──
def test_update_estimate_rollback_when_files_swap_fails_restores_existing_data(monkeypatch):
    eid = es.save_estimate(
        "nikko", PROJECT, QUANTITIES, ESTIMATION,
        drawing_materials={"pdf": _pdf_bytes()}, saved_step=1,
    )
    files_dir = es._estimate_files_dir("nikko", eid)
    json_path = es._ESTIMATES_DIR / "nikko" / f"{eid}.json"
    original_json_text = json_path.read_text(encoding="utf-8")
    original_pdf = (files_dir / "drawing_source.pdf").read_bytes()

    def _fail_files_swap(src_name, dst_name):
        return ".newtmp-" in src_name and not dst_name.endswith(".json")

    _flaky_replace(monkeypatch, es, _fail_files_swap)

    with pytest.raises(OSError):
        es.update_estimate(
            "nikko", eid, PROJECT2, QUANTITIES2, ESTIMATION2,
            drawing_materials={"floor_plan": _pdf_bytes()}, saved_step=4,
        )

    # 既存データが完全に復元されていること
    assert json_path.exists()
    assert json_path.read_text(encoding="utf-8") == original_json_text
    assert files_dir.exists()
    assert (files_dir / "drawing_source.pdf").read_bytes() == original_pdf

    # 一時・バックアップの残骸が残っていないこと
    assert list(json_path.parent.glob(f"{eid}.json.newtmp-*")) == []
    assert list(json_path.parent.glob(f"{eid}.json.bak-*")) == []
    assert list(files_dir.parent.glob(f"{eid}.newtmp-*")) == []
    assert list(files_dir.parent.glob(f"{eid}.bak-*")) == []


# ── 34. update_estimate(): Phase2（JSON swap）失敗→rollbackで既存復元 ──
def test_update_estimate_rollback_when_json_swap_fails_restores_existing_data(monkeypatch):
    eid = es.save_estimate(
        "nikko", PROJECT, QUANTITIES, ESTIMATION,
        drawing_materials={"pdf": _pdf_bytes()}, saved_step=1,
    )
    files_dir = es._estimate_files_dir("nikko", eid)
    json_path = es._ESTIMATES_DIR / "nikko" / f"{eid}.json"
    original_json_text = json_path.read_text(encoding="utf-8")
    original_pdf = (files_dir / "drawing_source.pdf").read_bytes()

    def _fail_json_swap(src_name, dst_name):
        return ".newtmp-" in src_name and dst_name.endswith(".json")

    _flaky_replace(monkeypatch, es, _fail_json_swap)

    with pytest.raises(OSError):
        es.update_estimate(
            "nikko", eid, PROJECT2, QUANTITIES2, ESTIMATION2,
            drawing_materials={"floor_plan": _pdf_bytes()}, saved_step=4,
        )

    assert json_path.exists()
    assert json_path.read_text(encoding="utf-8") == original_json_text
    assert files_dir.exists()
    assert (files_dir / "drawing_source.pdf").read_bytes() == original_pdf

    assert list(json_path.parent.glob(f"{eid}.json.newtmp-*")) == []
    assert list(json_path.parent.glob(f"{eid}.json.bak-*")) == []
    assert list(files_dir.parent.glob(f"{eid}.newtmp-*")) == []
    assert list(files_dir.parent.glob(f"{eid}.bak-*")) == []


# ── 35. update_estimate(): JSONのみの案件でもjson swap失敗→rollback ──
def test_update_estimate_rollback_when_json_swap_fails_for_json_only_estimate(monkeypatch):
    """ファイルディレクトリが元々存在しない案件でも、JSON swap失敗時に正しくrollbackできること。"""
    eid = es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION)
    json_path = es._ESTIMATES_DIR / "nikko" / f"{eid}.json"
    original_json_text = json_path.read_text(encoding="utf-8")

    def _fail_json_swap(src_name, dst_name):
        return ".newtmp-" in src_name and dst_name.endswith(".json")

    _flaky_replace(monkeypatch, es, _fail_json_swap)

    with pytest.raises(OSError):
        es.update_estimate("nikko", eid, PROJECT2, QUANTITIES2, ESTIMATION2)

    assert json_path.exists()
    assert json_path.read_text(encoding="utf-8") == original_json_text
    files_dir = es._estimate_files_dir("nikko", eid)
    assert not files_dir.exists()
    assert list(json_path.parent.glob(f"{eid}.json.newtmp-*")) == []
    assert list(json_path.parent.glob(f"{eid}.json.bak-*")) == []


# ── 36. update_estimate(): rollback自体が失敗→RuntimeError（両方の例外を保持） ──
def test_update_estimate_rollback_failure_raises_runtimeerror_with_both_errors(monkeypatch):
    eid = es.save_estimate(
        "nikko", PROJECT, QUANTITIES, ESTIMATION,
        drawing_materials={"pdf": _pdf_bytes()}, saved_step=1,
    )
    files_dir = es._estimate_files_dir("nikko", eid)
    json_path = es._ESTIMATES_DIR / "nikko" / f"{eid}.json"

    def _fail_json_swap_and_its_rollback(src_name, dst_name):
        # 本来のswap（tmp_json_path -> json_path）を失敗させる
        if ".newtmp-" in src_name and dst_name.endswith(".json"):
            return True
        # そのrollback処理（bak_json_path -> json_path への復元）も失敗させる
        if ".bak-" in src_name and dst_name.endswith(".json"):
            return True
        return False

    _flaky_replace(monkeypatch, es, _fail_json_swap_and_its_rollback)

    with pytest.raises(RuntimeError) as exc_info:
        es.update_estimate(
            "nikko", eid, PROJECT2, QUANTITIES2, ESTIMATION2,
            drawing_materials={"floor_plan": _pdf_bytes()}, saved_step=4,
        )

    # 元のswap失敗・rollback失敗の両方の情報がRuntimeErrorから辿れること
    assert exc_info.value.__cause__ is not None
    message = str(exc_info.value)
    assert "rollback" in message.lower() or "ロールバック" in message or "rollback" in message


# ── 36b. update_estimate(): 切替成功後のbak削除失敗は黙殺せずBackupCleanupError ──
def test_update_estimate_bak_files_dir_cleanup_failure_raises_explicit_exception(monkeypatch):
    """ファイルバックアップ（.bak-*ディレクトリ）の削除失敗が明示的な例外になること。
    本番データは既に更新後の内容であり、rollbackは行われない。"""
    eid = es.save_estimate(
        "nikko", PROJECT, QUANTITIES, ESTIMATION,
        drawing_materials={"pdf": _pdf_bytes()},
    )
    files_dir = es._estimate_files_dir("nikko", eid)
    json_path = es._ESTIMATES_DIR / "nikko" / f"{eid}.json"

    original_rmtree = es.shutil.rmtree

    def _flaky_rmtree(path, *args, **kwargs):
        if ".bak-" in Path(path).name:
            raise OSError("simulated bak files dir cleanup failure")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(es.shutil, "rmtree", _flaky_rmtree)

    new_pdf = _pdf_bytes() + b"\n%NEW\n"
    with pytest.raises(es.BackupCleanupError) as exc_info:
        es.update_estimate(
            "nikko", eid, PROJECT2, QUANTITIES2, ESTIMATION2,
            drawing_materials={"floor_plan": new_pdf},
        )

    message = str(exc_info.value)
    assert eid in message
    assert ".bak-" in message

    # 本番JSON・本番ファイルは更新後の内容であること（rollbackされていない）
    updated = es.load_estimate("nikko", eid)
    assert updated["project"] == PROJECT2
    assert (files_dir / "floor_plan.pdf").read_bytes() == new_pdf
    assert not (files_dir / "drawing_source.pdf").exists()

    # 削除に失敗したファイルバックアップだけが残っていること
    remaining_bak_dirs = list(files_dir.parent.glob(f"{eid}.bak-*"))
    assert len(remaining_bak_dirs) == 1
    # 削除できたJSONバックアップは残っていないこと
    remaining_bak_jsons = list(json_path.parent.glob(f"{eid}.json.bak-*"))
    assert remaining_bak_jsons == []


def test_update_estimate_bak_json_cleanup_failure_raises_explicit_exception(monkeypatch):
    """JSONバックアップ（.bak-*ファイル）の削除失敗が明示的な例外になること。
    本番データは既に更新後の内容であり、rollbackは行われない。"""
    eid = es.save_estimate(
        "nikko", PROJECT, QUANTITIES, ESTIMATION,
        drawing_materials={"pdf": _pdf_bytes()},
    )
    files_dir = es._estimate_files_dir("nikko", eid)
    json_path = es._ESTIMATES_DIR / "nikko" / f"{eid}.json"

    original_unlink = Path.unlink

    def _flaky_unlink(self, *args, **kwargs):
        if ".json.bak-" in self.name:
            raise OSError("simulated bak json cleanup failure")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", _flaky_unlink)

    new_pdf = _pdf_bytes() + b"\n%NEW\n"
    with pytest.raises(es.BackupCleanupError) as exc_info:
        es.update_estimate(
            "nikko", eid, PROJECT2, QUANTITIES2, ESTIMATION2,
            drawing_materials={"floor_plan": new_pdf},
        )

    message = str(exc_info.value)
    assert eid in message
    assert ".bak-" in message

    updated = es.load_estimate("nikko", eid)
    assert updated["project"] == PROJECT2
    assert (files_dir / "floor_plan.pdf").read_bytes() == new_pdf

    # 削除に失敗したJSONバックアップだけが残っていること
    remaining_bak_jsons = list(json_path.parent.glob(f"{eid}.json.bak-*"))
    assert len(remaining_bak_jsons) == 1
    # 削除できたファイルバックアップは残っていないこと
    remaining_bak_dirs = list(files_dir.parent.glob(f"{eid}.bak-*"))
    assert remaining_bak_dirs == []


# ── 37. update_estimate(): 他案件・他社は無傷 ────────────────────
def test_update_estimate_does_not_touch_other_estimates_or_companies():
    eid_a = es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION,
                             drawing_materials={"pdf": _pdf_bytes()})
    eid_b = es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION,
                             drawing_materials={"pdf": _pdf_bytes()})
    eid_c = es.save_estimate("other_company", PROJECT, QUANTITIES, ESTIMATION,
                             drawing_materials={"pdf": _pdf_bytes()})

    before_b = es.load_estimate("nikko", eid_b)
    before_c = es.load_estimate("other_company", eid_c)

    es.update_estimate("nikko", eid_a, PROJECT2, QUANTITIES2, ESTIMATION2)

    assert es.load_estimate("nikko", eid_b) == before_b
    assert es.load_estimate("other_company", eid_c) == before_c


# ── 38. update_estimate(): 成功後は一時・バックアップの残骸が残らない ──
def test_update_estimate_leaves_no_tmp_or_bak_residue_after_success():
    eid = es.save_estimate(
        "nikko", PROJECT, QUANTITIES, ESTIMATION,
        drawing_materials={"pdf": _pdf_bytes()},
    )
    files_dir = es._estimate_files_dir("nikko", eid)
    json_path = es._ESTIMATES_DIR / "nikko" / f"{eid}.json"

    es.update_estimate(
        "nikko", eid, PROJECT2, QUANTITIES2, ESTIMATION2,
        drawing_materials={"floor_plan": _pdf_bytes()},
    )

    assert list(json_path.parent.glob(f"{eid}.json.newtmp-*")) == []
    assert list(json_path.parent.glob(f"{eid}.json.bak-*")) == []
    assert list(files_dir.parent.glob(f"{eid}.newtmp-*")) == []
    assert list(files_dir.parent.glob(f"{eid}.bak-*")) == []


# ── 39. update_estimate(): canvas_states・入力dictを変更しないこと ──
def test_update_estimate_does_not_mutate_input_canvas_states_dict():
    eid = es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION)
    cs = _valid_canvas_states()
    import copy
    cs_copy = copy.deepcopy(cs)
    es.update_estimate("nikko", eid, PROJECT2, QUANTITIES2, ESTIMATION2, canvas_states=cs)
    assert cs == cs_copy


# ═════════════════════════════════════════════════════════════════
# load_estimate_file(): 保存済みファイルの安全な読込
# ═════════════════════════════════════════════════════════════════

def test_load_estimate_file_returns_bytes_filename_and_content_type_on_success():
    pdf = _pdf_bytes()
    eid = es.save_estimate(
        "nikko", PROJECT, QUANTITIES, ESTIMATION,
        drawing_materials={"pdf": pdf},
    )
    saved = es.load_estimate("nikko", eid)
    file_meta = saved["files"]["pdf"]

    result = es.load_estimate_file(file_meta)
    assert result["bytes"] == pdf
    assert result["filename"] == "drawing_source.pdf"
    assert result["content_type"] == "application/pdf"


def test_load_estimate_file_raises_on_missing_file():
    file_meta = {
        "filename": "ghost.pdf",
        "relative_path": "estimate_files/nikko/doesnotexist123/ghost.pdf",
        "content_type": "application/pdf",
        "size": 10,
        "sha256": "0" * 64,
    }
    with pytest.raises(FileNotFoundError):
        es.load_estimate_file(file_meta)


def test_load_estimate_file_rejects_size_mismatch():
    pdf = _pdf_bytes()
    eid = es.save_estimate(
        "nikko", PROJECT, QUANTITIES, ESTIMATION,
        drawing_materials={"pdf": pdf},
    )
    saved = es.load_estimate("nikko", eid)
    file_meta = dict(saved["files"]["pdf"])
    file_meta["size"] = file_meta["size"] + 1
    with pytest.raises(ValueError):
        es.load_estimate_file(file_meta)


def test_load_estimate_file_rejects_sha256_mismatch():
    pdf = _pdf_bytes()
    eid = es.save_estimate(
        "nikko", PROJECT, QUANTITIES, ESTIMATION,
        drawing_materials={"pdf": pdf},
    )
    saved = es.load_estimate("nikko", eid)
    file_meta = dict(saved["files"]["pdf"])
    file_meta["sha256"] = "f" * 64
    with pytest.raises(ValueError):
        es.load_estimate_file(file_meta)


@pytest.mark.parametrize("bad_relative_path", [
    "/etc/passwd",
    "../../etc/passwd",
    "estimate_files/../../../etc/passwd",
    "",
    None,
    123,
])
def test_load_estimate_file_rejects_unsafe_relative_path(bad_relative_path):
    file_meta = {
        "filename": "x.pdf",
        "relative_path": bad_relative_path,
        "content_type": "application/pdf",
        "size": 0,
        "sha256": "0" * 64,
    }
    with pytest.raises(ValueError):
        es.load_estimate_file(file_meta)


def test_load_estimate_file_rejects_relative_path_escaping_data_dir_via_resolve():
    """絶対パスではないが resolve() 後に data/ 配下を逸脱する相対パスも拒否すること。"""
    file_meta = {
        "filename": "x.pdf",
        "relative_path": "estimate_files/../../outside.pdf",
        "content_type": "application/pdf",
        "size": 0,
        "sha256": "0" * 64,
    }
    with pytest.raises(ValueError):
        es.load_estimate_file(file_meta)


def test_load_estimate_file_rejects_path_pointing_into_estimates_directory():
    """estimate_files以外のdata配下（data/estimates等）を指すrelative_pathは、
    実在するファイルであっても拒否すること（文字列上の"estimate_files/"接頭辞に依存しない
    resolve()ベースの包含確認の確認。修正1）。"""
    eid = es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION)
    json_path = es._ESTIMATES_DIR / "nikko" / f"{eid}.json"
    assert json_path.exists()

    import hashlib
    file_meta = {
        "filename": "leak.json",
        "relative_path": f"estimates/nikko/{eid}.json",
        "content_type": "application/json",
        "size": json_path.stat().st_size,
        "sha256": hashlib.sha256(json_path.read_bytes()).hexdigest(),
    }
    with pytest.raises(ValueError):
        es.load_estimate_file(file_meta)


def test_load_estimate_file_allows_normal_file_directly_under_estimate_files_dir():
    """_ESTIMATE_FILES_DIR配下の正常な案件ファイルは従来通り読めること（修正1後の回帰確認）。"""
    png = _png_bytes()
    eid = es.save_estimate(
        "nikko", PROJECT, QUANTITIES, ESTIMATION,
        drawing_materials={"photos": [png]},
    )
    saved = es.load_estimate("nikko", eid)
    file_meta = saved["files"]["photos"][0]
    result = es.load_estimate_file(file_meta)
    assert result["bytes"] == png


def test_load_estimate_file_rejects_relative_path_with_dotdot_even_if_resolves_back_into_estimate_files():
    """パス部品に'..'が含まれる場合は、resolve後にestimate_files配下へ戻る場合であっても
    単純かつ厳格に拒否する（修正1の仕様：'..'を1つでも含めば拒否）。"""
    eid = es.save_estimate(
        "nikko", PROJECT, QUANTITIES, ESTIMATION,
        drawing_materials={"pdf": _pdf_bytes()},
    )
    saved = es.load_estimate("nikko", eid)
    real_meta = saved["files"]["pdf"]
    sneaky_path = f"estimate_files/nikko/{eid}/../{eid}/drawing_source.pdf"

    # sneaky_pathがresolve後には本来の実ファイルと同じ場所を指すことの確認（テストの前提確認）
    files_root = es._ESTIMATE_FILES_DIR
    resolved = (files_root.parent / sneaky_path).resolve()
    assert resolved == (files_root / "nikko" / eid / "drawing_source.pdf").resolve()

    file_meta = dict(real_meta)
    file_meta["relative_path"] = sneaky_path
    with pytest.raises(ValueError):
        es.load_estimate_file(file_meta)


def test_load_estimate_file_rejects_non_dict_file_meta():
    with pytest.raises(ValueError):
        es.load_estimate_file(["not", "a", "dict"])


def test_load_estimate_file_rejects_missing_size_or_sha256():
    pdf = _pdf_bytes()
    eid = es.save_estimate(
        "nikko", PROJECT, QUANTITIES, ESTIMATION,
        drawing_materials={"pdf": pdf},
    )
    saved = es.load_estimate("nikko", eid)
    file_meta_no_size = dict(saved["files"]["pdf"])
    del file_meta_no_size["size"]
    with pytest.raises(ValueError):
        es.load_estimate_file(file_meta_no_size)

    file_meta_no_sha = dict(saved["files"]["pdf"])
    del file_meta_no_sha["sha256"]
    with pytest.raises(ValueError):
        es.load_estimate_file(file_meta_no_sha)


# ═════════════════════════════════════════════════════════════════
# A3-1: canvas_states の category（積算属性）検証・正規化・保存の検証
#
# 設計方針（project_a3_canvas_design.md「A3-1 実装スコープ確定」節を参照）:
#   category は「色分け」ではなく線オブジェクトの積算属性であり、CANVAS_CATEGORIES
#   （core.estimate_storage内で定義される唯一の正本）に含まれる文字列、または省略
#   （＝未分類、Noneとして正規化）のみを許可する。color自体は保存データに含まれない。
# ═════════════════════════════════════════════════════════════════

def _valid_canvas_states_with_category(category="外壁") -> dict:
    """_valid_canvas_states() と同形状だが、objects[0]にcategoryを含む版。"""
    cs = _valid_canvas_states()
    cs["abc123:p1"]["objects"][0]["category"] = category
    return cs


# ── CANVAS_CATEGORIES: 唯一の正本の内容確認 ──────────────────────
def test_canvas_categories_contains_expected_11_values_in_order():
    assert es.CANVAS_CATEGORIES == (
        "外壁", "軒天", "破風", "鼻隠し", "雨樋", "シャッターボックス",
        "水切り", "幕板", "ベランダ床", "シーリング", "その他",
    )


# ── 正常系: 許可された各カテゴリ値がそのまま保存・復元される ──────
@pytest.mark.parametrize("category", [
    "外壁", "軒天", "破風", "鼻隠し", "雨樋", "シャッターボックス",
    "水切り", "幕板", "ベランダ床", "シーリング", "その他",
])
def test_save_estimate_stores_canvas_states_category_matching_input(category):
    cs = _valid_canvas_states_with_category(category)
    eid = es.save_estimate(
        "nikko", PROJECT, QUANTITIES, ESTIMATION,
        canvas_states=cs,
    )
    saved = es.load_estimate("nikko", eid)
    assert saved["canvas_states"]["abc123:p1"]["objects"][0]["category"] == category
    # categoryを指定しなかったp2側のobjectsは空リストのまま（影響なし）
    assert saved["canvas_states"]["abc123:p2"]["objects"] == []


# ── categoryが指定されているオブジェクトにcolorキーが含まれないこと ──
def test_validate_and_normalize_canvas_states_does_not_add_color_key():
    normalized = es._validate_and_normalize_canvas_states(_valid_canvas_states_with_category("外壁"))
    obj = normalized["abc123:p1"]["objects"][0]
    assert "color" not in obj
    assert set(obj.keys()) == {"type", "orig_x1", "orig_y1", "orig_x2", "orig_y2", "length_px", "category"}


# ── 省略時のデフォルト: categoryキーの無い既存形式のobjectはNone(未分類)になる ──
def test_validate_and_normalize_canvas_states_defaults_category_to_none_when_omitted():
    # _valid_canvas_states() はcategoryキーを含まない（A3-1以前の既存形式を再現）
    normalized = es._validate_and_normalize_canvas_states(_valid_canvas_states())
    obj = normalized["abc123:p1"]["objects"][0]
    assert obj["category"] is None


# ── 明示的にcategory: Noneを指定した場合も未分類として許可される ──
def test_validate_and_normalize_canvas_states_accepts_explicit_none_category():
    cs = _valid_canvas_states_with_category(None)
    normalized = es._validate_and_normalize_canvas_states(cs)
    assert normalized["abc123:p1"]["objects"][0]["category"] is None


# ── 異常系: 許可カテゴリ外の文字列はValueError ────────────────────
def test_validate_and_normalize_canvas_states_rejects_unknown_category_string():
    cs = _valid_canvas_states_with_category("未知のカテゴリ")
    with pytest.raises(ValueError):
        es._validate_and_normalize_canvas_states(cs)


# ── 異常系: category に数値・bool・list等の非文字列を渡すとValueError ──
@pytest.mark.parametrize("bad_category", [123, 1.5, True, False, ["外壁"], {"x": 1}])
def test_validate_and_normalize_canvas_states_rejects_non_string_category(bad_category):
    cs = _valid_canvas_states_with_category(bad_category)
    with pytest.raises(ValueError):
        es._validate_and_normalize_canvas_states(cs)


# ── 統合: save_estimate()経由でも不正categoryはValueError＋残骸なし ──
def test_save_estimate_raises_valueerror_and_leaves_no_residue_when_category_invalid():
    bad_cs = _valid_canvas_states_with_category("未知のカテゴリ")
    with pytest.raises(ValueError):
        es.save_estimate(
            "nikko", PROJECT, QUANTITIES, ESTIMATION,
            drawing_materials={"pdf": _pdf_bytes(), "photos": [_png_bytes()]},
            canvas_states=bad_cs,
        )
    assert list((es._ESTIMATES_DIR / "nikko").glob("*.json")) == []
    nikko_files_root = es._ESTIMATE_FILES_DIR / "nikko"
    if nikko_files_root.exists():
        assert list(nikko_files_root.iterdir()) == []


# ── 後方互換: categoryキーの無い既存canvas_states JSONもそのまま読み込める ──
def test_load_estimate_existing_canvas_states_without_category_key_still_loads():
    """
    A3-1より前に保存された（category未対応の）canvas_states JSONは、
    line objectがcategoryキーを持たない。load_estimate()は保存時の正規化を
    再実行しない単純なJSON読み込みであるため、そのようなobjectもそのまま
    （categoryキー無しのまま）読み込めることを確認する。

    注意: save_estimate() → _validate_and_normalize_canvas_states() は
    常にcategoryキーを補完する（省略時はNone）ため、この観点は
    save_estimate()経由では再現できない。そのため、A3-0b-2時代の
    test_load_estimate_existing_json_without_canvas_states_key_still_loads()
    と同様に、保存後のJSONを直接書き換えて旧形式を再現する。
    """
    eid = es.save_estimate(
        "nikko", PROJECT, QUANTITIES, ESTIMATION,
        canvas_states=_valid_canvas_states(),
    )
    json_path = es._ESTIMATES_DIR / "nikko" / f"{eid}.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    # 保存直後はcategoryキーが補完されていること（前提確認）
    assert "category" in data["canvas_states"]["abc123:p1"]["objects"][0]
    # A3-1以前（category未対応）の形式を再現するため、意図的にキーを取り除く
    del data["canvas_states"]["abc123:p1"]["objects"][0]["category"]
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    loaded = es.load_estimate("nikko", eid)
    assert loaded is not None
    assert loaded["canvas_states"]["abc123:p1"]["objects"][0]["orig_x1"] == 1.0
    assert "category" not in loaded["canvas_states"]["abc123:p1"]["objects"][0]


# ═══════════════════════════════════════════════════════════════
# test_baseline（AI初期値スナップショット、write-once）の検証
#
# ここで組み立てるtest_baselineは build_test_baseline()（Streamlit非依存の
# 構築関数。app.pyがSTEP2の自動積算成功直後に呼び出し、その戻り値をそのまま
# st.session_state.test_baseline へ代入する想定）が返す、正規化済み9キーdict
# である。build_test_baseline() 自体が受け付ける「素材」フィールド
# （ai_initial_quantities・app_commit・input_sources・analysis_started_at/
# completed_at）に対する検証・独立deep copyの確認は
# tests/test_test_baseline.py 側で行う（build_test_baseline()を直接呼ぶ）。
#
# このファイルでは、save_estimate()内部の防御的な再検証
# （_validate_test_baseline_for_storage）・write-once（update_estimateとの
# 関係）・保存/読込の統合的な挙動のみを検証する。異常系テストは、
# 正常なtest_baseline dict（build_test_baseline()の戻り値）を直接タンパリング
# （改ざん）することで、save_estimate()側の防御層が単独でも機能することを
# 確認する構成とする。
# ═══════════════════════════════════════════════════════════════

def _valid_test_baseline(
    input_sources=("voice", "drawing_pdf"),
    quantities=None,
    app_commit="0123456789abcdef0123456789abcdef01234567",
    started="2026-07-25T10:00:00+09:00",
    completed="2026-07-25T10:00:30+09:00",
):
    """build_test_baseline() を経由して、save_estimate() へそのまま渡せる
    正規化済み9キーdictを構築するテスト用ヘルパー。"""
    return es.build_test_baseline(
        ai_initial_quantities=quantities if quantities is not None else {"wall_area": 100.0},
        input_sources=list(input_sources),
        app_commit=app_commit,
        analysis_started_at=started,
        analysis_completed_at=completed,
    )


# ── 正常系: 成功した入力ソースのみのtest_baselineがそのまま保存される ──
def test_save_estimate_stores_test_baseline_with_derived_models_and_prompt_versions():
    tb = _valid_test_baseline(input_sources=["voice", "photos"])
    eid = es.save_estimate(
        "nikko", PROJECT, QUANTITIES, ESTIMATION, test_baseline=tb,
    )
    saved = es.load_estimate("nikko", eid)
    tb_saved = saved["test_baseline"]
    assert tb_saved["input_sources"] == ["voice", "photos"]
    assert tb_saved["models"] == {"voice": "gpt-4o", "photo": "gpt-4o"}
    assert tb_saved["prompt_versions"] == {
        "voice": "voice_extractor_v1", "photo": "image_analyzer_v1",
    }
    assert tb_saved["pipeline_version"] == "legacy_analysis_v1"
    assert tb_saved["rule_version"] == "NESESTYLE_rule_v1.0"
    assert tb_saved["app_commit"] == tb["app_commit"]
    assert tb_saved["ai_initial_quantities"] == {"wall_area": 100.0}


# ── 未指定時: test_baselineはnull（None）で保存される ──
def test_save_estimate_without_test_baseline_stores_null():
    eid = es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION)
    saved = es.load_estimate("nikko", eid)
    assert saved["test_baseline"] is None


# ── deep copy: save_estimate()呼び出し後に、build_test_baseline()へ渡した元の
# dictや、build_test_baseline()の戻り値（session_state.test_baseline相当）を
# in-place変更しても、保存済みJSONは一切影響を受けない
# （build_test_baseline()時点の独立コピーに加え、save_estimate()内部の
# _validate_test_baseline_for_storage()でも再度独立コピーする二重の安全策の確認。
# build_test_baseline()単体でのdeep copy確認はtests/test_test_baseline.py側で
# より直接的に検証している） ──
def test_test_baseline_ai_initial_quantities_is_independent_deep_copy_through_save():
    original_quantities = {"wall_area": 100.0, "nested": {"a": 1}}
    tb = _valid_test_baseline(quantities=original_quantities)
    eid = es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION, test_baseline=tb)

    # 保存後に、元のquantities dict・build_test_baseline()の戻り値tb自体の
    # 両方をin-place変更する
    original_quantities["wall_area"] = 999.0
    original_quantities["nested"]["a"] = 999
    tb["ai_initial_quantities"]["wall_area"] = 888.0

    saved = es.load_estimate("nikko", eid)
    assert saved["test_baseline"]["ai_initial_quantities"] == {"wall_area": 100.0, "nested": {"a": 1}}


# ── update_estimate: 既存test_baselineを完全に維持する ──
def test_update_estimate_preserves_existing_test_baseline_unchanged():
    tb = _valid_test_baseline()
    eid = es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION, test_baseline=tb)
    before = es.load_estimate("nikko", eid)["test_baseline"]

    es.update_estimate(
        "nikko", eid, PROJECT, {"wall_area": 200.0}, {"total": 999999},
    )
    after = es.load_estimate("nikko", eid)["test_baseline"]
    assert after == before


# ── update_estimateはtest_baseline引数を持たない（呼び出し可能なシグネチャの確認） ──
def test_update_estimate_signature_has_no_test_baseline_parameter():
    import inspect
    params = inspect.signature(es.update_estimate).parameters
    assert "test_baseline" not in params, (
        "update_estimate() は test_baseline 引数を持たない設計です"
    )


# ── baselineなし旧案件をupdate_estimateしても、test_baselineキーが新規追加されない ──
def test_update_estimate_does_not_backfill_test_baseline_for_old_case():
    eid = es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION)  # test_baseline未指定
    json_path = es._ESTIMATES_DIR / "nikko" / f"{eid}.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert "test_baseline" in data  # save_estimateはキー自体は作る（値はNone）

    # 「test_baselineキー自体が無い、さらに古い案件」を模擬するため、キーごと削除する
    del data["test_baseline"]
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    es.update_estimate("nikko", eid, PROJECT, {"wall_area": 200.0}, {"total": 999999})

    after = json.loads(json_path.read_text(encoding="utf-8"))
    assert "test_baseline" not in after, (
        "test_baselineキーの無い旧案件をupdate_estimateしても、キーを新規追加してはいけません"
    )


# ── 後方互換: test_baselineキーの無い旧案件がload_estimateでそのまま読み込める ──
def test_load_estimate_existing_json_without_test_baseline_key_still_loads():
    eid = es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION)
    json_path = es._ESTIMATES_DIR / "nikko" / f"{eid}.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    del data["test_baseline"]
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    loaded = es.load_estimate("nikko", eid)
    assert loaded is not None
    assert "test_baseline" not in loaded


# ── 異常系: 未知キーを拒否する（build_test_baseline()の戻り値をタンパリング） ──
def test_save_estimate_rejects_test_baseline_with_unknown_key():
    tb = _valid_test_baseline()
    tb["unexpected_key"] = "value"
    with pytest.raises(ValueError):
        es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION, test_baseline=tb)
    assert list((es._ESTIMATES_DIR / "nikko").glob("*.json")) == []


# ── 異常系: 必須キー欠落を拒否する（正規化済み9キーのいずれかを削除） ──
@pytest.mark.parametrize("missing_key", [
    "ai_initial_quantities", "app_commit", "models", "input_sources",
    "pipeline_version", "prompt_versions", "rule_version",
    "analysis_started_at", "analysis_completed_at",
])
def test_save_estimate_rejects_test_baseline_with_missing_key(missing_key):
    tb = _valid_test_baseline()
    del tb[missing_key]
    with pytest.raises(ValueError):
        es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION, test_baseline=tb)


# ── 異常系: 許可外のinput_sources値を拒否する（タンパリング） ──
def test_save_estimate_rejects_test_baseline_with_unknown_input_source():
    tb = _valid_test_baseline()
    tb["input_sources"] = ["voice", "unknown_source"]
    with pytest.raises(ValueError):
        es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION, test_baseline=tb)
    assert list((es._ESTIMATES_DIR / "nikko").glob("*.json")) == []


# ── 異常系: input_sourcesの重複を拒否する（タンパリング） ──
def test_save_estimate_rejects_test_baseline_with_duplicate_input_sources():
    tb = _valid_test_baseline()
    tb["input_sources"] = ["voice", "voice"]
    with pytest.raises(ValueError):
        es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION, test_baseline=tb)


# ── 異常系: app_commitの形式不正を拒否する（タンパリング） ──
@pytest.mark.parametrize("bad_commit", ["", "not-hex-zzz", "123", 12345, None, True])
def test_save_estimate_rejects_test_baseline_with_invalid_app_commit(bad_commit):
    tb = _valid_test_baseline()
    tb["app_commit"] = bad_commit
    with pytest.raises(ValueError):
        es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION, test_baseline=tb)


# ── 正常系: app_commitが"unknown"であることも許可される ──
def test_save_estimate_accepts_unknown_app_commit():
    tb = _valid_test_baseline(app_commit="unknown")
    eid = es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION, test_baseline=tb)
    saved = es.load_estimate("nikko", eid)
    assert saved["test_baseline"]["app_commit"] == "unknown"


# ── 異常系: 時刻形式の不正を拒否する（タンパリング） ──
@pytest.mark.parametrize("bad_time", [
    "2026-07-25 10:00:00+09:00",     # Tが無い
    "2026-07-25T10:00:00",           # タイムゾーンが無い
    "2026-07-25T10:00:00+00:00",     # JSTではない
    "not-a-timestamp",
    12345,
    None,
])
def test_save_estimate_rejects_test_baseline_with_invalid_time_format(bad_time):
    tb = _valid_test_baseline()
    tb["analysis_started_at"] = bad_time
    with pytest.raises(ValueError):
        es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION, test_baseline=tb)


# ── 異常系: analysis_completed_at が analysis_started_at より前の場合を拒否する（タンパリング） ──
def test_save_estimate_rejects_test_baseline_with_completed_before_started():
    tb = _valid_test_baseline()
    tb["analysis_started_at"], tb["analysis_completed_at"] = (
        tb["analysis_completed_at"], tb["analysis_started_at"],
    )
    # 元の値が同時刻でないことを前提とする（started < completed だったものを入れ替える）
    with pytest.raises(ValueError):
        es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION, test_baseline=tb)


# ── タンパリング検出: models が input_sources から導出される値と不一致 ──
def test_save_estimate_rejects_test_baseline_with_models_inconsistent_with_input_sources():
    tb = _valid_test_baseline(input_sources=["voice"])
    # input_sourcesには無い"photo"のmodelsエントリを紛れ込ませる
    tb["models"] = dict(tb["models"], photo="gpt-4o")
    with pytest.raises(ValueError):
        es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION, test_baseline=tb)


# ── タンパリング検出: prompt_versions が input_sources から導出される値と不一致 ──
def test_save_estimate_rejects_test_baseline_with_prompt_versions_inconsistent_with_input_sources():
    tb = _valid_test_baseline(input_sources=["voice"])
    tb["prompt_versions"] = dict(tb["prompt_versions"], photo="image_analyzer_v1")
    with pytest.raises(ValueError):
        es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION, test_baseline=tb)


# ── タンパリング検出: pipeline_version が書き換えられている ──
def test_save_estimate_rejects_test_baseline_with_wrong_pipeline_version():
    tb = _valid_test_baseline()
    tb["pipeline_version"] = "tampered_v9"
    with pytest.raises(ValueError):
        es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION, test_baseline=tb)


# ── タンパリング検出: rule_version が書き換えられている ──
def test_save_estimate_rejects_test_baseline_with_wrong_rule_version():
    tb = _valid_test_baseline()
    tb["rule_version"] = "tampered_v9"
    with pytest.raises(ValueError):
        es.save_estimate("nikko", PROJECT, QUANTITIES, ESTIMATION, test_baseline=tb)


# ── 異常系: 未知キー時に既存の残骸なしcleanup経路がそのまま機能する（drawing_materials併用） ──
def test_save_estimate_raises_and_leaves_no_residue_when_test_baseline_invalid():
    tb = _valid_test_baseline()
    tb["unexpected_key"] = "value"
    with pytest.raises(ValueError):
        es.save_estimate(
            "nikko", PROJECT, QUANTITIES, ESTIMATION,
            drawing_materials={"pdf": _pdf_bytes(), "photos": [_png_bytes()]},
            test_baseline=tb,
        )
    assert list((es._ESTIMATES_DIR / "nikko").glob("*.json")) == []
    nikko_files_root = es._ESTIMATE_FILES_DIR / "nikko"
    if nikko_files_root.exists():
        assert list(nikko_files_root.iterdir()) == []

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

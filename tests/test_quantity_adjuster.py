# -*- coding: utf-8 -*-
"""quantity_adjuster の apply_diff（純Python）を、APIなしで検証する"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.quantity_adjuster import apply_diff
from core.voice_extractor import build_quantities
from core.quantity_calculator import calculate_from_quantities


# 現在の積算（住吉屋邸の音声抽出相当・ガードマン2名で開始）
CUR = build_quantities({
    "wall_area": 237, "roof_area": 190, "fascia_length": 74,
    "gutter_length": 92, "water_cutoff_length": 49,
    "joint_seal_length": 202, "roof_type": "スレート",
    "do_roof": True, "guardman_count": 2,
})


def _apply(diff):
    r = apply_diff(CUR, diff)
    r["total"] = calculate_from_quantities(r["quantities"])["total"]
    return r


def test_roof_area():
    r = _apply({"roof_area": 185})
    assert r["quantities"]["roof_area"] == 185.0
    assert len(r["changes"]) == 1


def test_guardman_zero():
    r = _apply({"guardman_count": 0})
    assert r["quantities"]["guardman_count"] == 0
    assert r["changes"][0]["before"] == 2


def test_discount():
    r = _apply({"discount": 50000})
    assert r["quantities"]["discount"] == 50000


def test_multi_change():
    r = _apply({"joint_seal_length": 220, "discount": 30000})
    fields = {c["field"] for c in r["changes"]}
    assert fields == {"joint_seal_length", "discount"}


def test_bool_change():
    r = _apply({"do_roof": False})
    assert r["quantities"]["do_roof"] is False
    assert "なし" in r["changes"][0]["text"]


def test_null_ignored():
    r = _apply({"roof_area": None, "discount": None})
    assert r["changes"] == []
    # 元の値を維持していること
    assert r["quantities"]["roof_area"] == CUR["roof_area"]


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  OK  {name}")
            passed += 1
    print(f"\n{passed} tests passed")

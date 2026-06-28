# -*- coding: utf-8 -*-
"""voice_extractor の経験則補完＋積算計算を、APIなしで検証する"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.voice_extractor import build_quantities
from core.quantity_calculator import calculate_from_quantities


def total_for(raw, label):
    q = build_quantities(raw)
    est = calculate_from_quantities(q, client_name="住吉屋 栄子")
    print(f"\n=== {label} ===")
    print(f"  外壁{q['wall_area']} 屋根{q['roof_area']} 足場{q['scaffold_area']} "
          f"軒天{q['soffit_length']} 目地{q['joint_seal_length']}")
    print(f"  小計(税抜): \\{est['subtotal']:,}")
    print(f"  消費税    : \\{est['tax_amount']:,}")
    print(f"  合計(税込): \\{est['total']:,}")
    return est["total"]


# (A) 音声メモ通りの丸めた数値（task のサンプル音声テキスト相当）
raw_voice = {
    "wall_area": 237, "roof_area": 190, "fascia_length": 74,
    "gutter_length": 92, "water_cutoff_length": 49,
    "joint_seal_length": 202, "soffit_length": None,
    "roof_type": "スレート", "wall_type": "サイディング", "floors": 2,
    "do_roof": True, "do_foundation": False, "do_shutter_box": False,
    "guardman_count": None, "misc_cost": None, "discount": None,
    "client_name": "住吉屋", "site_address": None, "notes": "道路使用許可必要",
}

# (B) サンプル実測値（CLAUDE.md：合計¥3,004,836が正解の元データ）
raw_exact = dict(raw_voice)
raw_exact.update({
    "wall_area": 237.595, "roof_area": 189.87, "fascia_length": 74.6,
    "gutter_length": 92.4, "water_cutoff_length": 48.9,
    "joint_seal_length": 202.1, "soffit_length": 74.6,
})

t_voice = total_for(raw_voice, "(A) 音声メモ（丸め値）")
t_exact = total_for(raw_exact, "(B) サンプル実測値")

print("\n----------------------------------------")
print(f"目標(CLAUDE.md): \\3,004,836")
print(f"(B)実測値との差 : \\{t_exact - 3004836:+,}")
print(f"(A)音声との差   : \\{t_voice - 3004836:+,}  ({(t_voice-3004836)/3004836*100:+.2f}%)")

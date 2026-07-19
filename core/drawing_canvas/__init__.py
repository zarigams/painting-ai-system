"""
drawing_canvas – Fabric.js 4.6.0 ベースの手動計測カスタムコンポーネント。

使い方:
    from core.drawing_canvas import drawing_canvas

    result = drawing_canvas(
        image_bytes=selected_page["img_bytes"],   # PNG bytes
        image_width=selected_page["width"],        # 元画像 px 幅
        image_height=selected_page["height"],      # 元画像 px 高さ
        page_key=page_key,                         # ページ識別子 (str)
        canvas_height=600,                         # コンポーネント高さ px
    )
    # result は None または dict
    # dict 形式:
    #   {
    #     "page_key": str,
    #     "viewport_transform": [float x6],   # Fabric viewportTransform
    #     "objects": [                         # 計測線リスト
    #       {"type":"line","orig_x1":float,"orig_y1":float,
    #        "orig_x2":float,"orig_y2":float,"length_px":float},
    #       ...
    #     ]
    #   }

座標設計:
    - Fabric.js ワールド座標 = 元画像ピクセル座標
    - 背景画像は元画像サイズで配置
    - ズーム・パンは viewportTransform のみ変更
    - マウス座標は canvas.getPointer() で取得
    - 各直線に _origX1/_origY1/_origX2/_origY2/_lengthPx を保持
"""
from __future__ import annotations

import base64
import math
import os
import streamlit.components.v1 as components

# フロントエンドの HTML があるディレクトリ
_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")

# declare_component: ローカル HTML サーバーを起動して iframe として埋め込む
_drawing_canvas_component = components.declare_component(
    "drawing_canvas",
    path=_FRONTEND_DIR,
)


def drawing_canvas(
    image_bytes: bytes,
    image_width: int,
    image_height: int,
    page_key: str,
    canvas_height: int = 600,
    canvas_state: dict | None = None,
    key: str | None = None,
) -> dict | None:
    """
    Fabric.js 手動計測コンポーネントを描画し、状態全体を dict で返す。

    Parameters
    ----------
    image_bytes   : PNG バイト列（表示する図面）
    image_width   : 元画像の px 幅
    image_height  : 元画像の px 高さ
    page_key      : ページ識別子（状態分離用）
    canvas_height : コンポーネントの表示高さ（px）
    canvas_state  : 復元したい既存状態 dict（ページ切替・rerun 復元用）
    key           : Streamlit コンポーネントキー

    Returns
    -------
    dict | None
        操作完了時に正規化済み状態 dict を返す。未操作・初期描画時は None。

    正規化形式:
        {
            "page_key": str,
            "viewport_transform": [float x6],
            "objects": [
                {"type": "line", "orig_x1": float, "orig_y1": float,
                 "orig_x2": float, "orig_y2": float, "length_px": float},
                ...
            ]
        }
    """
    # 画像を base64 DataURL に変換（ローカルファイルアクセス不要、iframe 内で利用可）
    b64 = base64.b64encode(image_bytes).decode("ascii")
    image_data_url = f"data:image/png;base64,{b64}"

    component_value = _drawing_canvas_component(
        imageDataUrl=image_data_url,
        imageWidth=image_width,
        imageHeight=image_height,
        pageKey=page_key,
        canvasState=canvas_state,       # 状態全体 dict を渡す
        canvasHeight=canvas_height,     # 明示的に高さを渡す
        default=None,
        key=key or f"drawing_canvas_{page_key}",
        height=canvas_height + 44,      # TOOLBAR_H = 44px
    )

    # コンポーネントが返す値を正規化
    if component_value is None:
        return None

    # 型チェック: dict であることを保証
    if not isinstance(component_value, dict):
        return None

    # page_key 一致チェック（異なるページの値・欠落・非文字列をすべて拒否）
    received_page_key = component_value.get("page_key")
    if not isinstance(received_page_key, str) or received_page_key != page_key:
        return None

    # viewport_transform を検証（6要素、有限値、正のスケール）
    raw_vt = component_value.get("viewport_transform")
    if (
        isinstance(raw_vt, list)
        and len(raw_vt) == 6
        and all(isinstance(v, (int, float)) and math.isfinite(v) for v in raw_vt)
        and raw_vt[0] > 0
        and raw_vt[3] > 0
    ):
        vt: list[float] = [float(v) for v in raw_vt]
    else:
        # 不正値の場合は None を返して呼び出し元に無視させる
        return None

    # objects（計測線リスト）を正規化
    objects: list[dict] = []
    for item in (component_value.get("objects") or []):
        if not isinstance(item, dict):
            continue
        if item.get("type") != "line":
            continue
        try:
            x1 = float(item["orig_x1"])
            y1 = float(item["orig_y1"])
            x2 = float(item["orig_x2"])
            y2 = float(item["orig_y2"])
        except (KeyError, TypeError, ValueError):
            continue
        # 座標の有限値チェック
        if not all(math.isfinite(v) for v in (x1, y1, x2, y2)):
            continue
        # JS から受け取った length_px を検証（符号・有限値）
        try:
            js_len = float(item["length_px"])
        except (KeyError, TypeError, ValueError):
            js_len = -1.0
        if not math.isfinite(js_len) or js_len < 0:
            continue
        # Python 側で長さを再計算（JS 値に依存しない）
        calculated_length = math.hypot(x2 - x1, y2 - y1)
        objects.append(
            {
                "type": "line",
                "orig_x1": x1,
                "orig_y1": y1,
                "orig_x2": x2,
                "orig_y2": y2,
                "length_px": calculated_length,
            }
        )

    return {
        "page_key": str(component_value.get("page_key", page_key)),
        "viewport_transform": vt,
        "objects": objects,
    }

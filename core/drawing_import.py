"""
図面取込モジュール (A1)

役割：
  1. アップロードされたPDF・PNG・JPEGファイルをページ単位の画像に変換
  2. STEP3「図面手動積算」画面で表示する page dict のリストを返す

page dict の形式：
  {
    "label": str,          # 表示ラベル（例: "floor_plan.pdf - p.1"）
    "source_label": str,   # アップロード元ラベル（"floor_plan" など）
    "img_bytes": bytes,    # PNG形式の画像データ
    "width": int,          # 画像幅（px）
    "height": int,         # 画像高さ（px）
    "source_file": str,    # 元ファイル名（拡張子付き）
    "page": int,           # ページ番号（1始まり、画像は常に1）
    "file_hash": str,      # 元ファイルbytesのMD5（ソース単位の重複排除用）
  }

重複排除の方針：
  - 同一ソース（同じ file_hash）は PDF変換前にスキップ
  - 同一PDF内の複数ページはすべて保持する
  - 重複判定はソース単位（file_hash 単位）
"""

from __future__ import annotations

import hashlib
import io
import logging
from typing import Optional

logger = logging.getLogger(__name__)

RENDER_DPI = 150  # PDF→PNG変換解像度

try:
    import streamlit as st
    _HAS_STREAMLIT = True
except ImportError:
    _HAS_STREAMLIT = False


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


if _HAS_STREAMLIT:
    @st.cache_data(show_spinner=False)
    def _pdf_to_pages(
        pdf_bytes: bytes, source_label: str, file_hash: str
    ) -> tuple[list[dict], list[str]]:
        """PDF bytes → (page dict のリスト, エラーメッセージリスト)（st.cache_data でキャッシュ）

        file_hash は呼び出し元が _md5(pdf_bytes) で計算した値をそのまま渡す。
        各ページの page dict["file_hash"] に設定する（元ファイル単位のハッシュ）。
        page 番号は 1 始まり。
        """
        try:
            import fitz  # PyMuPDF
        except ImportError:
            logger.warning("PyMuPDF (fitz) が見つかりません。PDF取込をスキップします。")
            return [], []

        pages: list[dict] = []
        errors: list[str] = []
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as e:
            logger.warning("PDF を開けませんでした: %s", type(e).__name__)
            errors.append(
                f"{source_label}を読み込めませんでした。ファイルが破損している可能性があります。"
            )
            return [], errors

        if len(doc) == 0:
            errors.append(
                f"{source_label}を読み込めませんでした。ファイルが破損している可能性があります。"
            )
            return [], errors

        for page_idx in range(len(doc)):
            try:
                page = doc[page_idx]
                mat = fitz.Matrix(RENDER_DPI / 72.0, RENDER_DPI / 72.0)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img_bytes = pix.tobytes("png")
                page_num = page_idx + 1  # 1始まり
                label = f"{source_label} - p.{page_num}"
                pages.append({
                    "label": label,
                    "source_label": source_label,
                    "img_bytes": img_bytes,
                    "width": pix.width,
                    "height": pix.height,
                    "source_file": source_label,
                    "page": page_num,       # 1始まり
                    "file_hash": file_hash, # 元ファイル単位のMD5
                })
            except Exception as e:
                logger.warning("PDF p.%d の変換に失敗: %s", page_idx, type(e).__name__)
                continue
        return pages, errors

else:
    def _pdf_to_pages(
        pdf_bytes: bytes, source_label: str, file_hash: str
    ) -> tuple[list[dict], list[str]]:
        """Streamlit なし環境用（テスト等）"""
        try:
            import fitz
        except ImportError:
            return [], []
        pages: list[dict] = []
        errors: list[str] = []
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception:
            errors.append(
                f"{source_label}を読み込めませんでした。ファイルが破損している可能性があります。"
            )
            return [], errors
        if len(doc) == 0:
            errors.append(
                f"{source_label}を読み込めませんでした。ファイルが破損している可能性があります。"
            )
            return [], errors
        for page_idx in range(len(doc)):
            try:
                page = doc[page_idx]
                mat = fitz.Matrix(RENDER_DPI / 72.0, RENDER_DPI / 72.0)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img_bytes = pix.tobytes("png")
                page_num = page_idx + 1  # 1始まり
                label = f"{source_label} - p.{page_num}"
                pages.append({
                    "label": label,
                    "source_label": source_label,
                    "img_bytes": img_bytes,
                    "width": pix.width,
                    "height": pix.height,
                    "source_file": source_label,
                    "page": page_num,       # 1始まり
                    "file_hash": file_hash, # 元ファイル単位のMD5
                })
            except Exception:
                continue
        return pages, errors


def _image_to_page(
    img_bytes: bytes, source_label: str, ext: str, file_hash: str
) -> tuple[Optional[dict], Optional[str]]:
    """PNG/JPEG bytes → (page dict, エラーメッセージ)（失敗時は (None, エラー文字列)）

    file_hash は呼び出し元が _md5(img_bytes) で計算した値をそのまま渡す。
    page は画像固定で 1。
    """
    try:
        from PIL import Image
    except ImportError:
        logger.warning("Pillow が見つかりません。画像取込をスキップします。")
        return None, None

    try:
        with Image.open(io.BytesIO(img_bytes)) as img:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            png_bytes = buf.getvalue()
            width, height = img.size
    except Exception as e:
        logger.warning("画像の読込に失敗: %s", type(e).__name__)
        return None, (
            f"{source_label}を読み込めませんでした。ファイルが破損している可能性があります。"
        )

    return {
        "label": source_label,
        "source_label": source_label,
        "img_bytes": png_bytes,
        "width": width,
        "height": height,
        "source_file": source_label,
        "page": 1,          # 画像は常に1
        "file_hash": file_hash,  # 元ファイル単位のMD5
    }, None


def load_drawing_pages_with_errors(
    sources: list[tuple[str, str, bytes]],
) -> tuple[list[dict], list[str]]:
    """
    複数ファイルソースからページ画像リストを生成する（エラーリスト付き）。

    Args:
        sources: list of (source_label, ext, file_bytes)
                 source_label: 表示ラベル（ファイル名など）
                 ext: 拡張子（".pdf", ".png", ".jpg", ".jpeg" など、小文字）
                 file_bytes: ファイルのバイナリデータ

    Returns:
        (page dict のリスト, エラーメッセージリスト)
        重複排除はソース単位（同じ元ファイルbytesなら PDF変換前にスキップ）
    """
    pages: list[dict] = []
    errors: list[str] = []
    seen_source_hashes: set[str] = set()

    for source_label, ext, file_bytes in sources:
        # ── ソース単位の重複排除（変換前）──────────────────────
        file_hash = _md5(file_bytes)
        if file_hash in seen_source_hashes:
            logger.debug("重複ソースをスキップ: %s (%s)", source_label, file_hash[:8])
            continue
        seen_source_hashes.add(file_hash)

        try:
            if ext.lower() == ".pdf":
                new_pages, new_errors = _pdf_to_pages(file_bytes, source_label, file_hash)
                errors.extend(new_errors)
                pages.extend(new_pages)
            elif ext.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"):
                page, err = _image_to_page(file_bytes, source_label, ext, file_hash)
                if page is not None:
                    pages.append(page)
                if err:
                    errors.append(err)
            else:
                logger.info("未対応の拡張子をスキップ: %s", ext)

        except Exception as e:
            logger.warning("ソース '%s' の取込中にエラー: %s", source_label, type(e).__name__)
            errors.append(
                f"{source_label}を読み込めませんでした。ファイルが破損している可能性があります。"
            )

    return pages, errors


def load_drawing_pages_from_sources(
    sources: list[tuple[str, str, bytes]],
) -> list[dict]:
    """
    複数ファイルソースからページ画像リストを生成する（公開API）。

    互換ラッパー。エラー情報が必要な場合は load_drawing_pages_with_errors() を使用。

    Args:
        sources: list of (source_label, ext, file_bytes)

    Returns:
        page dict のリスト
    """
    pages, _ = load_drawing_pages_with_errors(sources)
    return pages

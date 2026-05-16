from __future__ import annotations

import re
from pathlib import Path
from statistics import median
from typing import Any

import fitz


HEADER_MAX_Y = 92.0
WIDE_BLOCK_RATIO = 0.72
COLUMN_GAP_RATIO = 0.12


def _clean_line(value: str) -> str:
    value = value.replace("\u00a0", " ")
    value = value.replace("\uf0b7", "•")
    return re.sub(r"\s+", " ", value.strip())


def _is_bold_font(font_name: str) -> bool:
    lowered = font_name.lower()
    return "bold" in lowered or "semibold" in lowered or "black" in lowered


def _rect_intersects(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> bool:
    lx0, ly0, lx1, ly1 = left
    rx0, ry0, rx1, ry1 = right
    horizontal = lx0 < rx1 and rx0 < lx1
    vertical = ly0 < ry1 and ry0 < ly1
    return horizontal and vertical


def _group_column_threshold(blocks: list[dict[str, Any]], page_width: float) -> float | None:
    x_positions = sorted(block["x0"] for block in blocks)
    if len(x_positions) < 4:
        return None

    biggest_gap = 0.0
    threshold = None
    for left, right in zip(x_positions, x_positions[1:], strict=False):
        gap = right - left
        if gap > biggest_gap:
            biggest_gap = gap
            threshold = left + gap / 2

    if biggest_gap < page_width * COLUMN_GAP_RATIO:
        return None
    return threshold


def _order_page_blocks(blocks: list[dict[str, Any]], page_width: float) -> list[dict[str, Any]]:
    structural_blocks = [
        block
        for block in blocks
        if not (
            (block["y0"] <= HEADER_MAX_Y and block["width"] >= page_width * 0.55)
            or block["width"] >= page_width * WIDE_BLOCK_RATIO
        )
    ]
    threshold = _group_column_threshold(structural_blocks, page_width)

    ordered: list[dict[str, Any]] = []
    headers: list[dict[str, Any]] = []
    columns: dict[int, list[dict[str, Any]]] = {0: [], 1: []}
    fallback: list[dict[str, Any]] = []

    for block in blocks:
        if (
            (block["y0"] <= HEADER_MAX_Y and block["width"] >= page_width * 0.55)
            or block["width"] >= page_width * WIDE_BLOCK_RATIO
        ):
            block["column"] = None
            headers.append(block)
            continue

        if threshold is None:
            block["column"] = 0
            fallback.append(block)
            continue

        block["column"] = 0 if block["x0"] < threshold else 1
        columns[block["column"]].append(block)

    ordered.extend(sorted(headers, key=lambda block: (block["y0"], block["x0"])))
    if threshold is None:
        ordered.extend(sorted(fallback, key=lambda block: (block["y0"], block["x0"])))
        return ordered

    ordered.extend(sorted(columns[0], key=lambda block: (block["y0"], block["x0"])))
    ordered.extend(sorted(columns[1], key=lambda block: (block["y0"], block["x0"])))
    return ordered


def extract_pdf_layout(path: Path) -> dict[str, Any]:
    document = fitz.open(path)
    pages: list[dict[str, Any]] = []
    all_blocks: list[dict[str, Any]] = []
    all_links: list[dict[str, Any]] = []
    body_font_samples: list[float] = []

    try:
        for page_index, page in enumerate(document):
            page_links = [
                {
                    "page": page_index,
                    "uri": item.get("uri"),
                    "rect": tuple(item.get("from")) if item.get("from") else None,
                }
                for item in page.get_links()
                if item.get("uri")
            ]
            all_links.extend(page_links)

            page_dict = page.get_text("dict")
            page_width = float(page.rect.width)
            block_items: list[dict[str, Any]] = []

            for raw_block in page_dict.get("blocks", []):
                lines = raw_block.get("lines")
                if not lines:
                    continue

                line_texts: list[str] = []
                max_font_size = 0.0
                font_sizes: list[float] = []
                bold_signals = 0
                span_count = 0

                for raw_line in lines:
                    spans = raw_line.get("spans", [])
                    text = _clean_line("".join(span.get("text", "") for span in spans))
                    if not text:
                        continue
                    line_texts.append(text)

                    for span in spans:
                        size = float(span.get("size", 0.0) or 0.0)
                        font_sizes.append(size)
                        max_font_size = max(max_font_size, size)
                        span_count += 1
                        if _is_bold_font(str(span.get("font", ""))):
                            bold_signals += 1

                if not line_texts:
                    continue

                x0, y0, x1, y1 = map(float, raw_block.get("bbox", (0.0, 0.0, 0.0, 0.0)))
                block_bbox = (x0, y0, x1, y1)
                link_uris = [
                    link["uri"]
                    for link in page_links
                    if link.get("rect") and _rect_intersects(block_bbox, link["rect"])
                ]
                average_font = sum(font_sizes) / len(font_sizes) if font_sizes else 0.0
                body_font_samples.extend(font_sizes)

                block_items.append(
                    {
                        "page": page_index,
                        "x0": x0,
                        "y0": y0,
                        "x1": x1,
                        "y1": y1,
                        "width": x1 - x0,
                        "height": y1 - y0,
                        "text": "\n".join(line_texts),
                        "lines": line_texts,
                        "max_font_size": max_font_size,
                        "avg_font_size": average_font,
                        "is_bold": bool(span_count and bold_signals >= max(1, span_count / 2)),
                        "link_uris": link_uris,
                    }
                )

            ordered_blocks = _order_page_blocks(block_items, page_width)
            pages.append(
                {
                    "page_index": page_index,
                    "width": page_width,
                    "height": float(page.rect.height),
                    "blocks": ordered_blocks,
                }
            )
            all_blocks.extend(ordered_blocks)
    finally:
        document.close()

    body_font_size = median(body_font_samples) if body_font_samples else 11.0
    text = "\n\n".join(block["text"] for block in all_blocks if block["text"])
    return {
        "parser": "pymupdf_layout",
        "page_count": len(pages),
        "block_count": len(all_blocks),
        "link_count": len(all_links),
        "body_font_size": round(float(body_font_size), 2),
        "text": text,
        "pages": pages,
        "links": all_links,
    }

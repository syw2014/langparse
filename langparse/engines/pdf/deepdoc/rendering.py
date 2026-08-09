"""
New code, not ported from upstream: deepdoc's TableStructureRecognizer emits
tables as HTML (colspan/rowspan) or as Chinese natural-language sentences --
neither matches langparse's cross-engine table shape. This module renders
deepdoc's box list into ParsedPageResult, normalizing tables to
{"rows": list[list[str]]} to match SimplePDFEngine/MinerUEngine and to keep
services/fidelity.py's TEDS scoring working across engines.
"""

from __future__ import annotations

from collections import defaultdict
from html.parser import HTMLParser

from langparse.types import ParsedElement, ParsedPageResult


class _RawTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[dict]] = []
        self._row: list[dict] | None = None
        self._cell: list[str] | None = None
        self._cell_attrs: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []
            self._cell_attrs = attrs_dict

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            text = "".join(self._cell).strip()
            colspan = int(self._cell_attrs.get("colspan", 1) or 1)
            rowspan = int(self._cell_attrs.get("rowspan", 1) or 1)
            self._row.append({"text": text, "colspan": colspan, "rowspan": rowspan})
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def _extract_raw_rows(html: str) -> list[list[dict]]:
    parser = _RawTableParser()
    parser.feed(html)
    return parser.rows


def html_table_to_rows(html: str) -> list[list[str]]:
    """Flatten an HTML table (with colspan/rowspan) into a plain row grid."""
    raw_rows = _extract_raw_rows(html)
    grid: list[list[str]] = []
    carry: dict[int, tuple[str, int]] = {}  # column -> (text, additional rows remaining)

    for raw_row in raw_rows:
        row: list[str] = []
        col = 0
        cells = list(raw_row)
        cell_index = 0
        while cell_index < len(cells) or col in carry or any(c > col for c in carry):
            if col in carry:
                text, remaining = carry.pop(col)
                row.append(text)
                if remaining > 1:
                    carry[col] = (text, remaining - 1)
                col += 1
                continue
            if cell_index >= len(cells):
                col += 1
                continue
            cell = cells[cell_index]
            cell_index += 1
            colspan = max(1, cell["colspan"])
            rowspan = max(1, cell["rowspan"])
            for _ in range(colspan):
                row.append(cell["text"])
                if rowspan > 1:
                    carry[col] = (cell["text"], rowspan - 1)
                col += 1
        grid.append(row)
    return grid


def _bbox(box: dict) -> list[float]:
    # box["top"]/box["bottom"] are in document-cumulative Y space (offset by
    # the running sum of prior pages' heights, see _layouts_rec in
    # pdf_parser.py) so boxes sort correctly across a multi-page document
    # internally. box["positions"] -- a list of
    # [page_number, left, right, top, bottom] tuples -- carries the same
    # rectangle in page-local coordinates instead, which is what a
    # ParsedElement.bbox must report (MinerUEngine's bbox is page-local too).
    # Fall back to x0/top/x1/bottom when positions is absent, e.g. for
    # hand-built test fixtures.
    positions = box.get("positions")
    if positions:
        _page_number, left, right, top, bottom = positions[0]
        return [float(left), float(top), float(right), float(bottom)]
    return [
        float(box.get("x0", 0.0)),
        float(box.get("top", 0.0)),
        float(box.get("x1", 0.0)),
        float(box.get("bottom", 0.0)),
    ]


def _rows_to_markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    lines = [f"| {' | '.join(rows[0])} |", f"| {' | '.join(['---'] * len(rows[0]))} |"]
    for row in rows[1:]:
        lines.append(f"| {' | '.join(row)} |")
    return "\n".join(lines)


def render_pages(
    boxes: list[dict], ocr_pages: dict[int, bool] | None = None
) -> list[ParsedPageResult]:
    """Render deepdoc's flat box list (from RAGFlowPdfParser.parse_into_bboxes) into pages.

    ocr_pages is an optional {page_number: bool} map (1-indexed, matching
    box["page_number"]) saying whether a page's text should be credited to
    OCR rather than the PDF's native text layer -- see
    DeepDocEngine._classify_ocr_pages, which derives it via the same
    needs_ocr() heuristic simple/ocr.py already uses. A page absent from the
    map, or the map itself omitted, defaults to False/0.
    """
    boxes_by_page: dict[int, list[dict]] = defaultdict(list)
    for box in boxes:
        boxes_by_page[box["page_number"]].append(box)

    ocr_pages = ocr_pages or {}
    pages = []
    for page_number in sorted(boxes_by_page):
        markdown_parts: list[str] = []
        plain_parts: list[str] = []
        elements: list[ParsedElement] = []
        tables: list[dict] = []
        images: list[dict] = []

        for box in boxes_by_page[page_number]:
            layout_type = box.get("layout_type") or "text"
            text = (box.get("text") or "").strip()
            bbox = _bbox(box)

            if layout_type == "table":
                rows = html_table_to_rows(text)
                tables.append({"rows": rows})
                markdown_parts.append(_rows_to_markdown_table(rows))
                elements.append(
                    ParsedElement(
                        kind="table", text=text, bbox=bbox, metadata={"layout_type": layout_type}
                    )
                )
                continue

            if layout_type == "figure":
                images.append({"caption": text, "bbox": bbox})
                if text:
                    markdown_parts.append(f"*{text}*")
                elements.append(
                    ParsedElement(
                        kind="figure", text=text, bbox=bbox, metadata={"layout_type": layout_type}
                    )
                )
                continue

            if not text:
                continue

            markdown_parts.append(f"# {text}" if layout_type == "title" else text)
            plain_parts.append(text)
            elements.append(
                ParsedElement(
                    kind=layout_type, text=text, bbox=bbox, metadata={"layout_type": layout_type}
                )
            )

        plain_text = "\n".join(plain_parts)
        page_ocr_applied = bool(ocr_pages.get(page_number, False))
        pages.append(
            ParsedPageResult(
                page_number=page_number,
                markdown_content="\n\n".join(part for part in markdown_parts if part),
                plain_text=plain_text,
                elements=elements,
                tables=tables,
                images=images,
                metadata={
                    "engine_name": "deepdoc",
                    "ocr_applied": page_ocr_applied,
                    "ocr_text_chars": len(plain_text) if page_ocr_applied else 0,
                },
            )
        )
    return pages

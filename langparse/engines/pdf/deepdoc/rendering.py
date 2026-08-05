"""
New code, not ported from upstream: deepdoc's TableStructureRecognizer emits
tables as HTML (colspan/rowspan) or as Chinese natural-language sentences --
neither matches langparse's cross-engine table shape. This module renders
deepdoc's box list into ParsedPageResult, normalizing tables to
{"rows": list[list[str]]} to match SimplePDFEngine/MinerUEngine and to keep
services/fidelity.py's TEDS scoring working across engines.
"""

from __future__ import annotations

from html.parser import HTMLParser


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

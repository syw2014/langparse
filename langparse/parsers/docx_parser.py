from pathlib import Path
from typing import Union

from langparse.core.parser import BaseParser
from langparse.types import ParsedDocumentResult, ParsedElement, ParsedPageResult

_HEADING_PREFIXES = (
    ("heading 1", "# "),
    ("title", "# "),
    ("heading 2", "## "),
    ("heading 3", "### "),
)


class DocxParser(BaseParser):
    """
    Parses .docx files to Markdown.
    Note: DOCX is a flow format, so 'page numbers' are not strictly defined.
    We treat the entire document as Page 1 for now, unless we convert to PDF first.
    """

    def parse_result(self, file_path: Union[str, Path], **kwargs) -> ParsedDocumentResult:
        path = self._resolve_existing_path(file_path)

        try:
            import docx
        except ImportError:
            raise ImportError("python-docx is required. Install with `pip install python-docx`.")

        doc = docx.Document(path)
        markdown_lines: list[str] = []
        elements: list[ParsedElement] = []
        tables: list[dict] = []

        for block in self._iter_block_items(docx, doc):
            if isinstance(block, docx.text.paragraph.Paragraph):
                rendered = self._render_paragraph(block)
                if rendered is None:
                    continue
                kind, markdown = rendered
                markdown_lines.extend([markdown, ""])
                elements.append(ParsedElement(kind=kind, text=block.text.strip()))
                continue

            rows = self._table_rows(block)
            if not rows:
                continue
            table_markdown = self._rows_to_markdown(rows)
            tables.append({"rows": rows})
            markdown_lines.extend([table_markdown, ""])
            elements.append(ParsedElement(kind="table", text=table_markdown))

        markdown_content = "\n".join(markdown_lines)
        return ParsedDocumentResult(
            source=str(path),
            filename=path.name,
            engine="docx",
            pages=[
                ParsedPageResult(
                    page_number=1,
                    markdown_content=markdown_content,
                    plain_text="\n".join(
                        element.text for element in elements if element.kind != "table"
                    ),
                    elements=elements,
                    tables=tables,
                )
            ],
            markdown_content=markdown_content,
            metadata={"extension": ".docx"},
        )

    def _iter_block_items(self, docx, parent):
        """
        Yield paragraphs and tables in document order.

        python-docx exposes paragraphs and tables as separate collections, which
        loses their interleaving, so walk the body XML directly.
        """
        from docx.oxml.table import CT_Tbl
        from docx.oxml.text.paragraph import CT_P

        parent_elm = (
            parent.element.body if isinstance(parent, docx.document.Document) else parent._element
        )
        for child in parent_elm.iterchildren():
            if isinstance(child, CT_P):
                yield docx.text.paragraph.Paragraph(child, parent)
            elif isinstance(child, CT_Tbl):
                yield docx.table.Table(child, parent)

    def _render_paragraph(self, paragraph) -> tuple[str, str] | None:
        text = paragraph.text.strip()
        if not text:
            return None

        style_name = paragraph.style.name.lower()
        for needle, prefix in _HEADING_PREFIXES:
            if needle in style_name:
                return "heading", f"{prefix}{text}"
        if "list" in style_name:
            return "list_item", f"- {text}"
        return "paragraph", text

    def _table_rows(self, table) -> list[list[str]]:
        return [
            [cell.text.strip().replace("\n", " ") for cell in row.cells] for row in table.rows
        ]

    def _rows_to_markdown(self, rows: list[list[str]]) -> str:
        width = max(len(row) for row in rows)
        padded = [row + [""] * (width - len(row)) for row in rows]
        lines = [f"| {' | '.join(padded[0])} |", f"| {' | '.join(['---'] * width)} |"]
        lines.extend(f"| {' | '.join(row)} |" for row in padded[1:])
        return "\n".join(lines)

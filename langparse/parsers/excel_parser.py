from pathlib import Path

from langparse.core.parser import BaseParser
from langparse.parsers.sniff import looks_like_ole_binary, looks_like_zip_ooxml
from langparse.types import ParsedDocumentResult, ParsedElement, ParseDiagnostics, ParsedPageResult


class ExcelParser(BaseParser):
    """
    Parses workbook facts and exposes one compatibility part per sheet.

    Sheets keep stable ordinals but are not pages, so Excel results are always
    marked ``paginated=False``.
    """

    def parse_result(self, file_path: str | Path, **kwargs) -> ParsedDocumentResult:
        path = self._resolve_existing_path(file_path)

        if looks_like_zip_ooxml(path):
            return self._parse_ooxml(path)

        try:
            import pandas as pd
        except ImportError:
            raise ImportError(
                "pandas and openpyxl are required. Install with `pip install pandas openpyxl`."
            ) from None

        # The extension names one of .csv/.xls/.xlsx, but it can lie -- a
        # workbook re-exported or renamed to .csv (or vice versa) would
        # otherwise be handed to the wrong pandas reader. Content decides:
        # a real workbook is either a ZIP-OOXML or legacy-OLE container;
        # anything else is read as delimited text regardless of its label.
        is_legacy_workbook = looks_like_ole_binary(path)
        if is_legacy_workbook:
            sheets = pd.read_excel(path, sheet_name=None)
        else:
            sheets = {None: pd.read_csv(path)}

        pages = [
            self._page_for_sheet(index + 1, sheet_name, frame)
            for index, (sheet_name, frame) in enumerate(sheets.items())
        ]

        return ParsedDocumentResult(
            source=str(path),
            filename=path.name,
            engine="excel",
            pages=pages,
            markdown_content="\n".join(page.markdown_content for page in pages),
            metadata={"extension": path.suffix, "sheet_count": len(pages)},
            paginated=False,
            diagnostics=(
                ParseDiagnostics(
                    status="partial",
                    reconstruction_passed=False,
                    unsupported_features=[
                        "Legacy OLE workbooks use the pandas compatibility adapter; "
                        "rich workbook facts are not available in Phase 1."
                    ],
                )
                if is_legacy_workbook
                else None
            ),
        )

    def _parse_ooxml(self, path: Path) -> ParsedDocumentResult:
        try:
            from langparse.workbooks.adapters import OOXMLWorkbookAdapter
            from langparse.workbooks.assembly import assemble_baseline
            from langparse.workbooks.rendering import (
                compatibility_pages,
                render_workbook_markdown,
            )
        except ImportError:
            raise ImportError(
                "openpyxl is required for OOXML workbooks. "
                "Install with `pip install langparse[excel]`."
            ) from None

        snapshot = OOXMLWorkbookAdapter().snapshot(path)
        structure, diagnostics = assemble_baseline(snapshot)
        pages = compatibility_pages(snapshot, structure)
        markdown = render_workbook_markdown(snapshot, structure)
        return ParsedDocumentResult(
            source=str(path),
            filename=path.name,
            engine="excel",
            pages=pages,
            markdown_content=markdown,
            metadata={"extension": path.suffix, "sheet_count": len(snapshot.sheets)},
            paginated=False,
            structure=structure,
            diagnostics=diagnostics,
        )

    def _page_for_sheet(self, page_number: int, sheet_name, frame) -> ParsedPageResult:
        table_markdown = frame.to_markdown(index=False)
        heading = f"## Sheet: {sheet_name}\n" if sheet_name is not None else ""
        markdown_content = f"{heading}\n{table_markdown}\n" if heading else table_markdown

        rows = [[str(column) for column in frame.columns]]
        rows.extend([[self._cell_text(value) for value in row] for row in frame.values])

        return ParsedPageResult(
            page_number=page_number,
            markdown_content=markdown_content,
            plain_text=table_markdown,
            elements=[ParsedElement(kind="table", text=table_markdown)],
            tables=[{"rows": rows, "sheet_name": sheet_name}],
            metadata={"part_kind": "sheet", "sheet_name": sheet_name, "source_range": None},
        )

    def _cell_text(self, value) -> str:
        """
        Render one cell for the structured table.

        Blank cells arrive as NaN rather than None, and a single blank promotes
        an integer column to float -- so a naive str() yields "nan" and "1.0"
        where the source held an empty cell and 1.
        """
        import pandas as pd

        if value is None or pd.isna(value):
            return ""
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

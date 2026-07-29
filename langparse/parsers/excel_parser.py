from pathlib import Path
from typing import Union

from langparse.core.parser import BaseParser
from langparse.types import ParsedDocumentResult, ParsedElement, ParsedPageResult


class ExcelParser(BaseParser):
    """
    Parses .xlsx/.csv files to Markdown Tables.
    Each Sheet is treated as a separate 'Page'.
    """

    def parse_result(self, file_path: Union[str, Path], **kwargs) -> ParsedDocumentResult:
        path = self._resolve_existing_path(file_path)

        try:
            import pandas as pd
        except ImportError:
            raise ImportError(
                "pandas and openpyxl are required. Install with `pip install pandas openpyxl`."
            )

        if path.suffix.lower() == ".csv":
            sheets = {None: pd.read_csv(path)}
        else:
            sheets = pd.read_excel(path, sheet_name=None)

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
        )

    def _page_for_sheet(self, page_number: int, sheet_name, frame) -> ParsedPageResult:
        table_markdown = frame.to_markdown(index=False)
        heading = f"### Sheet: {sheet_name}\n" if sheet_name is not None else ""
        markdown_content = f"{heading}\n{table_markdown}\n" if heading else table_markdown

        rows = [[str(column) for column in frame.columns]]
        rows.extend([["" if value is None else str(value) for value in row] for row in frame.values])

        return ParsedPageResult(
            page_number=page_number,
            markdown_content=markdown_content,
            plain_text=table_markdown,
            elements=[ParsedElement(kind="table", text=table_markdown)],
            tables=[{"rows": rows, "sheet_name": sheet_name}],
            metadata={"sheet_name": sheet_name},
        )

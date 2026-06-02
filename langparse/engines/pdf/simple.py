from langparse.core.engine import BaseEngine, PageResult
from pathlib import Path
from typing import Iterator

class BasePDFEngine(BaseEngine):
    """
    Base class specifically for PDF engines.
    """
    def __init__(self, **kwargs):
        pass

class SimplePDFEngine(BasePDFEngine):
    """
    A lightweight, dependency-free (except pdfplumber) engine.
    Good for simple, native PDFs.
    """
    
    def process(self, file_path: Path, **kwargs) -> Iterator[PageResult]:
        try:
            import pdfplumber
        except ImportError:
            raise ImportError("Please install `pdfplumber` to use the 'simple' engine.")
            
        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                # Basic text extraction
                text = page.extract_text() or ""
                tables = []
                table_markdown = []
                extract_tables = getattr(page, "extract_tables", None)
                for table in (extract_tables() if callable(extract_tables) else []) or []:
                    cleaned_table = [
                        ["" if cell is None else str(cell).strip().replace("\n", " ") for cell in row]
                        for row in table
                    ]
                    if not cleaned_table:
                        continue

                    tables.append({"rows": cleaned_table})
                    headers = cleaned_table[0]
                    table_markdown.append(f"| {' | '.join(headers)} |")
                    table_markdown.append(f"| {' | '.join(['---'] * len(headers))} |")
                    for row in cleaned_table[1:]:
                        table_markdown.append(f"| {' | '.join(row)} |")

                markdown_content = text
                if table_markdown:
                    markdown_content = "\n\n".join([text, "\n".join(table_markdown)]).strip()
                
                yield PageResult(
                    page_number=i + 1,
                    markdown_content=markdown_content,
                    plain_text=text,
                    elements=[],
                    tables=tables,
                    images=[],
                    metadata={"engine_name": "simple"},
                )

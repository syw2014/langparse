from typing import Union
from pathlib import Path
from langparse.core.parser import BaseParser
from langparse.types import Document

class AutoParser:
    """
    Factory class to automatically select the correct parser based on file extension.
    """
    
    @staticmethod
    def parse(file_path: Union[str, Path], **kwargs) -> Document:
        file_path = Path(file_path)
        ext = file_path.suffix.lower()

        parser: BaseParser = None

        if ext == ".pdf":
            from langparse.parsers.pdf_parser import PDFParser

            parser_engine = kwargs.pop("engine", "simple")
            parser = PDFParser(engine=parser_engine, **kwargs)

        elif ext in [".docx", ".doc"]:
            from langparse.parsers.docx_parser import DocxParser
            parser = DocxParser()

        elif ext in [".xlsx", ".xls", ".csv"]:
            from langparse.parsers.excel_parser import ExcelParser
            parser = ExcelParser()

        elif ext in [".md", ".txt"]:
            from langparse.parsers.markdown_parser import MarkdownParser
            parser = MarkdownParser()

        else:
            raise ValueError(f"Unsupported file extension: {ext}")

        return parser.parse(file_path, **kwargs)

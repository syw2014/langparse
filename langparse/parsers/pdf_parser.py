from pathlib import Path
from typing import Literal

from langparse.config import settings
from langparse.core.parser import BaseParser
from langparse.services.parse_service import ParseService
from langparse.types import ParsedDocumentResult


class PDFParser(BaseParser):
    """
    A universal PDF parser that delegates to specific engines.
    """

    def __init__(
        self,
        engine: Literal["simple", "mineru"] = None,
        **engine_kwargs,
    ):
        # Engine name resolves as: argument > config > default. Construction is
        # delegated so selection errors read the same here as from the CLI.
        self.engine_name = engine or settings.get("default_pdf_engine", "simple")
        self.engine = ParseService().create_engine(self.engine_name, **engine_kwargs)

    def parse_result(self, file_path: str | Path, **kwargs) -> ParsedDocumentResult:
        return ParseService().parse_result(
            file_path,
            engine_name=self.engine_name,
            engine=self.engine,
            **kwargs,
        )

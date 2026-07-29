from pathlib import Path
from typing import Union

from langparse.core.rendering import document_from_result
from langparse.types import Document, ParsedDocumentResult


class AutoParser:
    """
    Facade that parses any supported file without the caller picking a parser.

    Extension routing lives in `ParseService`, driven by
    `langparse.parsers.registry`, so this stays a convenience wrapper rather
    than a second place formats can be registered and drift.
    """

    @staticmethod
    def parse_result(file_path: Union[str, Path], **kwargs) -> ParsedDocumentResult:
        from langparse.services.parse_service import ParseService

        engine_name = kwargs.pop("engine", None) or "simple"
        return ParseService().parse_result(file_path, engine_name=engine_name, **kwargs)

    @staticmethod
    def parse(file_path: Union[str, Path], **kwargs) -> Document:
        return document_from_result(AutoParser.parse_result(file_path, **kwargs))

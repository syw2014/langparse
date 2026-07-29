from pathlib import Path
from typing import Union

from langparse.core.parser import BaseParser
from langparse.types import ParsedDocumentResult, ParsedPageResult


class MarkdownParser(BaseParser):
    """
    A simple parser for Markdown files.

    Markdown is a flow format with no page boundaries, so the whole file is one
    unpaginated page and the content passes through verbatim -- including any
    page markers the source already carries.
    """

    def parse_result(self, file_path: Union[str, Path], **kwargs) -> ParsedDocumentResult:
        path = self._resolve_existing_path(file_path)
        content = path.read_text(encoding="utf-8")

        return ParsedDocumentResult(
            source=str(path),
            filename=path.name,
            engine="markdown",
            pages=[
                ParsedPageResult(
                    page_number=1,
                    markdown_content=content,
                    plain_text=content,
                )
            ],
            markdown_content=content,
            metadata={"extension": path.suffix},
            paginated=False,
        )

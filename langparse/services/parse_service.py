from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path
from typing import Iterator, Union

from langparse.config import settings
from langparse.core.rendering import document_from_result
from langparse.engines.pdf.mineru import MinerUEngine
from langparse.engines.pdf.other import DeepDocEngine, PaddleOCRVLEngine
from langparse.engines.pdf.simple import SimplePDFEngine
from langparse.engines.pdf.vision_llm import VisionLLMEngine
from langparse.parsers.registry import (
    is_supported,
    parser_kind_for,
    unsupported_extension_error,
)
from langparse.services.output_paths import (
    output_filename,
    resolve_output_path,
    resolve_output_paths,
)
from langparse.types import Chunk, Document, ParsedDocumentResult, ParsedPageResult

ENGINE_MAP = {
    "simple": SimplePDFEngine,
    "mineru": MinerUEngine,
    "vision_llm": VisionLLMEngine,
    "deepdoc": DeepDocEngine,
    "paddle": PaddleOCRVLEngine,
}


class ParseService:
    def chunk_result(self, parsed: ParsedDocumentResult, chunker=None) -> list[Chunk]:
        """Chunk a parse result, rendering it to Markdown first."""
        from langparse.chunkers.semantic import SemanticChunker

        return (chunker or SemanticChunker()).chunk(document_from_result(parsed))

    def render_output(
        self,
        parsed: ParsedDocumentResult,
        fmt: str,
        chunks: list[Chunk] | None = None,
    ) -> str:
        if fmt == "markdown":
            if chunks is None:
                return parsed.markdown_content
            return "\n\n---\n\n".join(chunk.content for chunk in chunks)
        if fmt == "json":
            payload = asdict(parsed)
            if chunks is not None:
                payload["chunks"] = [asdict(chunk) for chunk in chunks]
            return json.dumps(payload, ensure_ascii=False, indent=2)
        raise ValueError(f"Unsupported output format: {fmt}")

    def parse_output(
        self,
        file_path,
        engine_name="simple",
        fmt="markdown",
        engine=None,
        chunk=False,
        **kwargs,
    ) -> str:
        parsed = self.parse_result(
            file_path,
            engine_name=engine_name,
            engine=engine,
            **kwargs,
        )
        return self.render_output(parsed, fmt, chunks=self.chunk_result(parsed) if chunk else None)

    def parse_batch_outputs(
        self,
        inputs,
        engine_name="simple",
        fmt="markdown",
        engine=None,
        **kwargs,
    ) -> list[tuple[Path, str]]:
        outputs = []
        active_engine = engine or self._create_engine(engine_name, **kwargs)
        for file_path in self.expand_inputs(inputs):
            outputs.append(
                (
                    file_path,
                    self.parse_output(
                        file_path,
                        engine_name=engine_name,
                        fmt=fmt,
                        engine=active_engine,
                        **kwargs,
                    ),
                )
            )
        return outputs

    def write_output(self, content: str, output_path) -> Path:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        return destination

    def write_batch_outputs(self, outputs, output_dir, fmt: str) -> list[Path]:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        outputs = list(outputs)
        # Resolve all destinations together so same-stem siblings are grouped
        # the same way BatchParseService groups them.
        relative_paths = resolve_output_paths([source for source, _ in outputs], fmt)

        written_paths = []
        for (_, content), relative in zip(outputs, relative_paths):
            destination = output_dir / relative
            self.write_output(content, destination)
            written_paths.append(destination)
        return written_paths

    def expand_inputs(self, inputs):
        paths = []
        for item in self._flatten_inputs(inputs):
            path = Path(item)
            if not path.exists():
                raise FileNotFoundError(f"File not found: {path}")
            if path.is_dir():
                paths.extend(
                    sorted(
                        child
                        for child in path.iterdir()
                        if child.is_file() and is_supported(child)
                    )
                )
            else:
                paths.append(path)
        return paths

    def parse_result(self, file_path, engine_name="simple", engine=None, **kwargs):
        """
        Parse any supported format into a ParsedDocumentResult.

        This is the one place extension routing happens; everything else reads
        the mapping from `langparse.parsers.registry`.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        kind = parser_kind_for(path)
        if kind is None:
            raise unsupported_extension_error(path)
        if kind == "pdf":
            return self._collect_pdf_document_result(
                path,
                engine_name=engine_name,
                engine=engine,
                **kwargs,
            )
        return self._parser_for_kind(kind).parse_result(path, **kwargs)

    def _parser_for_kind(self, kind: str):
        if kind == "docx":
            from langparse.parsers.docx_parser import DocxParser

            return DocxParser()
        if kind == "excel":
            from langparse.parsers.excel_parser import ExcelParser

            return ExcelParser()
        if kind == "markdown":
            from langparse.parsers.markdown_parser import MarkdownParser

            return MarkdownParser()
        raise ValueError(f"No parser registered for kind: {kind}")

    def parse_file(self, file_path, engine_name="simple", engine=None, **kwargs):
        parsed = self.parse_result(
            file_path,
            engine_name=engine_name,
            engine=engine,
            **kwargs,
        )
        return self._build_document_from_result(parsed)

    def parse_pdf_document(self, file_path, engine_name="simple", engine=None, **kwargs):
        return self.parse_file(file_path, engine_name=engine_name, engine=engine, **kwargs)

    def parse_batch(self, inputs, engine_name="simple", engine=None, **kwargs):
        documents = []
        active_engine = engine or self._create_engine(engine_name, **kwargs)
        for file_path in self.expand_inputs(inputs):
            documents.append(
                self.parse_file(file_path, engine_name=engine_name, engine=active_engine, **kwargs)
            )
        return documents

    def _collect_pdf_document_result(self, file_path, engine_name="simple", engine=None, **kwargs):
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        active_engine = engine or self._create_engine(engine_name, **kwargs)
        if hasattr(active_engine, "process_document"):
            process_document = getattr(active_engine, "process_document")
            if not callable(process_document):
                raise TypeError(
                    f"{type(active_engine).__name__}.process_document exists but is not callable"
                )

            parsed = process_document(file_path, **kwargs)
            if not isinstance(parsed, ParsedDocumentResult):
                raise TypeError(
                    f"{type(active_engine).__name__}.process_document must return ParsedDocumentResult"
                )
            return parsed

        pages = []
        for page in active_engine.process(file_path, **kwargs):
            pages.append(self._to_parsed_page_result(page))

        return ParsedDocumentResult(
            source=str(file_path),
            filename=file_path.name,
            engine=engine_name,
            pages=pages,
            markdown_content="\n".join(page.markdown_content for page in pages),
            metadata={},
        )

    def create_engine(self, engine_name: str = "simple", **kwargs):
        """
        Build one engine instance callers can reuse across many files.

        Batch runs must share a single engine: a per-file MinerU engine would
        start and stop its own local mineru-api service, and concurrent workers
        would race for the same port.
        """
        return self._create_engine(engine_name, **kwargs)

    def _create_engine(self, engine_name: str, **kwargs):
        engine_class = ENGINE_MAP.get(engine_name)
        if engine_class is None:
            raise ValueError(f"Unknown engine: {engine_name}. Available: {list(ENGINE_MAP.keys())}")

        engine_config = settings.resolve_engine_config(engine_name, kwargs)
        return engine_class(**engine_config)

    def _to_parsed_page_result(self, page) -> ParsedPageResult:
        return ParsedPageResult(
            page_number=page.page_number,
            markdown_content=page.markdown_content,
            plain_text=getattr(page, "plain_text", ""),
            elements=list(getattr(page, "elements", [])),
            tables=list(getattr(page, "tables", [])),
            images=list(getattr(page, "images", [])),
            metadata=dict(getattr(page, "metadata", {})),
        )

    def _build_document_from_result(self, parsed: ParsedDocumentResult) -> Document:
        return document_from_result(parsed)

    def _flatten_inputs(self, inputs) -> Iterator[Union[str, Path]]:
        if isinstance(inputs, (str, Path)):
            yield inputs
            return

        if isinstance(inputs, Iterable):
            for item in inputs:
                if isinstance(item, (str, Path)):
                    yield item
                elif isinstance(item, Iterable):
                    yield from self._flatten_inputs(item)
                else:
                    yield item
            return

        yield inputs

    def _output_filename(self, source, fmt: str) -> str:
        return output_filename(source, fmt)

    def _output_path_for_batch_item(self, source, fmt: str, used_paths: set[Path]) -> Path:
        return resolve_output_path(source, fmt, used_paths)

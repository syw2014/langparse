from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import asdict
from pathlib import Path

from langparse.chunkers.profiles import (
    ChunkProfileNotSupportedError,
    resolve_workbook_chunk_policy,
)
from langparse.config import settings
from langparse.core.rendering import document_from_result
from langparse.engines.pdf.deepdoc_engine import DeepDocEngine
from langparse.engines.pdf.mineru import MinerUEngine
from langparse.engines.pdf.other import PaddleOCRVLEngine
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
from langparse.types import (
    Chunk,
    Document,
    ParsedDocumentResult,
    ParseDiagnostics,
    ParsedPageResult,
)
from langparse.workbooks.modeling import WorkbookDisambiguation
from langparse.workbooks.types import WorkbookIR

#: Engines a caller can actually select. Advertising an engine that raises
#: NotImplementedError only once it runs wastes the user's configuration effort
#: and, for MinerU-scale setups, their model downloads.
ENGINE_MAP = {
    "simple": SimplePDFEngine,
    "mineru": MinerUEngine,
    "deepdoc": DeepDocEngine,
}

#: Reserved names with adapters in the tree but no working implementation.
#: Selecting one fails immediately with an explanation instead of at parse time.
PLANNED_ENGINES = {
    "vision_llm": VisionLLMEngine,
    "paddle": PaddleOCRVLEngine,
}


class ParseService:
    def chunk_result(
        self,
        parsed: ParsedDocumentResult,
        chunker=None,
        *,
        chunk_profile: str | None = None,
    ) -> list[Chunk]:
        """Chunk a parse result from its richest available representation."""
        if chunker is not None and chunk_profile is not None:
            raise ValueError("custom chunker and chunk_profile are mutually exclusive")

        if chunker is not None:
            if parsed.structure is not None and parsed.structure.kind == "workbook":
                return chunker.chunk(parsed)
            return chunker.chunk(document_from_result(parsed))

        policy = resolve_workbook_chunk_policy(chunk_profile)
        if isinstance(parsed.structure, WorkbookIR):
            from langparse.chunkers.workbook import WorkbookStructuralChunker

            return WorkbookStructuralChunker(profile=policy.name).chunk(parsed)

        if policy.name.value == "analysis":
            raise ChunkProfileNotSupportedError("analysis chunk profile requires WorkbookIR")

        from langparse.chunkers.semantic import SemanticChunker

        chunks = SemanticChunker().chunk(document_from_result(parsed))
        for chunk in chunks:
            chunk.metadata["chunk_profile"] = policy.name.value
            chunk.metadata["chunk_profile_version"] = policy.version
        return chunks

    def render_output(
        self,
        parsed: ParsedDocumentResult,
        fmt: str,
        chunks: list[Chunk] | None = None,
    ) -> str:
        if fmt == "markdown":
            if chunks is None:
                return parsed.markdown_content
            if not chunks:
                return parsed.markdown_content
            return "\n\n---\n\n".join(chunk.content for chunk in chunks)
        if fmt == "json":
            payload = asdict(parsed)
            if chunks is not None:
                payload["chunks"] = [asdict(chunk) for chunk in chunks]
            return json.dumps(payload, ensure_ascii=False, indent=2, default=_json_scalar)
        raise ValueError(f"Unsupported output format: {fmt}")

    def parse_output(
        self,
        file_path,
        engine_name="simple",
        fmt="markdown",
        engine=None,
        chunk=False,
        chunk_profile: str | None = None,
        workbook_disambiguation: WorkbookDisambiguation | None = None,
        **kwargs,
    ) -> str:
        parsed = self.parse_result(
            file_path,
            engine_name=engine_name,
            engine=engine,
            chunk=chunk,
            chunk_profile=chunk_profile,
            workbook_disambiguation=workbook_disambiguation,
            **kwargs,
        )
        return self.render_output(parsed, fmt, chunks=parsed.chunks if chunk else None)

    def parse_batch_outputs(
        self,
        inputs,
        engine_name="simple",
        fmt="markdown",
        engine=None,
        chunk=False,
        chunk_profile: str | None = None,
        workbook_disambiguation: WorkbookDisambiguation | None = None,
        **kwargs,
    ) -> list[tuple[Path, str]]:
        # `chunk` is named explicitly rather than left in **kwargs: kwargs also
        # feed engine construction, and MinerU folds unknown kwargs into
        # extra_options and sends them to its API as form fields.
        model = kwargs.pop("model", None)
        api_key = kwargs.pop("api_key", None)
        base_url = kwargs.pop("base_url", None)
        kwargs.pop("disambiguation", None)
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
                        chunk=chunk,
                        chunk_profile=chunk_profile,
                        workbook_disambiguation=workbook_disambiguation,
                        model=model,
                        api_key=api_key,
                        base_url=base_url,
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
        for (_, content), relative in zip(outputs, relative_paths, strict=True):
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
                        child for child in path.iterdir() if child.is_file() and is_supported(child)
                    )
                )
            else:
                paths.append(path)
        return paths

    def parse_result(
        self,
        file_path,
        engine_name="simple",
        engine=None,
        chunk=False,
        chunk_profile: str | None = None,
        workbook_disambiguation: str | WorkbookDisambiguation | None = None,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        **kwargs,
    ):
        """
        Parse any supported format into a ParsedDocumentResult.

        This is the one place extension routing happens; everything else reads
        the mapping from `langparse.parsers.registry`.
        """
        if chunk:
            resolve_workbook_chunk_policy(chunk_profile)

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        kind = parser_kind_for(path)
        if kind is None:
            raise unsupported_extension_error(path)
        if kind == "pdf":
            parsed = self._collect_pdf_document_result(
                path,
                engine_name=engine_name,
                engine=engine,
                **kwargs,
            )
        else:
            parsed = self._parser_for_kind(
                kind,
                workbook_disambiguation,
                model=model,
                api_key=api_key,
                base_url=base_url,
            ).parse_result(path, **kwargs)
        if chunk:
            self._populate_chunks(parsed, chunk_profile)
        return parsed

    def _populate_chunks(
        self,
        parsed: ParsedDocumentResult,
        chunk_profile: str | None,
    ) -> None:
        policy = resolve_workbook_chunk_policy(chunk_profile)
        try:
            parsed.chunks = self.chunk_result(parsed, chunk_profile=policy.name.value)
        except ChunkProfileNotSupportedError:
            if parsed.diagnostics is None:
                parsed.diagnostics = ParseDiagnostics()
            if parsed.diagnostics.status != "failed":
                parsed.diagnostics.status = "partial"
            parsed.diagnostics.unsupported_features.append(
                f"Chunking profile '{policy.name.value}' is not supported for engine "
                f"'{parsed.engine}'."
            )
            parsed.chunks = []
        except Exception as exc:  # noqa: BLE001 - preserve parsed result at chunk boundary
            if parsed.diagnostics is None:
                parsed.diagnostics = ParseDiagnostics()
            if parsed.diagnostics.status != "failed":
                parsed.diagnostics.status = "partial"
            parsed.diagnostics.errors.append(
                f"Chunking profile '{policy.name.value}' failed ({type(exc).__name__})."
            )
            parsed.chunks = []

    def _parser_for_kind(
        self,
        kind: str,
        workbook_disambiguation: str | WorkbookDisambiguation | None = None,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        if kind == "docx":
            from langparse.parsers.docx_parser import DocxParser

            return DocxParser()
        if kind == "excel":
            from langparse.parsers.excel_parser import ExcelParser

            return ExcelParser(
                disambiguation=workbook_disambiguation,
                model=model,
                api_key=api_key,
                base_url=base_url,
            )
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
        workbook_disambiguation = kwargs.pop("workbook_disambiguation", None)
        model = kwargs.pop("model", None)
        api_key = kwargs.pop("api_key", None)
        base_url = kwargs.pop("base_url", None)
        documents = []
        active_engine = engine or self._create_engine(engine_name, **kwargs)
        for file_path in self.expand_inputs(inputs):
            documents.append(
                self.parse_file(
                    file_path,
                    engine_name=engine_name,
                    engine=active_engine,
                    workbook_disambiguation=workbook_disambiguation,
                    model=model,
                    api_key=api_key,
                    base_url=base_url,
                    **kwargs,
                )
            )
        return documents

    def _collect_pdf_document_result(self, file_path, engine_name="simple", engine=None, **kwargs):
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        engine_kwargs = {
            k: v
            for k, v in kwargs.items()
            if k
            not in (
                "model",
                "api_key",
                "base_url",
                "workbook_disambiguation",
                "disambiguation",
            )
        }
        active_engine = engine or self._create_engine(engine_name, **engine_kwargs)
        if hasattr(active_engine, "process_document"):
            process_document = active_engine.process_document
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
            metadata=self._document_metadata_from_pages(pages),
        )

    def _document_metadata_from_pages(self, pages: list[ParsedPageResult]) -> dict:
        """Roll per-page engine signals up to the document, where metrics read them."""
        return {
            "ocr_applied": any(page.metadata.get("ocr_applied") for page in pages),
            "ocr_text_chars": sum(
                int(page.metadata.get("ocr_text_chars", 0) or 0) for page in pages
            ),
        }

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
            available = ", ".join(sorted(ENGINE_MAP))
            if engine_name in PLANNED_ENGINES:
                raise ValueError(
                    f"Engine '{engine_name}' is not implemented yet. Available: {available}"
                )
            raise ValueError(f"Unknown engine: {engine_name}. Available: {available}")

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

    def _flatten_inputs(self, inputs) -> Iterator[str | Path]:
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


def _json_scalar(value):
    """Serialize native spreadsheet scalars such as dates and decimals."""

    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)

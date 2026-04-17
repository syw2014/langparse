from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path
from typing import Iterator, Union

from langparse.config import settings
from langparse.engines.pdf.mineru import MinerUEngine
from langparse.engines.pdf.other import DeepDocEngine, PaddleOCRVLEngine
from langparse.engines.pdf.simple import SimplePDFEngine
from langparse.engines.pdf.vision_llm import VisionLLMEngine
from langparse.types import Document, ParsedDocumentResult, ParsedPageResult

ENGINE_MAP = {
    "simple": SimplePDFEngine,
    "mineru": MinerUEngine,
    "vision_llm": VisionLLMEngine,
    "deepdoc": DeepDocEngine,
    "paddle": PaddleOCRVLEngine,
}


class ParseService:
    def render_output(self, parsed: ParsedDocumentResult, fmt: str) -> str:
        if fmt == "markdown":
            return parsed.markdown_content
        if fmt == "json":
            return json.dumps(asdict(parsed), ensure_ascii=False, indent=2)
        raise ValueError(f"Unsupported output format: {fmt}")

    def parse_output(self, file_path, engine_name="simple", fmt="markdown", engine=None, **kwargs) -> str:
        parsed = self._collect_pdf_document_result(
            file_path,
            engine_name=engine_name,
            engine=engine,
            **kwargs,
        )
        return self.render_output(parsed, fmt)

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

        written_paths = []
        used_relative_paths = set()
        for source_path, content in outputs:
            destination = output_dir / self._output_path_for_batch_item(
                source_path,
                fmt,
                used_relative_paths,
            )
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
                        if child.is_file() and child.suffix.lower() == ".pdf"
                    )
                )
            else:
                paths.append(path)
        return paths

    def parse_file(self, file_path, engine_name="simple", engine=None, **kwargs):
        parsed = self._collect_pdf_document_result(
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
        full_content = []
        for page in parsed.pages:
            full_content.append(f"\n<!-- page_number: {page.page_number} -->\n")
            full_content.append(page.markdown_content)

        return Document(
            content="\n".join(full_content),
            metadata={
                "source": parsed.source,
                "filename": parsed.filename,
                "engine": parsed.engine,
                "parsed_metadata": parsed.metadata,
            },
        )

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
        suffix = ".md" if fmt == "markdown" else ".json"
        return f"{Path(source).stem}{suffix}"

    def _output_path_for_batch_item(self, source, fmt: str, used_paths: set[Path]) -> Path:
        source_path = Path(source)
        filename = self._output_filename(source_path, fmt)
        parent_parts = [part for part in source_path.parent.parts if part not in {"", ".", source_path.anchor}]

        candidates = []
        if source_path.is_absolute():
            candidates.append(Path(filename))
            for width in range(1, len(parent_parts) + 1):
                candidates.append(Path(*parent_parts[-width:]) / filename)
        else:
            if parent_parts:
                candidates.append(Path(*parent_parts) / filename)
            for width in range(1, len(parent_parts)):
                candidates.append(Path(*parent_parts[-width:]) / filename)
            candidates.append(Path(filename))

        for candidate in candidates:
            if candidate not in used_paths:
                used_paths.add(candidate)
                return candidate

        stem = Path(filename).stem
        suffix = Path(filename).suffix
        counter = 1
        while True:
            candidate = Path(f"{stem}-{counter}{suffix}")
            if candidate not in used_paths:
                used_paths.add(candidate)
                return candidate
            counter += 1

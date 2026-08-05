import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from langparse.core.engine import PageResult
from langparse.engines.pdf.simple import BasePDFEngine
from langparse.types import ParsedDocumentResult


class DeepDocEngine(BasePDFEngine):
    """
    Adapter for the ported DeepDoc (RAGFlow) OCR + layout + table-structure
    pipeline. CPU-only ONNX inference, no separate runtime service --
    unlike MinerU, it runs in-process (see langparse/engines/pdf/deepdoc/).
    """

    def __init__(
        self,
        device: str = "cpu",
        model_dir: str | None = None,
        download_dir: str | None = None,
        model_policy: str = "download_if_missing",
        parser: Any = None,
        **kwargs: Any,
    ):
        if device != "cpu":
            raise ValueError(
                f"DeepDocEngine only supports device='cpu' in this version, got: {device!r}"
            )
        self.device = device
        self.model_dir = model_dir
        self.download_dir = download_dir
        self.model_policy = model_policy
        self._parser = parser
        # Batch runs share one engine (and thus one RAGFlowPdfParser) across
        # worker threads. RAGFlowPdfParser is deeply per-parse stateful --
        # __images__ resets self.boxes/self.page_images/etc. at the top of
        # every call, and the downstream chain mutates self.boxes in place --
        # so two threads parsing concurrently would corrupt each other's
        # state. The lock also prevents two threads from racing to build (and
        # load ~100MB of models for) separate parsers. Same precedent as
        # SimplePDFEngine._ocr_lock: correctness over throughput on an
        # already-slow path.
        self._parser_lock = threading.Lock()

    def _build_parser(self):
        try:
            from langparse.engines.pdf.deepdoc.model_loader import ensure_deepdoc_models
            from langparse.engines.pdf.deepdoc.pdf_parser import RAGFlowPdfParser
        except ImportError as exc:
            raise ImportError(
                'DeepDoc engine needs extra dependencies. Install them with `pip install "langparse[deepdoc]"`.'
            ) from exc

        resolved_model_dir = ensure_deepdoc_models(
            model_dir=self.model_dir,
            download_dir=self.download_dir,
            model_policy=self.model_policy,
        )
        return RAGFlowPdfParser(model_dir=resolved_model_dir)

    def process_document(self, file_path: Path, **kwargs: Any) -> ParsedDocumentResult:
        try:
            from langparse.engines.pdf.deepdoc.rendering import render_pages
        except ImportError as exc:
            raise ImportError(
                'DeepDoc engine needs extra dependencies. Install them with `pip install "langparse[deepdoc]"`.'
            ) from exc

        with self._parser_lock:
            if self._parser is None:
                self._parser = self._build_parser()
            boxes = self._parser.parse_into_bboxes(str(file_path))

        pages = render_pages(boxes)
        return ParsedDocumentResult(
            source=str(file_path),
            filename=Path(file_path).name,
            engine="deepdoc",
            pages=pages,
            markdown_content="\n\n".join(page.markdown_content for page in pages),
            metadata={"device": self.device, "model_dir": self.model_dir},
        )

    def process(self, file_path: Path, **kwargs) -> Iterator[PageResult]:
        parsed = self.process_document(file_path, **kwargs)
        for page in parsed.pages:
            yield PageResult(
                page_number=page.page_number,
                markdown_content=page.markdown_content,
                plain_text=page.plain_text,
                elements=page.elements,
                tables=page.tables,
                images=page.images,
                metadata=page.metadata,
            )

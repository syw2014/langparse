import threading
from collections.abc import Iterator
from pathlib import Path

from langparse.core.engine import BaseEngine, PageResult
from langparse.engines.pdf.ocr import (
    DEFAULT_MIN_CHARS,
    DEFAULT_RESOLUTION,
    load_recogniser,
    needs_ocr,
    ocr_page_text,
)


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

    Scanned pages fall back to OCR. Without it a scanned document parses
    "successfully" into a handful of watermark characters, which is harder for a
    caller to notice than an outright failure.
    """

    def __init__(
        self,
        enable_ocr: bool = True,
        ocr_min_chars: int = DEFAULT_MIN_CHARS,
        ocr_resolution: int = DEFAULT_RESOLUTION,
        recogniser=None,
        **kwargs,
    ):
        self.enable_ocr = enable_ocr
        self.ocr_min_chars = ocr_min_chars
        self.ocr_resolution = ocr_resolution
        self._recogniser = recogniser
        # Batch runs share one engine across worker threads. The lock keeps
        # model loading (tens of seconds) from happening once per thread, and
        # serialises recognition because rapidocr states no thread-safety
        # guarantee -- correctness over throughput on an already slow path.
        self._ocr_lock = threading.Lock()

    def process(self, file_path: Path, **kwargs) -> Iterator[PageResult]:
        try:
            import pdfplumber
        except ImportError:
            raise ImportError("Please install `pdfplumber` to use the 'simple' engine.") from None

        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                ocr_applied = False

                if self.enable_ocr and needs_ocr(page, min_chars=self.ocr_min_chars):
                    recovered = self._run_ocr(page)
                    if recovered:
                        text = recovered
                        ocr_applied = True

                tables, table_markdown = self._extract_tables(page)

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
                    metadata={
                        "engine_name": "simple",
                        "ocr_applied": ocr_applied,
                        "ocr_text_chars": len(text) if ocr_applied else 0,
                    },
                )

    def _run_ocr(self, page) -> str:
        """Recognise a page, degrading to no text rather than failing the parse."""
        try:
            with self._ocr_lock:
                recogniser = self._build_recogniser_if_needed()
                return ocr_page_text(page, recogniser, resolution=self.ocr_resolution)
        except ImportError:
            # rapidocr absent: the page keeps whatever thin text layer it had.
            return ""

    def _resolve_recogniser(self):
        with self._ocr_lock:
            return self._build_recogniser_if_needed()

    def _build_recogniser_if_needed(self):
        """Caller must hold `_ocr_lock`."""
        if self._recogniser is None:
            self._recogniser = load_recogniser()
        return self._recogniser

    def _extract_tables(self, page):
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
        return tables, table_markdown

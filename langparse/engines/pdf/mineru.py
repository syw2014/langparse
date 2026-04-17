from pathlib import Path
from typing import Any, Iterator

from langparse.core.engine import PageResult
from langparse.engines.pdf.simple import BasePDFEngine
from langparse.types import ParsedDocumentResult, ParsedPageResult


class MinerUEngine(BasePDFEngine):
    """
    Adapter for MinerU (Magic-PDF).
    High precision parsing for complex documents (papers, textbooks).
    """

    def __init__(
        self,
        device: str = "auto",
        model_dir: str | None = None,
        download_dir: str | None = None,
        enable_ocr: bool = True,
        extra_options: dict[str, Any] | None = None,
        **kwargs: Any,
    ):
        self.device = device
        self.model_dir = model_dir
        self.download_dir = download_dir
        self.enable_ocr = enable_ocr
        self.extra_options = {**(extra_options or {}), **kwargs}

    def _cuda_available(self) -> bool:
        try:
            import torch
        except ImportError:
            return False

        return bool(torch.cuda.is_available())

    def _resolve_device(self, device: str | None = None) -> str:
        requested_device = self.device if device is None else device

        if requested_device == "auto":
            return "cuda" if self._cuda_available() else "cpu"

        if requested_device == "cuda" and not self._cuda_available():
            raise RuntimeError("CUDA was requested for MinerU but is not available.")

        return requested_device

    def _ensure_runtime(self) -> None:
        try:
            import magic_pdf  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "MinerU runtime is unavailable. Install the `magic-pdf` package to use the MinerU engine."
            ) from exc

    def _build_runtime_config(self, **kwargs: Any) -> dict[str, Any]:
        requested_device = kwargs.get("device", self.device)
        return {
            "device": self._resolve_device(requested_device),
            "model_dir": kwargs.get("model_dir", self.model_dir),
            "download_dir": kwargs.get("download_dir", self.download_dir),
            "enable_ocr": kwargs.get("enable_ocr", self.enable_ocr),
            "extra_options": {**self.extra_options, **kwargs.get("extra_options", {})},
        }

    def _run_mineru(self, file_path: Path, runtime_config: dict[str, Any]) -> list[dict[str, Any]]:
        raise NotImplementedError(
            "MinerU runtime wiring is not implemented yet. Override `_run_mineru()` "
            "or provide a concrete magic-pdf integration."
        )

    def process_document(self, file_path: Path, **kwargs: Any) -> ParsedDocumentResult:
        self._ensure_runtime()
        runtime_config = self._build_runtime_config(**kwargs)
        raw_pages = self._run_mineru(file_path, runtime_config)
        pages = [
            ParsedPageResult(
                page_number=item["page_number"],
                markdown_content=item.get("markdown", ""),
                plain_text=item.get("plain_text", ""),
                elements=item.get("elements", []),
                tables=item.get("tables", []),
                images=item.get("images", []),
                metadata={
                    "engine_name": "mineru",
                    "device": runtime_config["device"],
                    "engine_specific": item.get("engine_specific", {}),
                },
            )
            for item in raw_pages
        ]
        return ParsedDocumentResult(
            source=str(file_path),
            filename=file_path.name,
            engine="mineru",
            pages=pages,
            markdown_content="\n".join(page.markdown_content for page in pages),
            metadata={
                "device": runtime_config["device"],
                "model_dir": runtime_config["model_dir"],
                "download_dir": runtime_config["download_dir"],
                "enable_ocr": runtime_config["enable_ocr"],
            },
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

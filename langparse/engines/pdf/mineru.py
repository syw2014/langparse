from pathlib import Path
from typing import Any, Iterator

from langparse.core.engine import PageResult
from langparse.engines.pdf.mineru_client import MinerUClient
from langparse.engines.pdf.mineru_service import MinerUServiceManager
from langparse.engines.pdf.simple import BasePDFEngine
from langparse.types import ParsedDocumentResult, ParsedElement, ParsedPageResult


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
        api_url: str | None = None,
        api_host: str = "127.0.0.1",
        api_port: int = 8000,
        api_command: str = "mineru-api",
        api_start_timeout: float = 30.0,
        request_timeout: float = 300.0,
        extra_options: dict[str, Any] | None = None,
        **kwargs: Any,
    ):
        self.device = device
        self.model_dir = model_dir
        self.download_dir = download_dir
        self.enable_ocr = enable_ocr
        self.api_url = api_url
        self.api_host = api_host
        self.api_port = api_port
        self.api_command = api_command
        self.api_start_timeout = api_start_timeout
        self.request_timeout = request_timeout
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
        # The real runtime path is mineru-api. Dependency validation happens when
        # starting or connecting to that service.
        return None

    def _build_runtime_config(self, **kwargs: Any) -> dict[str, Any]:
        requested_device = kwargs.get("device", self.device)
        return {
            "device": self._resolve_device(requested_device),
            "model_dir": kwargs.get("model_dir", self.model_dir),
            "download_dir": kwargs.get("download_dir", self.download_dir),
            "enable_ocr": kwargs.get("enable_ocr", self.enable_ocr),
            "extra_options": {**self.extra_options, **kwargs.get("extra_options", {})},
        }

    def _build_service_config(self) -> dict[str, Any]:
        return {
            "api_url": self.api_url,
            "host": self.api_host,
            "port": self.api_port,
            "command": self.api_command,
            "start_timeout": self.api_start_timeout,
            "request_timeout": self.request_timeout,
        }

    def _create_client(self, base_url: str) -> MinerUClient:
        return MinerUClient(base_url, timeout=self.request_timeout)

    def _create_service_manager(self) -> MinerUServiceManager:
        return MinerUServiceManager(**self._build_service_config())

    def _run_mineru(self, file_path: Path, runtime_config: dict[str, Any]) -> list[dict[str, Any]]:
        manager = self._create_service_manager()
        with manager.running_service() as base_url:
            client = self._create_client(base_url)
            return client.parse_file(file_path, runtime_config)

    def process_document(self, file_path: Path, **kwargs: Any) -> ParsedDocumentResult:
        self._ensure_runtime()
        runtime_config = self._build_runtime_config(**kwargs)
        raw_pages = self._run_mineru(file_path, runtime_config)
        pages = [
            ParsedPageResult(
                page_number=item["page_number"],
                markdown_content=item.get("markdown", ""),
                plain_text=item.get("plain_text", ""),
                elements=[
                    element
                    if isinstance(element, ParsedElement)
                    else ParsedElement(
                        kind=element.get("kind", "text"),
                        text=element.get("text", ""),
                        bbox=element.get("bbox"),
                        metadata=element.get("metadata", {}),
                    )
                    for element in item.get("elements", [])
                ],
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

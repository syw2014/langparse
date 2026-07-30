from collections.abc import Iterator
from pathlib import Path

from langparse.core.engine import PageResult
from langparse.engines.pdf.simple import BasePDFEngine
from langparse.logging import get_logger

logger = get_logger(__name__)


class VisionLLMEngine(BasePDFEngine):
    """
    Uses Vision LLMs (GPT-4o, Gemini 1.5 Pro) to parse pages.
    Extremely slow/expensive but handles EVERYTHING (handwriting, complex charts).
    """

    def __init__(self, model_name: str = "gpt-4o", api_key: str = None):
        self.model_name = model_name
        self.api_key = api_key

    def process(self, file_path: Path, **kwargs) -> Iterator[PageResult]:
        # 1. Convert PDF to Images (using pdf2image)
        # 2. Send each image to LLM with a prompt like "Transcribe this page to Markdown"

        logger.debug("VisionLLM processing %s with %s", file_path, self.model_name)

        raise NotImplementedError("Vision LLM integration is pending.")

from collections.abc import Iterator
from pathlib import Path

from langparse.core.engine import PageResult
from langparse.engines.pdf.simple import BasePDFEngine
from langparse.logging import get_logger

logger = get_logger(__name__)


class PaddleOCRVLEngine(BasePDFEngine):
    """
    Adapter for PaddleOCR + Layout Analysis or PP-Structure.
    Can be local or via API.
    """

    def process(self, file_path: Path, **kwargs) -> Iterator[PageResult]:
        logger.debug("PaddleOCR processing %s", file_path)
        # TODO: Integrate PaddleOCR / PP-Structure logic
        raise NotImplementedError("PaddleOCR integration is pending.")

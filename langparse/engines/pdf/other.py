from langparse.core.engine import PageResult
from langparse.engines.pdf.simple import BasePDFEngine
from pathlib import Path
from typing import Iterator

class DeepDocEngine(BasePDFEngine):
    """
    Adapter for DeepDoc (e.g., from RAGFlow or similar deep learning based parsers).
    """
    
    def process(self, file_path: Path, **kwargs) -> Iterator[PageResult]:
        print(f"[DeepDoc] Processing {file_path}...")
        # TODO: Integrate DeepDoc inference logic
        raise NotImplementedError("DeepDoc integration is pending.")

class PaddleOCRVLEngine(BasePDFEngine):
    """
    Adapter for PaddleOCR + Layout Analysis or PP-Structure.
    Can be local or via API.
    """
    
    def process(self, file_path: Path, **kwargs) -> Iterator[PageResult]:
        print(f"[PaddleOCR] Processing {file_path}...")
        # TODO: Integrate PaddleOCR / PP-Structure logic
        raise NotImplementedError("PaddleOCR integration is pending.")

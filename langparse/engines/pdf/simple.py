from langparse.core.engine import BaseEngine, PageResult
from pathlib import Path
from typing import Iterator

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
    """
    
    def process(self, file_path: Path, **kwargs) -> Iterator[PageResult]:
        try:
            import pdfplumber
        except ImportError:
            raise ImportError("Please install `pdfplumber` to use the 'simple' engine.")
            
        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                # Basic text extraction
                text = page.extract_text() or ""
                
                # TODO: Add basic table extraction logic here if needed
                
                yield PageResult(
                    page_number=i + 1,
                    markdown_content=text
                )

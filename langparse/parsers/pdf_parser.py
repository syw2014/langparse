from typing import Union, Literal
from pathlib import Path
from langparse.core.parser import BaseParser
from langparse.types import Document
from langparse.engines.pdf.simple import SimplePDFEngine
from langparse.engines.pdf.mineru import MinerUEngine
from langparse.engines.pdf.vision_llm import VisionLLMEngine
from langparse.engines.pdf.other import DeepDocEngine, PaddleOCRVLEngine

# Registry of available engines
ENGINE_MAP = {
    "simple": SimplePDFEngine,
    "mineru": MinerUEngine,
    "vision_llm": VisionLLMEngine,
    "deepdoc": DeepDocEngine,
    "paddle": PaddleOCRVLEngine,
}

from langparse.config import settings

class PDFParser(BaseParser):
    """
    A universal PDF parser that delegates to specific engines.
    """
    
    def __init__(self, engine: Literal["simple", "mineru", "vision_llm", "deepdoc", "paddle"] = None, **engine_kwargs):
        # 1. Resolve engine name: Argument > Config > Default
        self.engine_name = engine or settings.get("default_pdf_engine", "simple")
        
        engine_class = ENGINE_MAP.get(self.engine_name)
        if not engine_class:
            raise ValueError(f"Unknown engine: {self.engine_name}. Available: {list(ENGINE_MAP.keys())}")
        
        # 2. Merge engine-specific config
        # e.g. Get 'engines.vision_llm' config and merge with runtime kwargs
        config_key = f"engines.{self.engine_name}"
        engine_config = settings.get(config_key, {})
        
        # Runtime kwargs override config
        final_kwargs = {**engine_config, **engine_kwargs}
        
        self.engine = engine_class(**final_kwargs)
        
    def parse(self, file_path: Union[str, Path], **kwargs) -> Document:
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
            
        full_content = []
        
        # Iterate through pages yielded by the engine
        for page_result in self.engine.process(file_path):
            # Standardize Output: Inject Page Markers
            full_content.append(f"\n<!-- page_number: {page_result.page_number} -->\n")
            full_content.append(page_result.markdown_content)
            
        combined_markdown = "\n".join(full_content)
        
        return Document(
            content=combined_markdown,
            metadata={
                "source": str(file_path),
                "filename": file_path.name,
                "engine": self.engine_name
            }
        )

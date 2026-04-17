from typing import Literal, Union
from pathlib import Path
from langparse.core.parser import BaseParser
from langparse.services.parse_service import ENGINE_MAP, ParseService
from langparse.types import Document

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

        engine_config = settings.resolve_engine_config(self.engine_name, engine_kwargs)
        self.engine = engine_class(**engine_config)
        
    def parse(self, file_path: Union[str, Path], **kwargs) -> Document:
        service = ParseService()
        return service.parse_pdf_document(
            file_path,
            engine_name=self.engine_name,
            engine=self.engine,
            **kwargs,
        )

from pathlib import Path
from typing import Union
from langparse.core.parser import BaseParser
from langparse.types import Document

class MarkdownParser(BaseParser):
    """
    A simple parser for Markdown files.
    """
    
    def parse(self, file_path: Union[str, Path], **kwargs) -> Document:
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
            
        content = file_path.read_text(encoding='utf-8')
        
        return Document(
            content=content,
            metadata={
                "source": str(file_path),
                "filename": file_path.name,
                "extension": file_path.suffix
            }
        )

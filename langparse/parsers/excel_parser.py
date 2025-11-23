from typing import Union
from pathlib import Path
from langparse.core.parser import BaseParser
from langparse.types import Document

class ExcelParser(BaseParser):
    """
    Parses .xlsx/.csv files to Markdown Tables.
    Each Sheet is treated as a separate 'Page'.
    """
    
    def parse(self, file_path: Union[str, Path], **kwargs) -> Document:
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
            
        try:
            import pandas as pd
        except ImportError:
            raise ImportError("pandas and openpyxl are required. Install with `pip install pandas openpyxl`.")
            
        markdown_parts = []
        
        if file_path.suffix == '.csv':
            df = pd.read_csv(file_path)
            markdown_parts.append("<!-- page_number: 1 -->\n")
            markdown_parts.append(df.to_markdown(index=False))
        else:
            # Excel with multiple sheets
            sheets = pd.read_excel(file_path, sheet_name=None)
            for i, (sheet_name, df) in enumerate(sheets.items()):
                page_num = i + 1
                markdown_parts.append(f"\n<!-- page_number: {page_num} -->")
                markdown_parts.append(f"### Sheet: {sheet_name}\n")
                markdown_parts.append(df.to_markdown(index=False))
                markdown_parts.append("\n")
                
        return Document(
            content="\n".join(markdown_parts),
            metadata={
                "source": str(file_path),
                "filename": file_path.name,
                "extension": file_path.suffix
            }
        )

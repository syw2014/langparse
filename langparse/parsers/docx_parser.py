from typing import Union, Any, Dict
from pathlib import Path
from langparse.core.parser import BaseParser
from langparse.types import Document

class DocxParser(BaseParser):
    """
    Parses .docx files to Markdown.
    Note: DOCX is a flow format, so 'page numbers' are not strictly defined.
    We treat the entire document as Page 1 for now, unless we convert to PDF first.
    """
    
    def parse(self, file_path: Union[str, Path], **kwargs) -> Document:
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
            
        try:
            import docx
        except ImportError:
            raise ImportError("python-docx is required. Install with `pip install python-docx`.")
            
        doc = docx.Document(file_path)
        markdown_lines = []
        
        # Inject Page 1 marker
        markdown_lines.append("<!-- page_number: 1 -->\n")
        
        # Iterate through all block-level elements (paragraphs and tables) in document order
        # python-docx doesn't provide a direct way to iterate mixed content easily, 
        # so we iterate through document.element.body
        
        from docx.oxml.text.paragraph import CT_P
        from docx.oxml.table import CT_Tbl
        
        def iter_block_items(parent):
            if isinstance(parent, docx.document.Document):
                parent_elm = parent.element.body
            else:
                parent_elm = parent._element
                
            for child in parent_elm.iterchildren():
                if isinstance(child, CT_P):
                    yield docx.text.paragraph.Paragraph(child, parent)
                elif isinstance(child, CT_Tbl):
                    yield docx.table.Table(child, parent)
        
        for block in iter_block_items(doc):
            if isinstance(block, docx.text.paragraph.Paragraph):
                text = block.text.strip()
                if not text:
                    continue
                    
                style_name = block.style.name.lower()
                if 'heading 1' in style_name or 'title' in style_name:
                    markdown_lines.append(f"# {text}")
                elif 'heading 2' in style_name:
                    markdown_lines.append(f"## {text}")
                elif 'heading 3' in style_name:
                    markdown_lines.append(f"### {text}")
                elif 'list' in style_name:
                    markdown_lines.append(f"- {text}")
                else:
                    markdown_lines.append(text)
                markdown_lines.append("") # Add spacing
                
            elif isinstance(block, docx.table.Table):
                # Convert table to Markdown
                # 1. Get headers
                rows = block.rows
                if not rows:
                    continue
                    
                # Simple table extraction
                table_data = []
                for row in rows:
                    row_cells = [cell.text.strip().replace('\n', ' ') for cell in row.cells]
                    table_data.append(row_cells)
                
                if not table_data:
                    continue
                    
                # Construct Markdown Table
                headers = table_data[0]
                markdown_lines.append(f"| {' | '.join(headers)} |")
                markdown_lines.append(f"| {' | '.join(['---'] * len(headers))} |")
                
                for row in table_data[1:]:
                    markdown_lines.append(f"| {' | '.join(row)} |")
                
                markdown_lines.append("") # Add spacing
        
        return Document(
            content="\n".join(markdown_lines),
            metadata={
                "source": str(file_path),
                "filename": file_path.name,
                "extension": ".docx"
            }
        )

import re
from typing import List, Dict, Any, Tuple
from langparse.core.chunker import BaseChunker
from langparse.types import Document, Chunk

class SemanticChunker(BaseChunker):
    """
    Chunks text based on Markdown headers to preserve semantic structure.
    """
    
    def __init__(self, max_chunk_size: int = 1000, min_chunk_size: int = 100):
        self.max_chunk_size = max_chunk_size
        self.min_chunk_size = min_chunk_size

    def chunk(self, document: Document, **kwargs) -> List[Chunk]:
        content = document.content
        chunks = []
        
        # 1. Pre-scan for page markers to build a map of {char_index: page_number}
        # Marker format: <!-- page_number: 1 -->
        page_marker_regex = re.compile(r'<!--\s*page_number:\s*(\d+)\s*-->')
        page_markers = []
        for match in page_marker_regex.finditer(content):
            page_markers.append((match.start(), int(match.group(1))))
            
        def get_pages_for_range(start: int, end: int, current_page_context: int) -> List[int]:
            """
            Finds all page numbers that appear within the text range [start, end].
            If no markers are found, returns the current page context.
            """
            pages = set()
            # Check if the range starts on a known page (from previous context)
            pages.add(current_page_context)
            
            for marker_idx, page_num in page_markers:
                if start <= marker_idx < end:
                    pages.add(page_num)
            
            return sorted(list(pages))

        def get_last_page_before(idx: int) -> int:
            """Find the last page number seen before a given index."""
            last_page = 1 # Default to page 1
            for marker_idx, page_num in page_markers:
                if marker_idx < idx:
                    last_page = page_num
                else:
                    break
            return last_page

        # 2. Identify Headers
        header_regex = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
        matches = list(header_regex.finditer(content))
        
        if not matches:
            # No headers found, treat as one big chunk
            # Determine pages
            pages = get_pages_for_range(0, len(content), 1)
            clean_content = page_marker_regex.sub('', content).strip()
            
            meta = document.metadata.copy()
            meta.update({
                "page_numbers": pages,
                "header": None,
                "header_level": 0,
                "header_path": ""
            })
            return [Chunk(content=clean_content, metadata=meta)]
            
        # Handle text before the first header
        if matches[0].start() > 0:
            pre_header_content = content[:matches[0].start()].strip()
            if pre_header_content:
                # Determine pages
                pages = get_pages_for_range(0, matches[0].start(), 1)
                meta = document.metadata.copy()
                
                # Clean markers
                clean_content = page_marker_regex.sub('', pre_header_content).strip()
                
                meta.update({
                    "page_numbers": pages,
                    "header": None,
                    "header_level": 0,
                    "header_path": ""
                })
                
                chunks.append(Chunk(content=clean_content, metadata=meta))

        # Stack to keep track of header hierarchy
        header_stack: List[Tuple[int, str]] = []

        for i, match in enumerate(matches):
            start_idx = match.start()
            end_idx = matches[i+1].start() if i + 1 < len(matches) else len(content)
            
            section_content = content[start_idx:end_idx] # Keep raw first to find markers
            
            header_level = len(match.group(1))
            header_title = match.group(2).strip()
            
            while header_stack and header_stack[-1][0] >= header_level:
                header_stack.pop()
            header_stack.append((header_level, header_title))
            header_path = " > ".join([h[1] for h in header_stack])
            
            if not section_content.strip():
                continue

            # Calculate Page Numbers
            # The start page is determined by the last marker seen before this section
            start_page_context = get_last_page_before(start_idx)
            pages = get_pages_for_range(start_idx, end_idx, start_page_context)

            # Clean content (remove page markers)
            clean_content = page_marker_regex.sub('', section_content).strip()

            chunk_metadata = document.metadata.copy()
            chunk_metadata.update({
                "header": header_title,
                "header_level": header_level,
                "header_path": header_path,
                "page_numbers": pages
            })
            
            chunks.append(Chunk(
                content=clean_content,
                metadata=chunk_metadata
            ))
            
        return chunks

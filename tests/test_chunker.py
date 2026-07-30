from langparse.chunkers.semantic import SemanticChunker
from langparse.types import Document


def test_semantic_chunker_basic():
    content = """# Header 1
Content 1.
## Header 2
Content 2.
"""
    doc = Document(content=content, metadata={})
    chunker = SemanticChunker()
    chunks = chunker.chunk(doc)

    assert len(chunks) == 2
    assert chunks[0].metadata["header"] == "Header 1"
    assert chunks[1].metadata["header"] == "Header 2"
    assert chunks[1].metadata["header_path"] == "Header 1 > Header 2"


def test_semantic_chunker_page_tracking():
    content = """
<!-- page_number: 1 -->
# Page 1 Header
Text on page 1.
<!-- page_number: 2 -->
Text on page 2.
## Page 2 Header
Text under header on page 2.
"""
    doc = Document(content=content, metadata={})
    chunker = SemanticChunker()
    chunks = chunker.chunk(doc)

    # Chunk 1: Page 1 Header (spans page 1 and 2)
    # "Text on page 1." is p1. "Text on page 2." is p2.
    # The header itself starts on p1.
    c1 = chunks[0]
    # Depending on implementation, the first chunk might be the pre-header text (empty or newline)
    # or the first header.
    # In our case, "<!-- page_number: 1 -->" is removed, leaving "\n".
    # If the chunker strips empty chunks, we go straight to header.

    # Let's inspect chunks to be safe
    idx = 0
    if chunks[0].metadata.get("header") is None:
        # This is the pre-header newline
        idx = 1

    c1 = chunks[idx]
    assert c1.metadata["header"] == "Page 1 Header"
    assert 1 in c1.metadata["page_numbers"]
    assert 2 in c1.metadata["page_numbers"]

    # Chunk 2: Page 2 Header
    c2 = chunks[idx + 1]
    assert c2.metadata["header"] == "Page 2 Header"
    assert c2.metadata["page_numbers"] == [2]


def test_semantic_chunker_marker_cleanup():
    content = "<!-- page_number: 1 -->\nClean text."
    doc = Document(content=content, metadata={})
    chunker = SemanticChunker()
    chunks = chunker.chunk(doc)

    assert "<!-- page_number" not in chunks[0].content
    assert chunks[0].content.strip() == "Clean text."

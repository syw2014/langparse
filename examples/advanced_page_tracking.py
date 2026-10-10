import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langparse import Document, SemanticChunker


def main():
    # Simulate a document with page markers
    # Imagine this content came from a PDFParser
    simulated_content = """
# Introduction
<!-- page_number: 1 -->
Welcome to LangParse. This is the first page.
It talks about the basics.

## Features
<!-- page_number: 2 -->
Here we are on page 2.
We discuss high-fidelity parsing.

### Deep Dive
This section is still on page 2.
<!-- page_number: 3 -->
But this paragraph flows into page 3.
The chunker should detect that this section spans page 2 and 3.
"""

    print("--- Simulating PDF Content with Page Markers ---")
    doc = Document(content=simulated_content, metadata={"source": "manual_test.pdf"})

    chunker = SemanticChunker()
    chunks = chunker.chunk(doc)

    for i, chunk in enumerate(chunks):
        print(f"\n[Chunk {i + 1}]")
        print(f"Header: {chunk.metadata.get('header')}")
        print(f"Pages: {chunk.metadata.get('page_numbers')}")
        print(f"Content Preview: {chunk.content.strip()[:50]}...")


if __name__ == "__main__":
    main()

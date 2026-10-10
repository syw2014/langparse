import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


from langparse import MarkdownParser, SemanticChunker


def main():
    # 1. Initialize Parser and Chunker
    parser = MarkdownParser()
    chunker = SemanticChunker()

    # 2. Parse the README file
    file_path = "README_cn.md"
    print(f"Parsing {file_path}...")
    try:
        doc = parser.parse(file_path)
    except FileNotFoundError:
        # Fallback for testing if running from different dir
        file_path = "../README_cn.md"
        doc = parser.parse(file_path)

    print(f"Document parsed. Total length: {len(doc.content)} characters.")

    # 3. Chunk the document
    print("Chunking document...")
    chunks = chunker.chunk(doc)
    print(f"Total chunks generated: {len(chunks)}")

    # 4. Display results
    print("\n--- Chunks Preview ---")
    for i, chunk in enumerate(chunks):
        print(f"\n[Chunk {i + 1}]")
        print(f"Metadata: {chunk.metadata}")
        # Show first line only for preview
        preview = chunk.content.split("\n")[0]
        print(f"Content Preview: {preview}...")
        print("-" * 40)


if __name__ == "__main__":
    main()

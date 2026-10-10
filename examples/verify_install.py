#!/usr/bin/env python3
"""
Test script to verify langparse installation.
This should be run AFTER installing the package.
"""


def test_basic_import():
    """Test that we can import the main modules."""
    print("Testing basic imports...")
    try:
        from langparse import (
            AutoParser,
            Chunk,
            Document,
            DocxParser,
            ExcelParser,
            MarkdownParser,
            SemanticChunker,
        )

        exports = (
            AutoParser,
            Chunk,
            Document,
            DocxParser,
            ExcelParser,
            MarkdownParser,
            SemanticChunker,
        )
        print(f"✓ All {len(exports)} imports successful")
        return True
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        return False


def test_markdown_parsing():
    """Test basic markdown parsing."""
    print("\nTesting Markdown parsing...")
    try:
        import tempfile

        from langparse import MarkdownParser, SemanticChunker

        # Create a temporary markdown file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("""# Test Document
This is a test.

## Section 1
Content here.
""")
            temp_path = f.name

        # Parse it
        parser = MarkdownParser()
        doc = parser.parse(temp_path)

        # Chunk it
        chunker = SemanticChunker()
        chunks = chunker.chunk(doc)

        print(f"✓ Parsed document with {len(chunks)} chunks")
        print(f"  First chunk header: {chunks[0].metadata.get('header')}")

        # Cleanup
        import os

        os.unlink(temp_path)
        return True
    except Exception as e:
        print(f"✗ Markdown parsing failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_autoparser():
    """Test AutoParser routing."""
    print("\nTesting AutoParser...")
    try:
        import tempfile

        from langparse import AutoParser

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# Auto Test")
            temp_path = f.name

        doc = AutoParser.parse(temp_path)
        print("✓ AutoParser successfully routed .md file")
        print(f"  Metadata: {doc.metadata}")

        import os

        os.unlink(temp_path)
        return True
    except Exception as e:
        print(f"✗ AutoParser failed: {e}")
        return False


def main():
    print("=" * 60)
    print("LangParse Installation Test")
    print("=" * 60)

    results = []
    results.append(("Basic Imports", test_basic_import()))
    results.append(("Markdown Parsing", test_markdown_parsing()))
    results.append(("AutoParser", test_autoparser()))

    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    for test_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {test_name}")

    all_passed = all(r[1] for r in results)
    print("\n" + ("=" * 60))
    if all_passed:
        print("✓ All tests passed! LangParse is working correctly.")
    else:
        print("✗ Some tests failed. Please check the output above.")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    exit(main())

import pytest

from langparse.chunkers.semantic import SemanticChunker
from langparse.types import Document


def chunk(content, **kwargs):
    return SemanticChunker(**kwargs).chunk(Document(content=content, metadata={}))


def test_section_under_the_limit_stays_one_chunk():
    content = "# Title\n\nShort body.\n"

    assert len(chunk(content, max_chunk_size=1000)) == 1


def test_long_section_is_split_to_respect_max_chunk_size():
    paragraphs = "\n\n".join(f"Paragraph {i} " + "word " * 40 for i in range(6))
    content = f"# Title\n\n{paragraphs}\n"

    chunks = chunk(content, max_chunk_size=300)

    assert len(chunks) > 1
    assert all(len(c.content) <= 300 for c in chunks)


def test_every_split_chunk_keeps_the_section_header_path():
    paragraphs = "\n\n".join("word " * 60 for _ in range(4))
    content = f"# Top\n\n## Nested\n\n{paragraphs}\n"

    chunks = [c for c in chunk(content, max_chunk_size=200) if c.metadata["header"] == "Nested"]

    assert len(chunks) > 1
    assert all(c.metadata["header_path"] == "Top > Nested" for c in chunks)


def test_chunks_are_indexed():
    content = "# A\n\nbody\n\n# B\n\nbody\n"

    assert [c.metadata["chunk_index"] for c in chunk(content)] == [0, 1]


def test_oversized_table_splits_by_row_repeating_the_header():
    rows = "\n".join(f"| r{i} | {'x' * 30} |" for i in range(12))
    content = f"# T\n\n| Name | Value |\n| --- | --- |\n{rows}\n"

    chunks = [c for c in chunk(content, max_chunk_size=250) if "|" in c.content]

    assert len(chunks) > 1
    assert all("| Name | Value |" in c.content for c in chunks)


def test_oversized_code_block_is_kept_whole_and_flagged():
    body = "\n".join(f"line_{i} = {i}" for i in range(80))
    content = f"# C\n\n```python\n{body}\n```\n"

    chunks = [c for c in chunk(content, max_chunk_size=200) if "line_0" in c.content]

    assert len(chunks) == 1
    assert "line_79" in chunks[0].content
    assert chunks[0].metadata["oversized"] is True


def test_hash_inside_code_no_longer_creates_a_bogus_section():
    content = "# Real\n\n```python\n# not a heading\nx = 1\n```\n"

    headers = [c.metadata["header"] for c in chunk(content)]

    assert headers == ["Real"]


def test_length_function_controls_the_boundaries():
    content = "# T\n\n" + "\n\n".join("word " * 20 for _ in range(5))

    by_words = chunk(content, max_chunk_size=30, length_function=lambda t: len(t.split()))
    by_chars = chunk(content, max_chunk_size=30)

    assert len(by_words) < len(by_chars)


def test_overlap_repeats_the_tail_of_the_previous_chunk():
    paragraphs = "\n\n".join(f"Para{i} " + "word " * 30 for i in range(4))
    content = f"# T\n\n{paragraphs}\n"

    chunks = chunk(content, max_chunk_size=250, overlap=60)

    assert len(chunks) > 1
    # The second chunk opens with material that closed the first one.
    assert chunks[1].content[:40] in chunks[0].content


def test_overlap_defaults_to_off():
    paragraphs = "\n\n".join(f"Para{i} " + "word " * 30 for i in range(4))
    chunks = chunk(f"# T\n\n{paragraphs}\n", max_chunk_size=250)

    assert chunks[1].content[:40] not in chunks[0].content


def test_min_chunk_size_is_gone():
    with pytest.raises(TypeError):
        SemanticChunker(min_chunk_size=100)

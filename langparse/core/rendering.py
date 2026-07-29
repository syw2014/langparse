from __future__ import annotations

from pathlib import Path

from langparse.types import Document, ParsedDocumentResult

PAGE_MARKER_TEMPLATE = "<!-- page_number: {page_number} -->"


def document_from_result(parsed: ParsedDocumentResult) -> Document:
    """
    Render the structured parse result into the flat Markdown ``Document`` that
    chunkers and end users consume.

    Page markers are injected only for paginated results. A flow format such as
    plain Markdown has no page boundaries to mark, and injecting a fake one
    would corrupt any markers the source already carries.
    """
    if parsed.paginated:
        blocks: list[str] = []
        for page in parsed.pages:
            blocks.append(f"\n{PAGE_MARKER_TEMPLATE.format(page_number=page.page_number)}\n")
            blocks.append(page.markdown_content)
        content = "\n".join(blocks)
    else:
        content = "\n".join(page.markdown_content for page in parsed.pages)

    return Document(content=content, metadata=document_metadata(parsed))


def document_metadata(parsed: ParsedDocumentResult) -> dict:
    """
    Build the Document metadata.

    Engine-specific detail stays nested under ``parsed_metadata`` on purpose:
    SemanticChunker copies this dict into every chunk, so flattening MinerU's
    runtime fields here would duplicate them across every chunk written to a
    vector store.
    """
    return {
        "source": parsed.source,
        "filename": parsed.filename,
        "extension": parsed.metadata.get("extension") or Path(parsed.filename).suffix,
        "engine": parsed.engine,
        # Copied, not aliased: SemanticChunker shallow-copies this dict into
        # every chunk, so sharing one instance would let a later mutation of the
        # parse result reach through into already-emitted chunks.
        "parsed_metadata": dict(parsed.metadata),
    }

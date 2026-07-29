from __future__ import annotations

from pathlib import Path

#: Single source of truth for which extensions LangParse handles and which
#: parser family owns each one. AutoParser, ParseService routing, directory
#: expansion and CLI error messages all read from here so they cannot drift.
PARSER_KIND_BY_EXTENSION: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".doc": "docx",
    ".xlsx": "excel",
    ".xls": "excel",
    ".csv": "excel",
    ".md": "markdown",
    ".txt": "markdown",
}

SUPPORTED_EXTENSIONS = frozenset(PARSER_KIND_BY_EXTENSION)


def parser_kind_for(file_path) -> str | None:
    """Return the parser family for a path, or None when unsupported."""
    return PARSER_KIND_BY_EXTENSION.get(Path(file_path).suffix.lower())


def is_supported(file_path) -> bool:
    return parser_kind_for(file_path) is not None


def unsupported_extension_error(file_path) -> ValueError:
    suffix = Path(file_path).suffix.lower() or "(no extension)"
    supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
    return ValueError(f"Unsupported file extension: {suffix}. Supported: {supported}")

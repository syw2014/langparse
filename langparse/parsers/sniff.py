from __future__ import annotations

import zipfile
from pathlib import Path

#: Magic-byte signatures for formats we can identify without a dependency.
_PDF_SIGNATURE = b"%PDF-"
_ZIP_SIGNATURE = b"PK\x03\x04"
_OLE_CFB_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

#: OOXML zip packages are only distinguishable by which top-level folder
#: their parts live under -- the file extension plays no part in this.
_OOXML_KIND_BY_NAMELIST_PREFIX = {
    "word/": "docx",
    "xl/": "excel",
}


def sniff_kind(file_path) -> str | None:
    """Best-effort parser-kind detection from file content, independent of extension.

    Extensions can lie -- a renamed or re-exported file can carry the wrong
    suffix. Returns a `PARSER_KIND_BY_EXTENSION` value when the signature is
    conclusive (PDF, OOXML docx/xlsx). Returns None when it isn't -- legacy
    OLE binaries, plain text (csv/md/txt), a missing file, or an unrecognized
    layout -- so the caller falls back to the extension.
    """
    header = _read_header(file_path)
    if header is None:
        return None
    if header.startswith(_PDF_SIGNATURE):
        return "pdf"
    if header.startswith(_ZIP_SIGNATURE):
        return _sniff_ooxml_kind(file_path)
    return None


def looks_like_zip_ooxml(file_path) -> bool:
    """True when the file is any ZIP-based Office document (docx/xlsx/...),
    regardless of extension. Used to catch a workbook mislabeled `.csv`."""
    header = _read_header(file_path)
    return header is not None and header.startswith(_ZIP_SIGNATURE)


def looks_like_ole_binary(file_path) -> bool:
    """True when the file is a legacy OLE Compound File Binary container
    (pre-2007 .doc/.xls), regardless of extension. The signature alone can't
    tell a Word doc from a workbook -- callers only check this after routing
    has already settled the family via the extension."""
    header = _read_header(file_path)
    return header is not None and header.startswith(_OLE_CFB_SIGNATURE)


def _read_header(file_path, size: int = 8) -> bytes | None:
    path = Path(file_path)
    try:
        with path.open("rb") as handle:
            return handle.read(size)
    except OSError:
        return None


def _sniff_ooxml_kind(file_path) -> str | None:
    try:
        with zipfile.ZipFile(file_path) as archive:
            names = archive.namelist()
    except zipfile.BadZipFile:
        return None
    for prefix, kind in _OOXML_KIND_BY_NAMELIST_PREFIX.items():
        if any(name.startswith(prefix) for name in names):
            return kind
    return None

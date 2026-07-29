from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Iterable


def output_filename(source, fmt: str) -> str:
    suffix = ".md" if fmt == "markdown" else ".json"
    return f"{Path(source).stem}{suffix}"


def extension_tagged_filename(source, fmt: str) -> str:
    """``report.docx`` -> ``report-docx.md``, to tell same-stem siblings apart."""
    source_path = Path(source)
    suffix = ".md" if fmt == "markdown" else ".json"
    source_kind = source_path.suffix.lower().lstrip(".")
    stem = f"{source_path.stem}-{source_kind}" if source_kind else source_path.stem
    return f"{stem}{suffix}"


def resolve_output_path(
    source,
    fmt: str,
    used_paths: set[Path],
    preferred_filename: str | None = None,
) -> Path:
    """
    Pick a repo-relative output path for one source, widening the parent prefix
    until it no longer collides with a path already handed out.

    Two sources sharing a stem (``alpha/report.pdf`` and ``beta/report.pdf``)
    must not both resolve to ``report.md`` — the second would silently
    overwrite the first.
    """
    source_path = Path(source)
    filename = preferred_filename or output_filename(source_path, fmt)
    parent_parts = [
        part for part in source_path.parent.parts if part not in {"", ".", source_path.anchor}
    ]

    def with_prefix(width: int) -> Path:
        return Path(*parent_parts[-width:]) / filename if width else Path(filename)

    if source_path.is_absolute():
        widths: Iterable[int] = range(0, len(parent_parts) + 1)
    else:
        widths = [len(parent_parts), *range(1, len(parent_parts)), 0]

    for width in widths:
        candidate = with_prefix(width)
        if candidate not in used_paths:
            used_paths.add(candidate)
            return candidate

    stem, suffix = Path(filename).stem, Path(filename).suffix
    counter = 1
    while True:
        candidate = Path(f"{stem}-{counter}{suffix}")
        if candidate not in used_paths:
            used_paths.add(candidate)
            return candidate
        counter += 1


def resolve_output_paths(sources: Iterable, fmt: str) -> list[Path]:
    """
    Resolve every source to a distinct relative output path, in input order.

    Collisions get the disambiguator that actually carries information:
    same-stem siblings in one directory (``report.pdf`` next to ``report.docx``)
    are told apart by source format, because widening the parent prefix would
    only scatter siblings across unrelated output directories. Same-stem sources
    in *different* directories keep the plain name and widen the prefix instead.
    """
    sources = list(sources)
    sibling_counts = Counter(
        (Path(source).parent, Path(source).stem) for source in sources
    )

    used_paths: set[Path] = set()
    resolved: list[Path] = []
    for source in sources:
        source_path = Path(source)
        has_same_dir_twin = sibling_counts[(source_path.parent, source_path.stem)] > 1
        preferred = extension_tagged_filename(source, fmt) if has_same_dir_twin else None
        resolved.append(resolve_output_path(source, fmt, used_paths, preferred))
    return resolved

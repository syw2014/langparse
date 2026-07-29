from __future__ import annotations

from pathlib import Path
from typing import Iterable


def output_filename(source, fmt: str) -> str:
    suffix = ".md" if fmt == "markdown" else ".json"
    return f"{Path(source).stem}{suffix}"


def resolve_output_path(source, fmt: str, used_paths: set[Path]) -> Path:
    """
    Pick a repo-relative output path for one source, widening the parent prefix
    until it no longer collides with a path already handed out.

    Two sources sharing a stem (``alpha/report.pdf`` and ``beta/report.pdf``)
    must not both resolve to ``report.md`` — the second would silently overwrite
    the first.
    """
    source_path = Path(source)
    filename = output_filename(source_path, fmt)
    parent_parts = [
        part for part in source_path.parent.parts if part not in {"", ".", source_path.anchor}
    ]

    candidates: list[Path] = []
    if source_path.is_absolute():
        candidates.append(Path(filename))
        for width in range(1, len(parent_parts) + 1):
            candidates.append(Path(*parent_parts[-width:]) / filename)
    else:
        if parent_parts:
            candidates.append(Path(*parent_parts) / filename)
        for width in range(1, len(parent_parts)):
            candidates.append(Path(*parent_parts[-width:]) / filename)
        candidates.append(Path(filename))

    for candidate in candidates:
        if candidate not in used_paths:
            used_paths.add(candidate)
            return candidate

    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 1
    while True:
        candidate = Path(f"{stem}-{counter}{suffix}")
        if candidate not in used_paths:
            used_paths.add(candidate)
            return candidate
        counter += 1


def resolve_output_paths(sources: Iterable, fmt: str) -> list[Path]:
    """Resolve every source to a distinct relative output path, in input order."""
    used_paths: set[Path] = set()
    return [resolve_output_path(source, fmt, used_paths) for source in sources]

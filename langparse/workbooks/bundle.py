"""Versioned workbook consumption interface with explicit export omissions."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import fields, is_dataclass
from typing import Any

from langparse.types import ParsedDocumentResult
from langparse.workbooks.lineage import overlaps
from langparse.workbooks.types import SourceRef, WorkbookIR

BUNDLE_SCHEMA_VERSION = 1


def _value(item: Any) -> Any:
    if isinstance(item, SourceRef):
        return item.key
    if is_dataclass(item):
        return {field.name: _value(getattr(item, field.name)) for field in fields(item)}
    if isinstance(item, dict):
        if set(item) == {"sheet_name", "range"}:
            return f"{item['sheet_name']}!{item['range']}"
        return {str(key): _value(value) for key, value in item.items()}
    if isinstance(item, (list, tuple)):
        return [_value(value) for value in item]
    if hasattr(item, "isoformat"):
        return item.isoformat()
    if item is None or isinstance(item, (str, bool, int, float)):
        return item
    return str(item)


def _cell(sheet, cell) -> dict:
    return {"source_ref": f"{sheet.name}!{cell.coordinate}", **_value(cell)}


def _edge(edge) -> dict:
    return _value(edge)


class WorkbookBundle:
    """Stable JSON partitions and queries over a parsed or serialized workbook."""

    def __init__(self, payload: dict, parsed: ParsedDocumentResult | None = None):
        if (
            type(payload.get("schema_version")) is not int
            or payload["schema_version"] != BUNDLE_SCHEMA_VERSION
        ):
            raise ValueError("Unsupported workbook bundle schema version")
        for key in ("facts", "structures", "relations", "diagnostics", "provenance"):
            if not isinstance(payload.get(key), dict):
                raise ValueError(f"Workbook bundle {key} must be an object")
        for group, key in (
            ("facts", "sheets"),
            ("structures", "blocks"),
            ("relations", "dependencies"),
        ):
            if not isinstance(payload[group].get(key), list):
                raise ValueError(f"Workbook bundle {group}.{key} must be an array")
        sheet_names = set()
        for sheet in payload["facts"]["sheets"]:
            if not isinstance(sheet, dict) or not isinstance(sheet.get("name"), str):
                raise ValueError("Workbook bundle sheet must have a name")
            if sheet["name"] in sheet_names:
                raise ValueError("Duplicate workbook bundle sheet")
            sheet_names.add(sheet["name"])
            if sheet.get("cells") is not None and not isinstance(sheet["cells"], list):
                raise ValueError("Workbook bundle cells must be an array or null")

        def source(value):
            if not isinstance(value, str) or "!" not in value:
                raise ValueError("Invalid workbook bundle source ref")
            name, cell_range = value.rsplit("!", 1)
            ref = SourceRef(name, cell_range)
            if name not in sheet_names:
                raise ValueError("Workbook bundle source ref uses unknown sheet")
            try:
                if not overlaps(ref, ref):
                    raise ValueError("reversed range")
            except ValueError as exc:
                raise ValueError("Invalid workbook bundle source range") from exc

        def sources(value, *, nullable=False):
            if isinstance(value, list):
                for item in value:
                    sources(item, nullable=nullable)
            elif value is not None or not nullable:
                source(value)

        def refs(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {"source_ref", "dependent", "target"} and item is not None:
                        source(item)
                    elif key.endswith("source_refs"):
                        if not isinstance(item, list):
                            raise ValueError("Workbook bundle source refs must be an array")
                        sources(item, nullable=key == "value_source_refs")
                    else:
                        refs(item)
            elif isinstance(value, list):
                for item in value:
                    refs(item)

        refs(payload)
        self._payload = deepcopy(payload)
        self._parsed = parsed

    @classmethod
    def from_result(
        cls,
        parsed: ParsedDocumentResult,
        *,
        include_cells: bool = False,
        max_rows: int | None = 200,
    ) -> WorkbookBundle:
        if not isinstance(parsed.structure, WorkbookIR) or parsed.structure.snapshot is None:
            raise TypeError("Workbook Bundle requires a rich OOXML workbook result")
        if type(include_cells) is not bool:
            raise ValueError("include_cells must be boolean")
        if max_rows is not None and (type(max_rows) is not int or max_rows < 1):
            raise ValueError("max_rows must be a positive integer or None")
        workbook = parsed.structure
        snapshot = workbook.snapshot
        blocks = []
        for sheet in workbook.sheets:
            for block in sheet.blocks:
                item = {
                    "id": block.block_id,
                    "sheet": sheet.name,
                    "kind": block.kind,
                    "source_refs": [ref.key for ref in block.source_refs],
                    "confidence": block.confidence,
                    "diagnostics": _value(block.diagnostics),
                }
                for name, content in (
                    ("table", block.logical_table),
                    ("form", block.form),
                    ("matrix", block.matrix),
                    ("text", block.text),
                ):
                    if content is not None:
                        data = _value(content)
                        if name == "table":
                            data["row_count"] = len(content.rows)
                            data["rows"] = data["rows"][:max_rows]
                            data["omitted_rows"] = len(content.rows) - len(data["rows"])
                        elif name == "matrix":
                            data["row_count"] = len(content.values)
                            for key in ("values", "row_headers", "value_source_refs"):
                                data[key] = data[key][:max_rows]
                            data["omitted_rows"] = len(content.values) - len(data["values"])
                        item[name] = data
                if block.kind in {"chart", "image"}:
                    item["object"] = _value(block.metadata["object"])
                blocks.append(item)
        from langparse import __version__

        return cls(
            {
                "schema_version": BUNDLE_SCHEMA_VERSION,
                "facts": {
                    "sheets": [
                        {
                            "name": sheet.name,
                            "visibility": sheet.visibility,
                            "used_range": sheet.used_range,
                            "cell_count": len(sheet.cells),
                            "merged_ranges": list(sheet.merged_ranges),
                            "cells": [_cell(sheet, cell) for cell in sheet.cells.values()]
                            if include_cells
                            else None,
                            "objects": _value(sheet.objects),
                        }
                        for sheet in snapshot.sheets
                    ],
                    "references": _value(snapshot.reference_facts),
                },
                "structures": {"blocks": blocks},
                "relations": {
                    "dependencies": [_edge(edge) for edge in workbook.lineage.edges]
                    if workbook.lineage
                    else [],
                    "continuations": [
                        {
                            "id": item.continuation_id,
                            "member_table_ids": item.member_table_ids,
                            "source_refs": [ref.key for ref in item.source_refs],
                        }
                        for item in workbook.table_continuations
                    ],
                },
                "diagnostics": _value(parsed.diagnostics) if parsed.diagnostics else {},
                "provenance": {
                    "source": parsed.source,
                    "filename": parsed.filename,
                    "parser_version": __version__,
                    "engine": parsed.engine,
                    "omissions": {
                        "cells": not include_cells,
                        "media_binary": True,
                        "source_binary": True,
                        "max_rows_per_block": max_rows,
                    },
                },
            },
            parsed,
        )

    @classmethod
    def from_json(cls, text: str) -> WorkbookBundle:
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"Duplicate bundle field: {key}")
                result[key] = value
            return result

        payload = json.loads(text, object_pairs_hook=unique)
        if not isinstance(payload, dict):
            raise ValueError("Workbook bundle root must be an object")
        return cls(payload)

    def to_dict(self) -> dict:
        return deepcopy(self._payload)

    def to_json(self) -> str:
        return json.dumps(self._payload, ensure_ascii=False, sort_keys=True, indent=2)

    def blocks(self, *, sheet: str | None = None, kind: str | None = None) -> list[dict]:
        return deepcopy(
            [
                block
                for block in self._payload["structures"]["blocks"]
                if (sheet is None or block["sheet"] == sheet)
                and (kind is None or block["kind"] == kind)
            ]
        )

    def tables(self, *, sheet: str | None = None) -> list[dict]:
        return [block["table"] for block in self.blocks(sheet=sheet) if "table" in block]

    def cells(self, *, sheet: str, source_range: str | None = None) -> list[dict]:
        if self._parsed is not None:
            snapshot = self._parsed.structure.snapshot
            selected = next((item for item in snapshot.sheets if item.name == sheet), None)
            if selected is None:
                raise ValueError(f"Unknown workbook sheet: {sheet}")
            cells = [_cell(selected, cell) for cell in selected.cells.values()]
        else:
            selected = next(
                (item for item in self._payload["facts"]["sheets"] if item["name"] == sheet), None
            )
            if selected is None:
                raise ValueError(f"Unknown workbook sheet: {sheet}")
            cells = selected["cells"]
            if cells is None:
                raise ValueError(
                    "Cells were omitted; export with include_cells=True to query a loaded bundle"
                )
        if source_range is not None:
            region = SourceRef(sheet, source_range)
            cells = [
                cell for cell in cells if overlaps(region, SourceRef(sheet, cell["coordinate"]))
            ]
        return deepcopy(cells)

    def relations(
        self, *, source_ref: str | None = None, direction: str = "dependencies"
    ) -> list[dict]:
        if direction not in {"dependencies", "dependents"}:
            raise ValueError("direction must be dependencies or dependents")
        edges = self._payload["relations"]["dependencies"]
        if source_ref is not None:
            name, cell_range = source_ref.rsplit("!", 1)
            selected = SourceRef(name, cell_range)
            key = "dependent" if direction == "dependencies" else "target"
            edges = [
                edge
                for edge in edges
                if edge[key] and overlaps(selected, SourceRef(*edge[key].rsplit("!", 1)))
            ]
        return deepcopy(edges)

    @property
    def diagnostics(self) -> dict:
        return deepcopy(self._payload["diagnostics"])

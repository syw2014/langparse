"""Independent range-level dependency graph with bounded, non-expanding queries."""

import re
from dataclasses import dataclass, field

from langparse.workbooks.reference_types import DependencyEdge, ReferenceDiagnostic
from langparse.workbooks.types import SourceRef, WorkbookSnapshot


def _bounds(value):
    if not isinstance(value, str):
        raise ValueError("Expected a finite A1 range")
    parts = value.replace("$", "").upper().split(":")
    if len(parts) not in {1, 2}:
        raise ValueError(f"Expected finite A1 range, got {value!r}")
    result = []
    for part in (parts[0], parts[-1]):
        match = re.fullmatch(r"([A-Z]+)([1-9][0-9]*)", part)
        if not match:
            raise ValueError(f"Expected finite A1 range, got {value!r}")
        column = 0
        for char in match[1]:
            column = column * 26 + ord(char) - 64
        result.append((column, int(match[2])))
    left, top = result[0]
    right, bottom = result[1]
    if not (1 <= left <= right <= 16384 and 1 <= top <= bottom <= 1048576):
        raise ValueError(f"Range is outside Excel bounds: {value!r}")
    return left, top, right, bottom


def overlaps(first: SourceRef, second: SourceRef) -> bool:
    if first.sheet_name.casefold() != second.sheet_name.casefold():
        return False
    a, b, c, d = _bounds(first.range)
    e, f, g, h = _bounds(second.range)
    return a <= g and e <= c and b <= h and f <= d


@dataclass
class WorkbookLineage:
    edges: list[DependencyEdge] = field(default_factory=list)
    diagnostics: list[ReferenceDiagnostic] = field(default_factory=list)

    def dependencies_of(self, source: SourceRef) -> list[DependencyEdge]:
        return [edge for edge in self.edges if overlaps(edge.dependent, source)]

    def dependents_of(self, source: SourceRef) -> list[DependencyEdge]:
        return [edge for edge in self.edges if edge.target and overlaps(edge.target, source)]


def build_lineage(snapshot: WorkbookSnapshot) -> WorkbookLineage:
    facts = snapshot.reference_facts
    result = WorkbookLineage(diagnostics=list(facts.diagnostics))
    for formula in facts.formulas:
        for reference in formula.references:
            if reference.status == "resolved" and not reference.targets:
                continue
            for target in reference.targets or [None]:
                result.edges.append(
                    DependencyEdge(
                        formula.source_ref,
                        target,
                        reference.reference,
                        reference.status,
                        [formula.source_ref, *([target] if target else [])],
                        reference.external_workbook,
                    )
                )
    # Iterative DFS avoids recursion limits on long formula chains.
    nodes = {f.source_ref.key: f.source_ref for f in facts.formulas}
    adjacency = {key: [] for key in nodes}
    for edge in result.edges:
        if edge.target:
            adjacency[edge.dependent.key].extend(
                key for key, ref in nodes.items() if overlaps(edge.target, ref)
            )
    visited, active, reported = set(), set(), set()
    for start in nodes:
        if start in visited:
            continue
        stack = [(start, iter(adjacency[start]))]
        active.add(start)
        while stack:
            node, children = stack[-1]
            child = next(children, None)
            if child is None:
                visited.add(node)
                active.remove(node)
                stack.pop()
            elif child in active:
                path = [item[0] for item in stack]
                cycle = path[path.index(child) :]
                identity = frozenset(cycle)
                if identity not in reported:
                    reported.add(identity)
                    result.diagnostics.append(
                        ReferenceDiagnostic(
                            "circular_reference",
                            " -> ".join([*cycle, child]),
                            [nodes[key] for key in cycle],
                        )
                    )
            elif child not in visited:
                active.add(child)
                stack.append((child, iter(adjacency[child])))
    return result

"""
Fidelity scoring against known-good output.

The quality checks in `quality.py` measure structure -- how many pages, whether
any tables were found. That says nothing about whether the extracted content is
*correct*. These functions compare a parse against a reference so accuracy
claims can be substantiated rather than asserted.
"""

from __future__ import annotations

MAX_TOKENS = 5000


def _tokens(text: str) -> list[str]:
    return text.split()


def _edit_distance(left: list, right: list, substitution_cost=None) -> float:
    """
    Levenshtein distance with a pluggable substitution cost.

    A cost function returning values in [0, 1] lets callers charge partial credit
    for near-matches instead of a flat 1 per mismatch.
    """
    if substitution_cost is None:

        def substitution_cost(a, b):
            return 0.0 if a == b else 1.0

    if not left:
        return float(len(right))
    if not right:
        return float(len(left))

    previous = [float(index) for index in range(len(right) + 1)]
    for i, left_item in enumerate(left, start=1):
        current = [float(i)]
        for j, right_item in enumerate(right, start=1):
            current.append(
                min(
                    previous[j] + 1.0,
                    current[j - 1] + 1.0,
                    previous[j - 1] + substitution_cost(left_item, right_item),
                )
            )
        previous = current
    return previous[-1]


def text_similarity_detail(expected: str, actual: str) -> dict:
    """
    Word-level normalised edit distance, with the truncation flag.

    Compared on whitespace-separated tokens rather than characters: it is both
    far cheaper and closer to what matters for retrieval, where a reflowed line
    break is not an error but a dropped word is.

    Inputs longer than MAX_TOKENS are truncated to keep the quadratic DP
    bounded, and `truncated` says so -- a score over the first quarter of a
    document must not be read as full-document fidelity.
    """
    all_expected = _tokens(expected)
    all_actual = _tokens(actual)
    expected_tokens = all_expected[:MAX_TOKENS]
    actual_tokens = all_actual[:MAX_TOKENS]
    truncated = len(all_expected) > MAX_TOKENS or len(all_actual) > MAX_TOKENS

    if not expected_tokens and not actual_tokens:
        score = 1.0
    else:
        distance = _edit_distance(expected_tokens, actual_tokens)
        worst = max(len(expected_tokens), len(actual_tokens))
        score = round(max(0.0, 1.0 - distance / worst), 4)

    return {
        "score": score,
        "truncated": truncated,
        "compared_tokens": max(len(expected_tokens), len(actual_tokens)),
    }


def text_similarity(expected: str, actual: str) -> float:
    """Word-level normalised edit distance as a similarity in [0, 1]."""
    return text_similarity_detail(expected, actual)["score"]


def _cell_cost(expected: str, actual: str) -> float:
    """Substitution cost between two cells, as character-level normalised distance."""
    if expected == actual:
        return 0.0
    if not expected or not actual:
        return 1.0
    distance = _edit_distance(list(expected), list(actual))
    return min(1.0, distance / max(len(expected), len(actual)))


def _row_cost(expected: list[str], actual: list[str]) -> float:
    """Cost of turning one row into another: an alignment of their cells."""
    return _edit_distance(expected, actual, substitution_cost=_cell_cost)


def _node_count(rows: list[list[str]]) -> int:
    """Nodes in the table tree: the table itself, one per row, one per cell."""
    if not rows:
        return 0
    return 1 + len(rows) + sum(len(row) for row in rows)


def teds(expected: list[list[str]], actual: list[list[str]]) -> float:
    """
    Tree-Edit-Distance-based Similarity for tables, in [0, 1].

    The table tree is table -> rows -> cells. Because cells cannot move between
    rows, the tree edit distance decomposes into an alignment of rows whose
    substitution cost is itself an alignment of that row's cells -- which is
    what Zhang-Shasha computes for a tree of this shape. Deleting a row costs
    the row node plus its cells; substituting cells costs their normalised
    character distance, so a typo scores better than a wrong value.
    """
    if not expected and not actual:
        return 1.0
    if not expected or not actual:
        return 0.0

    def row_substitution(expected_row, actual_row):
        return _row_cost(expected_row, actual_row)

    def row_indel(row):
        return 1.0 + len(row)

    distance = _tree_distance(expected, actual, row_substitution, row_indel)
    worst = max(_node_count(expected), _node_count(actual))
    return round(max(0.0, 1.0 - distance / worst), 4)


def _tree_distance(expected, actual, substitution, indel) -> float:
    """Sequence alignment over rows with subtree-sized insert/delete costs."""
    previous = [0.0]
    for actual_row in actual:
        previous.append(previous[-1] + indel(actual_row))

    for expected_row in expected:
        current = [previous[0] + indel(expected_row)]
        for j, actual_row in enumerate(actual, start=1):
            current.append(
                min(
                    previous[j] + indel(expected_row),
                    current[j - 1] + indel(actual_row),
                    previous[j - 1] + substitution(expected_row, actual_row),
                )
            )
        previous = current
    return previous[-1]

import pytest

from langparse.services.fidelity import teds, text_similarity


def test_identical_text_scores_one():
    assert text_similarity("the quick brown fox", "the quick brown fox") == 1.0


def test_completely_different_text_scores_zero():
    assert text_similarity("alpha beta", "gamma delta") == 0.0


def test_one_wrong_word_in_four_scores_three_quarters():
    assert text_similarity("a b c d", "a b c X") == 0.75


def test_text_similarity_ignores_whitespace_shape():
    assert text_similarity("a b\n\nc", "  a   b \n c  ") == 1.0


def test_empty_against_empty_scores_one():
    assert text_similarity("", "") == 1.0


def test_empty_against_content_scores_zero():
    assert text_similarity("", "something here") == 0.0


def test_identical_tables_score_one():
    rows = [["A", "B"], ["1", "2"]]

    assert teds(rows, rows) == 1.0


def test_empty_tables_score_one():
    assert teds([], []) == 1.0


def test_missing_table_scores_zero():
    assert teds([["A", "B"]], []) == 0.0


def test_one_changed_cell_scores_high_but_not_perfect():
    expected = [["A", "B"], ["1", "2"]]
    actual = [["A", "B"], ["1", "X"]]

    score = teds(expected, actual)

    assert 0.5 < score < 1.0


def test_a_dropped_row_costs_more_than_a_changed_cell():
    expected = [["A", "B"], ["1", "2"], ["3", "4"]]
    changed_cell = [["A", "B"], ["1", "2"], ["3", "X"]]
    dropped_row = [["A", "B"], ["1", "2"]]

    assert teds(expected, dropped_row) < teds(expected, changed_cell)


def test_transposed_content_scores_lower_than_correct():
    expected = [["A", "B"], ["1", "2"]]
    transposed = [["A", "1"], ["B", "2"]]

    assert teds(expected, transposed) < teds(expected, expected)


def test_teds_is_symmetric():
    a = [["A", "B"], ["1", "2"]]
    b = [["A", "B"], ["1", "X"], ["3", "4"]]

    assert teds(a, b) == pytest.approx(teds(b, a))


def test_scores_stay_within_the_unit_interval():
    cases = [
        ([["A"]], [["B"], ["C"], ["D"]]),
        ([["A", "B", "C"]], [["A"]]),
        ([], [["X"]]),
    ]

    for expected, actual in cases:
        assert 0.0 <= teds(expected, actual) <= 1.0


def test_truncation_is_reported_so_a_partial_score_is_not_read_as_full():
    from langparse.services.fidelity import MAX_TOKENS, text_similarity_detail

    long_text = " ".join(str(i) for i in range(MAX_TOKENS + 500))

    detail = text_similarity_detail(long_text, long_text)

    assert detail["truncated"] is True
    assert detail["compared_tokens"] == MAX_TOKENS


def test_short_input_is_not_marked_truncated():
    from langparse.services.fidelity import text_similarity_detail

    detail = text_similarity_detail("a b c", "a b c")

    assert detail["truncated"] is False
    assert detail["score"] == 1.0

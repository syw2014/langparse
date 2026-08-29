from __future__ import annotations

import pytest

from langparse.workbooks.evaluation.evaluator import (
    CaseObservation,
    CaseTruth,
    WorkbookEvaluationMetrics,
    classify_case_evaluation,
    evaluate_workbook_ambiguity,
)
from langparse.workbooks.evaluation.schema import InvalidGoldenSetError


def test_baseline_only_evaluation():
    truths = (
        CaseTruth(
            evaluation_id="eval-1",
            cohort="ambiguous",
            expected_kind="logical_table",
            baseline_kind="logical_table",
        ),
        CaseTruth(
            evaluation_id="eval-2",
            cohort="ambiguous",
            expected_kind="text",
            baseline_kind="unclassified",
        ),
        CaseTruth(
            evaluation_id="eval-3",
            cohort="ambiguous",
            expected_kind=None,  # unresolvable
            baseline_kind="unclassified",
        ),
    )

    metrics = evaluate_workbook_ambiguity(
        truths,
        observations=None,
        clear_sample_count=2,
        clear_unexpected_call_count=0,
    )

    assert isinstance(metrics, WorkbookEvaluationMetrics)
    assert metrics.ambiguous_case_count == 3
    assert metrics.resolvable_case_count == 2
    assert metrics.unresolvable_case_count == 1
    assert metrics.baseline_correct_count == 1
    assert metrics.baseline_wrong_count == 2  # eval-2 and eval-3 (unresolvable cannot be resolved)
    assert metrics.baseline_accuracy == 0.5  # 1 / 2 resolvable cases
    assert metrics.clear_sample_count == 2
    assert metrics.clear_unexpected_call_count == 0
    assert metrics.clear_call_rate == 0.0
    assert metrics.effectiveness_evidence is False

    # Model metrics must be None in baseline-only mode
    assert metrics.model_selected_count == 0
    assert metrics.model_correct_acceptance_count == 0
    assert metrics.model_wrong_acceptance_count == 0
    assert metrics.model_abstained_count == 0
    assert metrics.model_unresolved_count == 0
    assert metrics.model_failed_count == 0
    assert metrics.model_selection_accuracy is None
    assert metrics.wrong_acceptance_rate is None
    assert metrics.model_coverage is None
    assert metrics.abstain_rate is None
    assert metrics.unresolved_rate is None
    assert metrics.failure_rate is None
    assert metrics.net_correct_delta is None


def test_scripted_observation_transitions():
    truths = (
        # Case 1: fixed error (baseline wrong, model correct)
        CaseTruth(
            evaluation_id="eval-1",
            cohort="ambiguous",
            expected_kind="text",
            baseline_kind="unclassified",
        ),
        # Case 2: introduced error (baseline correct, model wrong)
        CaseTruth(
            evaluation_id="eval-2",
            cohort="ambiguous",
            expected_kind="logical_table",
            baseline_kind="logical_table",
        ),
        # Case 3: unchanged correct (both correct)
        CaseTruth(
            evaluation_id="eval-3",
            cohort="ambiguous",
            expected_kind="form",
            baseline_kind="form",
        ),
        # Case 4: unchanged wrong (both selected wrong)
        CaseTruth(
            evaluation_id="eval-4",
            cohort="ambiguous",
            expected_kind="matrix",
            baseline_kind="text",
        ),
        # Case 5: abstained (baseline wrong, model abstained)
        CaseTruth(
            evaluation_id="eval-5",
            cohort="ambiguous",
            expected_kind="text",
            baseline_kind="unclassified",
        ),
        # Case 6: unresolved (baseline correct, model unresolved)
        CaseTruth(
            evaluation_id="eval-6",
            cohort="ambiguous",
            expected_kind="logical_table",
            baseline_kind="logical_table",
        ),
        # Case 7: failed (baseline correct, model failed)
        CaseTruth(
            evaluation_id="eval-7",
            cohort="ambiguous",
            expected_kind="form",
            baseline_kind="form",
        ),
        # Case 8: unresolvable truth with safe abstain
        CaseTruth(
            evaluation_id="eval-8",
            cohort="ambiguous",
            expected_kind=None,
            baseline_kind="unclassified",
        ),
        # Case 9: unresolvable truth with wrong selection
        CaseTruth(
            evaluation_id="eval-9",
            cohort="ambiguous",
            expected_kind=None,
            baseline_kind="unclassified",
        ),
    )

    observations = (
        CaseObservation("eval-1", "harness_only", "selected", "text"),
        CaseObservation("eval-2", "harness_only", "selected", "form"),
        CaseObservation("eval-3", "harness_only", "selected", "form"),
        CaseObservation("eval-4", "harness_only", "selected", "form"),
        CaseObservation("eval-5", "harness_only", "abstained", None),
        CaseObservation("eval-6", "harness_only", "unresolved", None),
        CaseObservation("eval-7", "harness_only", "failed", None),
        CaseObservation("eval-8", "harness_only", "abstained", None),
        CaseObservation("eval-9", "harness_only", "selected", "logical_table"),
    )

    metrics = evaluate_workbook_ambiguity(
        truths,
        observations=observations,
        clear_sample_count=1,
        clear_unexpected_call_count=1,
    )

    assert metrics.ambiguous_case_count == 9
    assert metrics.resolvable_case_count == 7
    assert metrics.unresolvable_case_count == 2

    # Baseline: eval-2, eval-3, eval-6, eval-7 correct -> 4
    assert metrics.baseline_correct_count == 4
    assert metrics.baseline_wrong_count == 5
    assert metrics.baseline_accuracy == pytest.approx(4 / 7)

    # Model selections: eval-1 (text), eval-2 (form), eval-3 (form), eval-4 (form), eval-9 (logical_table) -> 5
    assert metrics.model_selected_count == 5
    # Model correct: eval-1 (text), eval-3 (form) -> 2
    assert metrics.model_correct_acceptance_count == 2
    # Model wrong: eval-2, eval-4, eval-9 -> 3
    assert metrics.model_wrong_acceptance_count == 3
    assert metrics.model_selection_accuracy == pytest.approx(2 / 5)
    assert metrics.wrong_acceptance_rate == pytest.approx(3 / 9)
    assert metrics.model_coverage == pytest.approx(5 / 9)

    assert metrics.model_abstained_count == 2  # eval-5, eval-8
    assert metrics.abstain_rate == pytest.approx(2 / 9)

    assert metrics.model_unresolved_count == 1  # eval-6
    assert metrics.unresolved_rate == pytest.approx(1 / 9)

    assert metrics.model_failed_count == 1  # eval-7
    assert metrics.failure_rate == pytest.approx(1 / 9)

    # Transitions
    assert metrics.fixed_error_count == 1  # eval-1
    assert metrics.introduced_error_count == 2  # eval-2, eval-9 (unresolvable wrongly selected)
    assert metrics.unchanged_correct_count == 1  # eval-3
    assert metrics.unchanged_wrong_count == 1  # eval-4
    assert metrics.net_correct_delta == 1 - 2  # -1

    assert metrics.clear_sample_count == 1
    assert metrics.clear_unexpected_call_count == 1
    assert metrics.clear_call_rate == 1.0

    # harness_only must result in effectiveness_evidence = False
    assert metrics.effectiveness_evidence is False

    # Check classify_case_evaluation helper
    d1 = classify_case_evaluation(truths[0], observations[0])
    assert d1.transition == "fixed_error"
    assert d1.baseline_correct is False

    d2 = classify_case_evaluation(truths[1], observations[1])
    assert d2.transition == "introduced_error"
    assert d2.baseline_correct is True

    d3 = classify_case_evaluation(truths[2], observations[2])
    assert d3.transition == "unchanged_correct"

    d4 = classify_case_evaluation(truths[3], observations[3])
    assert d4.transition == "unchanged_wrong"

    d5 = classify_case_evaluation(truths[4], observations[4])
    assert d5.transition == "abstained"

    d9 = classify_case_evaluation(truths[8], observations[8])
    assert d9.transition == "introduced_error"


def test_zero_denominator_null_handling():
    # Empty ambiguous cases
    metrics = evaluate_workbook_ambiguity(
        (),
        observations=(),
        clear_sample_count=0,
        clear_unexpected_call_count=0,
    )

    assert metrics.ambiguous_case_count == 0
    assert metrics.resolvable_case_count == 0
    assert metrics.unresolvable_case_count == 0
    assert metrics.baseline_accuracy is None
    assert metrics.model_selection_accuracy is None
    assert metrics.wrong_acceptance_rate is None
    assert metrics.model_coverage is None
    assert metrics.abstain_rate is None
    assert metrics.unresolved_rate is None
    assert metrics.failure_rate is None
    assert metrics.clear_call_rate is None
    assert metrics.net_correct_delta == 0


def test_reject_mismatched_observation_ids():
    truths = (CaseTruth("eval-1", "ambiguous", "text", "unclassified"),)

    # Missing ID
    with pytest.raises(InvalidGoldenSetError) as exc_info:
        evaluate_workbook_ambiguity(truths, observations=())
    assert exc_info.value.code == "evaluation_id_mismatch"


def test_reject_invalid_observation_shape_and_clear_counts():
    truth = (CaseTruth("eval-1", "ambiguous", "text", "unclassified"),)
    truths = truth

    with pytest.raises(InvalidGoldenSetError) as exc_info:
        evaluate_workbook_ambiguity(
            truth,
            observations=(CaseObservation("eval-1", "provider", "selected", None),),
        )
    assert exc_info.value.code == "invalid_observation"

    with pytest.raises(InvalidGoldenSetError) as exc_info:
        evaluate_workbook_ambiguity(
            truth,
            clear_sample_count=0,
            clear_unexpected_call_count=1,
        )
    assert exc_info.value.code == "invalid_metric_input"

    # Duplicate ID
    with pytest.raises(InvalidGoldenSetError) as exc_info:
        evaluate_workbook_ambiguity(
            truths,
            observations=(
                CaseObservation("eval-1", "harness_only", "abstained", None),
                CaseObservation("eval-1", "harness_only", "abstained", None),
            ),
        )
    assert exc_info.value.code == "duplicate_id"

    # Unknown ID
    with pytest.raises(InvalidGoldenSetError) as exc_info:
        evaluate_workbook_ambiguity(
            truths,
            observations=(CaseObservation("eval-2", "harness_only", "abstained", None),),
        )
    assert exc_info.value.code == "evaluation_id_mismatch"

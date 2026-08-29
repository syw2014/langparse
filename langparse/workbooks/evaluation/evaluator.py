from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .schema import InvalidGoldenSetError

RegionKind = Literal["logical_table", "form", "matrix", "text", "unclassified"]
_REGION_KINDS = frozenset({"logical_table", "form", "matrix", "text", "unclassified"})


@dataclass(frozen=True)
class CaseTruth:
    evaluation_id: str
    cohort: Literal["ambiguous"]
    expected_kind: RegionKind | None  # None indicates unresolvable
    baseline_kind: RegionKind | None


@dataclass(frozen=True)
class CaseObservation:
    evaluation_id: str
    evidence_class: Literal["harness_only", "provider"]
    status: Literal["selected", "abstained", "unresolved", "failed"]
    selected_kind: RegionKind | None


@dataclass(frozen=True)
class CaseEvaluationDetail:
    evaluation_id: str
    cohort: Literal["ambiguous"]
    expected_kind: RegionKind | None
    baseline_kind: RegionKind | None
    baseline_correct: bool
    observation_status: Literal["selected", "abstained", "unresolved", "failed"] | None
    observed_kind: RegionKind | None
    transition: str | None


@dataclass(frozen=True)
class WorkbookEvaluationMetrics:
    # 17 Raw counts
    ambiguous_case_count: int
    resolvable_case_count: int
    unresolvable_case_count: int
    baseline_correct_count: int
    baseline_wrong_count: int
    model_selected_count: int | None = None
    model_correct_acceptance_count: int | None = None
    model_wrong_acceptance_count: int | None = None
    model_abstained_count: int | None = None
    model_unresolved_count: int | None = None
    model_failed_count: int | None = None
    fixed_error_count: int | None = None
    introduced_error_count: int | None = None
    unchanged_correct_count: int | None = None
    unchanged_wrong_count: int | None = None
    clear_sample_count: int = 0
    clear_unexpected_call_count: int = 0

    # 9 Derived rates/deltas (None if denominator is 0)
    baseline_accuracy: float | None = None
    model_selection_accuracy: float | None = None
    wrong_acceptance_rate: float | None = None
    model_coverage: float | None = None
    abstain_rate: float | None = None
    unresolved_rate: float | None = None
    failure_rate: float | None = None
    clear_call_rate: float | None = None
    net_correct_delta: int | None = None

    # Evidence grading
    effectiveness_evidence: bool = False


def classify_case_evaluation(
    truth: CaseTruth,
    observation: CaseObservation | None,
) -> CaseEvaluationDetail:
    is_resolvable = truth.expected_kind is not None
    baseline_correct = is_resolvable and (truth.baseline_kind == truth.expected_kind)

    if observation is None:
        return CaseEvaluationDetail(
            evaluation_id=truth.evaluation_id,
            cohort=truth.cohort,
            expected_kind=truth.expected_kind,
            baseline_kind=truth.baseline_kind,
            baseline_correct=baseline_correct,
            observation_status=None,
            observed_kind=None,
            transition=None,
        )

    transition: str | None = None
    if observation.status == "selected":
        if is_resolvable:
            model_correct = observation.selected_kind == truth.expected_kind
            if not baseline_correct and model_correct:
                transition = "fixed_error"
            elif baseline_correct and not model_correct:
                transition = "introduced_error"
            elif baseline_correct and model_correct:
                transition = "unchanged_correct"
            else:
                transition = "unchanged_wrong"
        else:
            # Unresolvable truth selected by model is an introduced error / wrong acceptance
            transition = "introduced_error"
    else:
        transition = observation.status

    return CaseEvaluationDetail(
        evaluation_id=truth.evaluation_id,
        cohort=truth.cohort,
        expected_kind=truth.expected_kind,
        baseline_kind=truth.baseline_kind,
        baseline_correct=baseline_correct,
        observation_status=observation.status,
        observed_kind=observation.selected_kind,
        transition=transition,
    )


def evaluate_workbook_ambiguity(
    truths: tuple[CaseTruth, ...],
    observations: tuple[CaseObservation, ...] | None = None,
    *,
    clear_sample_count: int = 0,
    clear_unexpected_call_count: int = 0,
) -> WorkbookEvaluationMetrics:
    if (
        type(clear_sample_count) is not int
        or type(clear_unexpected_call_count) is not int
        or clear_sample_count < 0
        or clear_unexpected_call_count < 0
        or clear_unexpected_call_count > clear_sample_count
    ):
        raise InvalidGoldenSetError(
            "Clear-sample counts are inconsistent",
            code="invalid_metric_input",
        )
    truth_ids: set[str] = set()
    for truth in truths:
        if (
            not isinstance(truth, CaseTruth)
            or truth.cohort != "ambiguous"
            or truth.expected_kind not in _REGION_KINDS | {None}
            or truth.baseline_kind not in _REGION_KINDS | {None}
        ):
            raise InvalidGoldenSetError("Invalid truth shape", code="invalid_truth")
        if truth.evaluation_id in truth_ids:
            raise InvalidGoldenSetError(
                f"Duplicate truth evaluation_id: {truth.evaluation_id}",
                code="duplicate_id",
            )
        truth_ids.add(truth.evaluation_id)

    obs_by_id: dict[str, CaseObservation] = {}
    if observations is not None:
        for obs in observations:
            if (
                not isinstance(obs, CaseObservation)
                or obs.evidence_class not in {"harness_only", "provider"}
                or obs.status not in {"selected", "abstained", "unresolved", "failed"}
                or (obs.status == "selected" and obs.selected_kind not in _REGION_KINDS)
                or (obs.status != "selected" and obs.selected_kind is not None)
            ):
                raise InvalidGoldenSetError(
                    "Invalid observation shape",
                    code="invalid_observation",
                )
            if obs.evaluation_id in obs_by_id:
                raise InvalidGoldenSetError(
                    f"Duplicate observation evaluation_id: {obs.evaluation_id}",
                    code="duplicate_id",
                )
            if obs.evaluation_id not in truth_ids:
                raise InvalidGoldenSetError(
                    f"Observation evaluation_id not found in truth: {obs.evaluation_id}",
                    code="evaluation_id_mismatch",
                )
            obs_by_id[obs.evaluation_id] = obs

        if len(obs_by_id) != len(truth_ids):
            raise InvalidGoldenSetError(
                "Observations count does not match truths count",
                code="evaluation_id_mismatch",
            )

    ambiguous_case_count = len(truths)
    resolvable_case_count = 0
    unresolvable_case_count = 0
    baseline_correct_count = 0
    baseline_wrong_count = 0

    model_selected_count = 0
    model_correct_acceptance_count = 0
    model_wrong_acceptance_count = 0
    model_abstained_count = 0
    model_unresolved_count = 0
    model_failed_count = 0

    fixed_error_count = 0
    introduced_error_count = 0
    unchanged_correct_count = 0
    unchanged_wrong_count = 0

    has_observations = observations is not None
    has_provider_only_evidence = has_observations

    for truth in truths:
        is_resolvable = truth.expected_kind is not None
        if is_resolvable:
            resolvable_case_count += 1
            if truth.baseline_kind == truth.expected_kind:
                baseline_correct_count += 1
            else:
                baseline_wrong_count += 1
        else:
            unresolvable_case_count += 1
            baseline_wrong_count += 1

        if has_observations:
            obs = obs_by_id[truth.evaluation_id]
            if obs.evidence_class != "provider":
                has_provider_only_evidence = False

            if obs.status == "selected":
                model_selected_count += 1
                if is_resolvable:
                    if obs.selected_kind == truth.expected_kind:
                        model_correct_acceptance_count += 1
                        if truth.baseline_kind != truth.expected_kind:
                            fixed_error_count += 1
                        else:
                            unchanged_correct_count += 1
                    else:
                        model_wrong_acceptance_count += 1
                        if truth.baseline_kind == truth.expected_kind:
                            introduced_error_count += 1
                        else:
                            unchanged_wrong_count += 1
                else:
                    # Unresolvable truth selected is wrong acceptance
                    model_wrong_acceptance_count += 1
                    introduced_error_count += 1
            elif obs.status == "abstained":
                model_abstained_count += 1
            elif obs.status == "unresolved":
                model_unresolved_count += 1
            elif obs.status == "failed":
                model_failed_count += 1

    # Calculate derived metrics (null if denominator is 0)
    baseline_accuracy = (
        baseline_correct_count / resolvable_case_count if resolvable_case_count > 0 else None
    )

    if has_observations:
        model_selection_accuracy = (
            model_correct_acceptance_count / model_selected_count
            if model_selected_count > 0
            else None
        )
        wrong_acceptance_rate = (
            model_wrong_acceptance_count / ambiguous_case_count
            if ambiguous_case_count > 0
            else None
        )
        model_coverage = (
            model_selected_count / ambiguous_case_count if ambiguous_case_count > 0 else None
        )
        abstain_rate = (
            model_abstained_count / ambiguous_case_count if ambiguous_case_count > 0 else None
        )
        unresolved_rate = (
            model_unresolved_count / ambiguous_case_count if ambiguous_case_count > 0 else None
        )
        failure_rate = (
            model_failed_count / ambiguous_case_count if ambiguous_case_count > 0 else None
        )
        net_correct_delta = fixed_error_count - introduced_error_count
        effectiveness_evidence = has_provider_only_evidence
    else:
        model_selection_accuracy = None
        wrong_acceptance_rate = None
        model_coverage = None
        abstain_rate = None
        unresolved_rate = None
        failure_rate = None
        net_correct_delta = None
        effectiveness_evidence = False

    clear_call_rate = (
        clear_unexpected_call_count / clear_sample_count if clear_sample_count > 0 else None
    )

    return WorkbookEvaluationMetrics(
        ambiguous_case_count=ambiguous_case_count,
        resolvable_case_count=resolvable_case_count,
        unresolvable_case_count=unresolvable_case_count,
        baseline_correct_count=baseline_correct_count,
        baseline_wrong_count=baseline_wrong_count,
        baseline_accuracy=baseline_accuracy,
        model_selected_count=model_selected_count,
        model_correct_acceptance_count=model_correct_acceptance_count,
        model_wrong_acceptance_count=model_wrong_acceptance_count,
        model_abstained_count=model_abstained_count,
        model_unresolved_count=model_unresolved_count,
        model_failed_count=model_failed_count,
        model_selection_accuracy=model_selection_accuracy,
        wrong_acceptance_rate=wrong_acceptance_rate,
        model_coverage=model_coverage,
        abstain_rate=abstain_rate,
        unresolved_rate=unresolved_rate,
        failure_rate=failure_rate,
        fixed_error_count=fixed_error_count,
        introduced_error_count=introduced_error_count,
        unchanged_correct_count=unchanged_correct_count,
        unchanged_wrong_count=unchanged_wrong_count,
        net_correct_delta=net_correct_delta,
        clear_sample_count=clear_sample_count,
        clear_unexpected_call_count=clear_unexpected_call_count,
        clear_call_rate=clear_call_rate,
        effectiveness_evidence=effectiveness_evidence,
    )


def assess_production_readiness(
    metrics: WorkbookEvaluationMetrics,
    *,
    split: str | None = None,
    operational_evidence: bool = False,
    minimum_ambiguous_cases: int = 30,
) -> tuple[bool, tuple[str, ...]]:
    """Assess whether evaluation metrics satisfy production rollout criteria.

    All gates are unconditional: omitting ``split`` or ``operational_evidence``
    defaults to the conservative (blocking) position.
    """
    reasons: list[str] = []

    # Gate 1: holdout split required (tuning / None / unknown all fail)
    if split != "holdout":
        reasons.append("holdout_evidence_required")

    # Gate 2: minimum sample size
    if metrics.ambiguous_case_count < minimum_ambiguous_cases:
        reasons.append("minimum_ambiguous_cases_not_met")

    # Gate 3: operational staging evidence
    if not operational_evidence:
        reasons.append("operational_evidence_missing")

    # Gate 4: provider effectiveness evidence
    if not metrics.effectiveness_evidence:
        reasons.append("effectiveness_evidence_missing")

    # Gate 5: net improvement
    if metrics.net_correct_delta is None or metrics.net_correct_delta <= 0:
        reasons.append("net_correct_delta_non_positive")

    # Gate 6: wrong acceptance threshold
    if metrics.wrong_acceptance_rate is not None and metrics.wrong_acceptance_rate > 0.05:
        reasons.append("wrong_acceptance_rate_exceeds_threshold")

    # Gate 7: clear samples must not trigger model calls
    if metrics.clear_call_rate is not None and metrics.clear_call_rate > 0.0:
        reasons.append("clear_sample_unexpected_calls")

    # Gate 8: introduced errors must be fewer than fixed
    if (
        metrics.fixed_error_count is not None
        and metrics.introduced_error_count is not None
        and metrics.introduced_error_count >= metrics.fixed_error_count
    ):
        reasons.append("introduced_errors_exceed_fixed_errors")

    is_ready = len(reasons) == 0
    return is_ready, tuple(reasons)

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from langparse.workbooks.adapters import OOXMLWorkbookAdapter
from langparse.workbooks.assembly import assemble_workbook
from langparse.workbooks.evaluation.evaluator import (
    CaseEvaluationDetail,
    CaseObservation,
    CaseTruth,
    WorkbookEvaluationMetrics,
    assess_production_readiness,
    classify_case_evaluation,
    evaluate_workbook_ambiguity,
)
from langparse.workbooks.evaluation.schema import (
    GoldenSetDriftError,
    WorkbookEvaluationError,
    compute_choices_digest,
    compute_evaluation_id,
    load_golden_set_manifest,
    validate_output_dir_isolation,
)
from langparse.workbooks.modeling.policy import WorkbookDisambiguation
from langparse.workbooks.modeling.ports import WorkbookStructureModelAdapter
from langparse.workbooks.modeling.types import (
    REGION_PRIVACY_VERSION,
    REGION_PROMPT_VERSION,
    REGION_RULE_VERSION,
    REGION_SCHEMA_VERSION,
    REGION_VALIDATOR_VERSION,
    ModelIdentity,
    ProviderReply,
    RegionChoice,
    WorkbookModelRequest,
)


@dataclass(frozen=True)
class _CapturedCase:
    case_id: str
    sheet_name: str
    source_range: str
    fact_digest: str
    fallback_choice_id: str
    choices: tuple[RegionChoice, ...]


class _EvaluationCaptureAdapter(WorkbookStructureModelAdapter):
    """Zero-network in-memory capture adapter for golden set evaluation."""

    def __init__(self) -> None:
        self.captured_cases: list[_CapturedCase] = []
        self._identity = ModelIdentity(
            provider="evaluation",
            model="capture",
            revision="1",
        )

    @property
    def identity(self) -> ModelIdentity:
        return self._identity

    def complete(
        self,
        request: WorkbookModelRequest,
        *,
        timeout_seconds: float,
    ) -> ProviderReply:
        payload = json.loads(request.body.decode("utf-8"))
        for raw_case in payload.get("cases", []):
            choices = tuple(
                RegionChoice(
                    choice_id=c["choice_id"],
                    kind=c["kind"],
                    local_score=float(c["local_score"]),
                    reason_codes=tuple(c["reason_codes"]),
                )
                for c in raw_case["choices"]
            )
            self.captured_cases.append(
                _CapturedCase(
                    case_id=raw_case["case_id"],
                    sheet_name=raw_case["sheet_name"],
                    source_range=raw_case["source_range"],
                    fact_digest=raw_case["fact_digest"],
                    fallback_choice_id=raw_case["fallback_choice_id"],
                    choices=choices,
                )
            )

        decisions = [
            {
                "case_id": case_id,
                "status": "abstained",
                "confidence": 0.0,
                "reason_codes": ["evaluation_capture"],
            }
            for case_id in request.case_ids
        ]
        reply_dict = {
            "schema_version": request.schema_version,
            "request_checksum": request.request_checksum,
            "decisions": decisions,
        }
        reply_bytes = json.dumps(reply_dict, separators=(",", ":")).encode("utf-8")
        return ProviderReply(
            body=reply_bytes,
            provider_request_id="eval-capture",
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )


_UNRESOLVED_AUDIT_OUTCOMES = frozenset(
    {
        "case_limit_exceeded",
        "case_unavailable",
        "cell_limit_exceeded",
        "hidden_sheet",
        "kill_switch_activated",
        "limit_exceeded",
        "quota_exceeded",
        "request_too_large",
    }
)


def _observation_from_final_audit(
    case: _CapturedCase,
    audit: dict[str, object] | None,
) -> tuple[str, str | None]:
    """Translate only the production assembly's final audit into evaluation evidence."""

    if audit is None:
        return "unresolved", None
    outcome = audit.get("outcome")
    if outcome == "accepted":
        selected_choice_id = audit.get("selected_choice_id")
        selected_kind = next(
            (choice.kind for choice in case.choices if choice.choice_id == selected_choice_id),
            None,
        )
        return ("selected", selected_kind) if selected_kind is not None else ("failed", None)
    if outcome == "abstained":
        return "abstained", None
    if outcome in _UNRESOLVED_AUDIT_OUTCOMES:
        return "unresolved", None
    return "failed", None


@dataclass(frozen=True)
class WorkbookEvaluationReport:
    run_digest: str
    output_path: Path
    metrics: WorkbookEvaluationMetrics
    results: tuple[CaseEvaluationDetail, ...]
    summary: dict[str, Any]


def _compute_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return f"sha256:{hasher.hexdigest()}"


def _get_stat_tuple(path: Path) -> os.stat_result:
    return path.stat()


def _render_summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        f"# Workbook Ambiguity Evaluation Summary ({summary['dataset_id']})",
        "",
        f"- **Dataset Version**: {summary['dataset_version']}",
        f"- **Split**: {summary['split']}",
        f"- **Status**: {summary['status']}",
        f"- **Effectiveness Evidence**: {summary['effectiveness_evidence']}",
        f"- **Production Ready**: {summary.get('production_ready', False)}",
        f"- **Verdict Reasons**: {', '.join(summary.get('verdict_reasons', [])) or 'none'}",
        f"- **Run Digest**: `{summary['run_digest']}`",
        f"- **Dataset Digest**: `{summary['dataset_digest']}`",
        f"- **Model Prompt Version**: `{summary['model_contract']['prompt_version']}`",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "| :--- | :--- |",
        f"| Ambiguous Cases | {summary['ambiguous_case_count']} |",
        f"| Resolvable Cases | {summary['resolvable_case_count']} |",
        f"| Baseline Correct | {summary['baseline_correct_count']} |",
        f"| Baseline Wrong | {summary['baseline_wrong_count']} |",
        f"| Baseline Accuracy | {summary['baseline_accuracy']} |",
        f"| Model Selected | {summary['model_selected_count']} |",
        f"| Model Correct Acceptance | {summary['model_correct_acceptance_count']} |",
        f"| Model Wrong Acceptance | {summary['model_wrong_acceptance_count']} |",
        f"| Model Selection Accuracy | {summary['model_selection_accuracy']} |",
        f"| Wrong Acceptance Rate | {summary['wrong_acceptance_rate']} |",
        f"| Model Coverage | {summary['model_coverage']} |",
        f"| Fixed Errors | {summary['fixed_error_count']} |",
        f"| Introduced Errors | {summary['introduced_error_count']} |",
        f"| Net Correct Delta | {summary['net_correct_delta']} |",
        f"| Clear Samples | {summary['clear_sample_count']} |",
        f"| Clear Unexpected Calls | {summary['clear_unexpected_call_count']} |",
        f"| Clear Call Rate | {summary['clear_call_rate']} |",
        "",
    ]
    return "\n".join(lines)


def _report_directories_match(existing: Path, candidate: Path) -> bool:
    existing_files = {
        path.relative_to(existing): path
        for path in existing.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    candidate_files = {
        path.relative_to(candidate): path
        for path in candidate.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    if existing_files.keys() != candidate_files.keys():
        return False
    return all(
        existing_files[relative].read_bytes() == candidate_files[relative].read_bytes()
        for relative in existing_files
    )


def _safe_model_identity_payload(
    adapter: WorkbookStructureModelAdapter | None,
) -> dict[str, str | None] | None:
    if adapter is None:
        return None
    identity = adapter.identity
    if not isinstance(identity, ModelIdentity):
        return None
    values = (identity.provider, identity.model, identity.revision)
    if any(
        value is not None
        and (
            type(value) is not str
            or not 0 < len(value) <= 64
            or not value.isascii()
            or not all(character.isalnum() or character in "._-/" for character in value)
        )
        for value in values
    ):
        return None
    return {
        "provider": identity.provider,
        "model": identity.model,
        "revision": identity.revision,
    }


class WorkbookAmbiguityBenchmarkService:
    """Service to evaluate workbook model disambiguation against golden set baselines."""

    def __init__(self, adapter: OOXMLWorkbookAdapter | None = None) -> None:
        self._ooxml_adapter = adapter or OOXMLWorkbookAdapter()

    def run(
        self,
        manifest_path: str | Path,
        *,
        output_dir: str | Path,
        markdown: bool = True,
        adapter: WorkbookStructureModelAdapter | None = None,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> WorkbookEvaluationReport:
        manifest = load_golden_set_manifest(manifest_path)
        output_dir_path = Path(output_dir).resolve()
        validate_output_dir_isolation(manifest.source_root, output_dir_path)

        from langparse.workbooks.modeling.openai_adapter import (
            OpenAIWorkbookStructureAdapter,
        )

        if adapter is None and model is not None:
            adapter = OpenAIWorkbookStructureAdapter.from_env(
                cli_model=model,
                cli_api_key=api_key,
                cli_base_url=base_url,
            )

        provider_evidence = type(adapter) is OpenAIWorkbookStructureAdapter

        # Pre-execution stat and hash check
        initial_stats: dict[str, tuple[os.stat_result, str]] = {}
        for sample in manifest.samples:
            full_path = (manifest.source_root / sample.path).resolve()
            initial_stats[sample.sample_id] = (
                _get_stat_tuple(full_path),
                _compute_sha256(full_path),
            )

        truths: list[CaseTruth] = []
        observations: list[CaseObservation] = [] if adapter is not None else None
        clear_sample_count = 0
        clear_unexpected_call_count = 0

        for sample in manifest.samples:
            full_path = (manifest.source_root / sample.path).resolve()
            capture_adapter = _EvaluationCaptureAdapter()
            snapshot = self._ooxml_adapter.snapshot(full_path)
            assemble_workbook(
                snapshot,
                disambiguation=WorkbookDisambiguation.auto(capture_adapter),
            )

            if sample.cohort == "clear_no_call":
                clear_sample_count += 1
                if len(capture_adapter.captured_cases) > 0:
                    clear_unexpected_call_count += 1
                continue

            # ambiguous cohort matching
            runtime_cases_by_loc = {
                (c.sheet_name, c.source_range): c for c in capture_adapter.captured_cases
            }
            manifest_cases_by_loc = {(c.sheet_name, c.source_range): c for c in sample.cases}

            # Drift checks
            missing_locs = set(manifest_cases_by_loc.keys()) - set(runtime_cases_by_loc.keys())
            if missing_locs:
                raise GoldenSetDriftError(
                    "Runtime case missing from snapshot",
                    code="case_missing",
                )

            unlabeled_locs = set(runtime_cases_by_loc.keys()) - set(manifest_cases_by_loc.keys())
            if unlabeled_locs:
                raise GoldenSetDriftError(
                    "Runtime generated unlabeled ambiguity case",
                    code="case_unlabeled",
                )

            for loc, golden_case in manifest_cases_by_loc.items():
                runtime_case = runtime_cases_by_loc[loc]
                if runtime_case.fact_digest != golden_case.fact_digest:
                    raise GoldenSetDriftError(
                        "Case fact digest changed",
                        code="facts_changed",
                    )

                runtime_choices_digest = compute_choices_digest(runtime_case.choices)
                if runtime_choices_digest != golden_case.choices_digest:
                    raise GoldenSetDriftError(
                        "Case choices digest changed",
                        code="choices_changed",
                    )

                # Extract baseline kind from fallback choice
                fallback_choice = next(
                    (
                        c
                        for c in runtime_case.choices
                        if c.choice_id == runtime_case.fallback_choice_id
                    ),
                    None,
                )
                baseline_kind = fallback_choice.kind if fallback_choice is not None else None

                expected_kind = (
                    None if golden_case.expected == "unresolvable" else golden_case.expected
                )
                eval_id = compute_evaluation_id(
                    manifest.dataset_id,
                    manifest.dataset_version,
                    sample.sample_id,
                    golden_case.label_id,
                )
                truths.append(
                    CaseTruth(
                        evaluation_id=eval_id,
                        cohort="ambiguous",
                        expected_kind=expected_kind,
                        baseline_kind=baseline_kind,
                    )
                )

            # If adapter provided, run live observation pass
            if adapter is not None:
                _, live_diagnostics = assemble_workbook(
                    snapshot,
                    disambiguation=WorkbookDisambiguation.auto(adapter),
                )
                audits_by_case_id = {
                    audit["case_id"]: audit
                    for audit in live_diagnostics.model_calls
                    if isinstance(audit.get("case_id"), str)
                }
                for loc, golden_case in manifest_cases_by_loc.items():
                    runtime_case = runtime_cases_by_loc[loc]
                    eval_id = compute_evaluation_id(
                        manifest.dataset_id,
                        manifest.dataset_version,
                        sample.sample_id,
                        golden_case.label_id,
                    )
                    status, selected_kind = _observation_from_final_audit(
                        runtime_case,
                        audits_by_case_id.get(runtime_case.case_id),
                    )
                    observations.append(
                        CaseObservation(
                            evaluation_id=eval_id,
                            evidence_class="provider" if provider_evidence else "harness_only",
                            status=status,
                            selected_kind=selected_kind,
                        )
                    )

        # Post-execution stat and hash verification
        for sample in manifest.samples:
            full_path = (manifest.source_root / sample.path).resolve()
            current_stat = _get_stat_tuple(full_path)
            current_hash = _compute_sha256(full_path)
            initial_stat, initial_hash = initial_stats[sample.sample_id]
            if current_stat != initial_stat or current_hash != initial_hash:
                raise GoldenSetDriftError(
                    "Source file mutated during evaluation execution",
                    code="source_file_mutated",
                )

        metrics = evaluate_workbook_ambiguity(
            tuple(truths),
            observations=tuple(observations) if observations is not None else None,
            clear_sample_count=clear_sample_count,
            clear_unexpected_call_count=clear_unexpected_call_count,
        )

        if observations is not None:
            obs_map = {o.evaluation_id: o for o in observations}
            results = tuple(
                classify_case_evaluation(truth, obs_map[truth.evaluation_id]) for truth in truths
            )
            evidence_class = "provider" if metrics.effectiveness_evidence else "harness_only"
        else:
            results = tuple(classify_case_evaluation(truth, None) for truth in truths)
            evidence_class = "none"

        # Compute deterministic run digest
        model_identity = _safe_model_identity_payload(adapter)
        model_contract = {
            "schema_version": REGION_SCHEMA_VERSION,
            "prompt_version": REGION_PROMPT_VERSION,
            "privacy_version": REGION_PRIVACY_VERSION,
            "rule_version": REGION_RULE_VERSION,
            "validator_version": REGION_VALIDATOR_VERSION,
        }
        run_payload = {
            "dataset_digest": manifest.dataset_digest,
            "evidence_class": evidence_class,
            "model_identity": model_identity,
            "model_contract": model_contract,
            "metrics": asdict(metrics),
            "results": [asdict(r) for r in results],
        }
        serialized_run = json.dumps(run_payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        run_digest = f"sha256:{hashlib.sha256(serialized_run).hexdigest()}"

        production_ready, verdict_reasons = assess_production_readiness(
            metrics,
            split=manifest.split,
            operational_evidence=False,
        )
        summary_dict = {
            "schema_version": 1,
            "dataset_id": manifest.dataset_id,
            "dataset_version": manifest.dataset_version,
            "split": manifest.split,
            "dataset_digest": manifest.dataset_digest,
            "run_digest": run_digest,
            "status": "valid",
            "effectiveness_evidence": metrics.effectiveness_evidence,
            "model_identity": model_identity,
            "model_contract": model_contract,
            "production_ready": production_ready,
            "verdict_reasons": list(verdict_reasons),
            **asdict(metrics),
        }

        # Atomic publishing
        output_dir_path.mkdir(parents=True, exist_ok=True)
        tmp_run_dir = output_dir_path / f".tmp-{uuid.uuid4().hex}"
        tmp_run_dir.mkdir(parents=True, exist_ok=False)

        try:
            # Write results.jsonl (sanitized rows)
            results_path = tmp_run_dir / "workbook-ambiguity-results.jsonl"
            with results_path.open("w", encoding="utf-8") as f:
                for res in results:
                    row = {
                        "run_digest": run_digest,
                        "evaluation_id": res.evaluation_id,
                        "cohort": res.cohort,
                        "expected_kind": res.expected_kind,
                        "baseline_kind": res.baseline_kind,
                        "baseline_correct": res.baseline_correct,
                        "observation_status": res.observation_status,
                        "observed_kind": res.observed_kind,
                        "transition": res.transition,
                    }
                    f.write(json.dumps(row, separators=(",", ":")) + "\n")

            # Write summary.json
            summary_path = tmp_run_dir / "workbook-ambiguity-summary.json"
            summary_path.write_text(
                json.dumps(summary_dict, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            # Write summary.md if requested
            if markdown:
                summary_md_path = tmp_run_dir / "workbook-ambiguity-summary.md"
                summary_md_path.write_text(
                    _render_summary_markdown(summary_dict),
                    encoding="utf-8",
                )

            final_run_dir = output_dir_path / run_digest.removeprefix("sha256:")

            if final_run_dir.exists():
                if _report_directories_match(final_run_dir, tmp_run_dir):
                    shutil.rmtree(tmp_run_dir, ignore_errors=True)
                    return WorkbookEvaluationReport(
                        run_digest=run_digest,
                        output_path=final_run_dir,
                        metrics=metrics,
                        results=results,
                        summary=summary_dict,
                    )
                shutil.rmtree(tmp_run_dir, ignore_errors=True)
                raise WorkbookEvaluationError(
                    "Output run directory conflict with different content",
                    code="report_conflict",
                )

            os.replace(tmp_run_dir, final_run_dir)
            return WorkbookEvaluationReport(
                run_digest=run_digest,
                output_path=final_run_dir,
                metrics=metrics,
                results=results,
                summary=summary_dict,
            )
        except Exception:
            shutil.rmtree(tmp_run_dir, ignore_errors=True)
            raise

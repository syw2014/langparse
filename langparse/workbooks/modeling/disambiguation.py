from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import fields
from threading import RLock

from langparse.types import ParseDiagnostics

from .cache import MemoryDecisionCache
from .contract import (
    _copy_provider_reply,
    _validate_case,
    _validate_model_identity,
    build_model_request,
    decode_model_reply,
    response_checksum,
)
from .policy import WorkbookDisambiguation
from .ports import (
    RequiredWorkbookDisambiguationError,
    WorkbookModelResponseError,
    WorkbookStructureModelAdapter,
)
from .types import (
    ModelCallAudit,
    ModelIdentity,
    ProviderReply,
    RegionAmbiguityCase,
    RegionModelDecision,
    RegionResolution,
    RegionResolutionBatch,
    WorkbookModelMode,
    WorkbookModelPolicy,
    WorkbookModelRequest,
)


class WorkbookRegionDisambiguator:
    """Resolve workbook region ambiguity behind the local model contract."""

    def __init__(
        self,
        cache: MemoryDecisionCache | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._cache = MemoryDecisionCache() if cache is None else cache
        self._clock = clock
        self._resolve_lock = RLock()

    def resolve(
        self,
        cases: Iterable[RegionAmbiguityCase],
        configured: WorkbookDisambiguation,
    ) -> RegionResolutionBatch:
        with self._resolve_lock:
            return self._resolve(cases, configured)

    def _resolve(
        self,
        cases: Iterable[RegionAmbiguityCase],
        configured: WorkbookDisambiguation,
    ) -> RegionResolutionBatch:
        ordered_cases = tuple(cases)
        if not ordered_cases:
            return RegionResolutionBatch(resolutions=())

        self._validate_cases(ordered_cases)
        if configured.mode is WorkbookModelMode.OFF:
            return RegionResolutionBatch(
                resolutions=tuple(_fallback_resolution(case) for case in ordered_cases)
            )

        policy = configured.policy
        visible_limit = policy.max_cases
        eligible_visible_cases = tuple(
            case
            for index, case in enumerate(_visible_cases(ordered_cases))
            if index < visible_limit
        )
        identity, identity_error = self._read_identity(configured, eligible_visible_cases)
        adapter = configured.adapter
        workbook_started = self._clock() if eligible_visible_cases else None
        deadline = (
            workbook_started + policy.workbook_timeout_seconds
            if workbook_started is not None
            else None
        )

        resolutions: list[RegionResolution] = []
        audits: list[ModelCallAudit] = []
        unresolved_case_ids: list[str] = []
        call_budget = [0]
        visible_index = 0
        for case in ordered_cases:
            if case.sheet_visibility != "visible":
                resolution, audit = self._local_failure(
                    case,
                    configured.mode,
                    outcome="hidden_sheet",
                )
            elif visible_index >= visible_limit:
                resolution, audit = self._local_failure(
                    case,
                    configured.mode,
                    identity=identity,
                    outcome="limit_exceeded",
                )
                visible_index += 1
            elif identity_error is not None:
                resolution, audit = self._local_failure(
                    case,
                    configured.mode,
                    outcome="adapter_error",
                    error=identity_error,
                    elapsed_ms=self._elapsed_ms(workbook_started),
                )
                visible_index += 1
            else:
                assert identity is not None
                assert deadline is not None
                assert adapter is not None
                resolution, audit = self._resolve_visible_case(
                    case,
                    configured.mode,
                    adapter,
                    identity,
                    policy,
                    workbook_started,
                    deadline,
                    call_budget,
                )
                visible_index += 1

            resolutions.append(resolution)
            audits.append(audit)
            if (
                configured.mode is WorkbookModelMode.REQUIRED
                and resolution.status == "local_fallback"
            ):
                unresolved_case_ids.append(case.case_id)

        if unresolved_case_ids:
            raise RequiredWorkbookDisambiguationError(
                tuple(unresolved_case_ids),
                ParseDiagnostics(
                    status="failed",
                    model_calls=[_audit_payload(audit) for audit in audits],
                ),
            )
        return RegionResolutionBatch(resolutions=tuple(resolutions))

    def _validate_cases(self, cases: tuple[RegionAmbiguityCase, ...]) -> None:
        for case in cases:
            _validate_case(case, allow_hidden_sheet=True)

    def _read_identity(
        self,
        configured: WorkbookDisambiguation,
        eligible_visible_cases: tuple[RegionAmbiguityCase, ...],
    ) -> tuple[ModelIdentity | None, Exception | None]:
        if not eligible_visible_cases:
            return None, None
        assert configured.adapter is not None
        try:
            identity = configured.adapter.identity
            _validate_model_identity(identity)
            return identity, None
        except Exception as error:
            return None, error

    def _resolve_visible_case(
        self,
        case: RegionAmbiguityCase,
        mode: WorkbookModelMode,
        adapter: WorkbookStructureModelAdapter,
        identity: ModelIdentity,
        policy: WorkbookModelPolicy,
        workbook_started: float | None,
        deadline: float,
        call_budget: list[int],
    ) -> tuple[RegionResolution, ModelCallAudit]:
        if len(case.cells) > policy.max_cells_per_case:
            return self._local_failure(
                case,
                mode,
                identity=identity,
                outcome="cell_limit_exceeded",
                elapsed_ms=self._elapsed_ms(workbook_started),
            )

        try:
            request = build_model_request(case, identity)
        except Exception as error:
            return self._local_failure(
                case,
                mode,
                identity=identity,
                outcome="request_error",
                error=error,
                elapsed_ms=self._elapsed_ms(workbook_started),
            )
        request_bytes = len(request.body)
        if request_bytes > policy.max_request_bytes:
            return self._local_failure(
                case,
                mode,
                identity=identity,
                request=request,
                request_bytes=request_bytes,
                outcome="request_too_large",
                elapsed_ms=self._elapsed_ms(workbook_started),
            )

        try:
            cached_body = self._cache.get(request.request_checksum)
        except Exception as error:
            return self._local_failure(
                case,
                mode,
                identity=identity,
                request=request,
                request_bytes=request_bytes,
                cache_status="error",
                outcome="cache_error",
                error=error,
                elapsed_ms=self._elapsed_ms(workbook_started),
            )
        if cached_body is not None:
            return self._resolve_cached(
                case,
                mode,
                identity,
                request,
                cached_body,
                policy,
                workbook_started,
            )
        return self._call_adapter(
            case,
            mode,
            adapter,
            identity,
            request,
            policy,
            workbook_started,
            deadline,
            call_budget,
        )

    def _resolve_cached(
        self,
        case: RegionAmbiguityCase,
        mode: WorkbookModelMode,
        identity: ModelIdentity,
        request: WorkbookModelRequest,
        cached_body: bytes,
        policy: WorkbookModelPolicy,
        workbook_started: float | None,
    ) -> tuple[RegionResolution, ModelCallAudit]:
        try:
            reply = ProviderReply(body=cached_body, provider_request_id=None)
            decision = decode_model_reply(
                reply,
                request,
                max_response_bytes=policy.max_response_bytes,
            )
        except Exception as error:
            safe_cached_body = cached_body if type(cached_body) is bytes else None
            return self._local_failure(
                case,
                mode,
                identity=identity,
                request=request,
                request_bytes=len(request.body),
                response_body=safe_cached_body,
                cache_status="corrupt",
                outcome="invalid_response",
                error=error,
                elapsed_ms=self._elapsed_ms(workbook_started),
            )
        return self._decision_result(
            case,
            mode,
            identity,
            request,
            cached_body,
            decision,
            cache_status="hit",
            attempts=0,
            elapsed_ms=self._elapsed_ms(workbook_started),
        )

    def _call_adapter(
        self,
        case: RegionAmbiguityCase,
        mode: WorkbookModelMode,
        adapter: WorkbookStructureModelAdapter,
        identity: ModelIdentity,
        request: WorkbookModelRequest,
        policy: WorkbookModelPolicy,
        workbook_started: float | None,
        deadline: float,
        call_budget: list[int],
    ) -> tuple[RegionResolution, ModelCallAudit]:
        attempts = 0
        last_error: Exception | None = None
        last_body: bytes | None = None
        assert mode is not WorkbookModelMode.OFF

        while attempts < policy.max_attempts:
            remaining = deadline - self._clock()
            if remaining <= 0:
                return self._local_failure(
                    case,
                    mode,
                    identity=identity,
                    request=request,
                    request_bytes=len(request.body),
                    response_body=last_body,
                    cache_status="miss",
                    attempts=attempts,
                    outcome="deadline_exceeded",
                    error=last_error,
                    elapsed_ms=self._elapsed_ms(workbook_started),
                )
            if call_budget[0] >= policy.max_calls:
                return self._local_failure(
                    case,
                    mode,
                    identity=identity,
                    request=request,
                    request_bytes=len(request.body),
                    response_body=last_body,
                    cache_status="miss",
                    attempts=attempts,
                    outcome="limit_exceeded",
                    error=last_error,
                    elapsed_ms=self._elapsed_ms(workbook_started),
                )
            attempts += 1
            call_budget[0] += 1
            try:
                reply = _copy_provider_reply(
                    adapter.complete(
                        request,
                        timeout_seconds=min(policy.timeout_seconds, remaining),
                    )
                )
                if self._clock() >= deadline:
                    return self._local_failure(
                        case,
                        mode,
                        identity=identity,
                        request=request,
                        request_bytes=len(request.body),
                        cache_status="miss",
                        attempts=attempts,
                        outcome="deadline_exceeded",
                        error=TimeoutError(),
                        elapsed_ms=self._elapsed_ms(workbook_started),
                    )
                last_body = reply.body
                decision = decode_model_reply(
                    reply,
                    request,
                    max_response_bytes=policy.max_response_bytes,
                )
            except Exception as error:
                last_error = error
                continue

            try:
                response_checksum(reply.body)
            except Exception as error:
                return self._local_failure(
                    case,
                    mode,
                    identity=identity,
                    request=request,
                    request_bytes=len(request.body),
                    response_body=reply.body,
                    cache_status="miss",
                    attempts=attempts,
                    outcome="checksum_error",
                    error=error,
                    elapsed_ms=self._elapsed_ms(workbook_started),
                )
            try:
                self._cache.put(request.request_checksum, reply.body)
            except Exception as error:
                return self._local_failure(
                    case,
                    mode,
                    identity=identity,
                    request=request,
                    request_bytes=len(request.body),
                    response_body=reply.body,
                    cache_status="error",
                    attempts=attempts,
                    outcome="cache_error",
                    error=error,
                    elapsed_ms=self._elapsed_ms(workbook_started),
                )
            return self._decision_result(
                case,
                mode,
                identity,
                request,
                reply.body,
                decision,
                cache_status="miss",
                attempts=attempts,
                elapsed_ms=self._elapsed_ms(workbook_started),
            )

        outcome = "timeout" if isinstance(last_error, TimeoutError) else "invalid_response"
        if last_error is not None and not _is_response_error(last_error):
            outcome = "timeout" if isinstance(last_error, TimeoutError) else "adapter_error"
        return self._local_failure(
            case,
            mode,
            identity=identity,
            request=request,
            request_bytes=len(request.body),
            response_body=last_body,
            cache_status="miss",
            attempts=attempts,
            outcome=outcome,
            error=last_error,
            elapsed_ms=self._elapsed_ms(workbook_started),
        )

    def _decision_result(
        self,
        case: RegionAmbiguityCase,
        mode: WorkbookModelMode,
        identity: ModelIdentity,
        request: WorkbookModelRequest,
        response_body: bytes,
        decision: RegionModelDecision,
        *,
        cache_status: str,
        attempts: int,
        elapsed_ms: int,
    ) -> tuple[RegionResolution, ModelCallAudit]:
        try:
            response_checksum(response_body)
        except Exception as error:
            return self._local_failure(
                case,
                mode,
                identity=identity,
                request=request,
                request_bytes=len(request.body),
                response_body=response_body,
                cache_status=cache_status,
                attempts=attempts,
                outcome="checksum_error",
                error=error,
                elapsed_ms=elapsed_ms,
            )
        if decision.status == "abstained":
            return self._local_failure(
                case,
                mode,
                identity=identity,
                request=request,
                request_bytes=len(request.body),
                response_body=response_body,
                cache_status=cache_status,
                attempts=attempts,
                outcome="abstained",
                reported_confidence=decision.reported_confidence,
                elapsed_ms=elapsed_ms,
            )

        assert decision.choice_id is not None
        audit = _audit(
            case,
            identity=identity,
            request=request,
            request_bytes=len(request.body),
            response_body=response_body,
            cache_status=cache_status,
            attempts=attempts,
            outcome="selected",
            selected_choice_id=decision.choice_id,
            reported_confidence=decision.reported_confidence,
            elapsed_ms=elapsed_ms,
            mode=mode,
        )
        status = "cache_selected" if cache_status == "hit" else "model_selected"
        return (
            RegionResolution(
                case_id=case.case_id,
                choice_id=decision.choice_id,
                status=status,
                audit=audit,
            ),
            audit,
        )

    def _local_failure(
        self,
        case: RegionAmbiguityCase,
        mode: WorkbookModelMode,
        *,
        identity: ModelIdentity | None = None,
        request: WorkbookModelRequest | None = None,
        request_bytes: int = 0,
        response_body: bytes | None = None,
        cache_status: str = "not_checked",
        attempts: int = 0,
        elapsed_ms: int = 0,
        outcome: str,
        selected_choice_id: str | None = None,
        reported_confidence: float | None = None,
        error: Exception | None = None,
    ) -> tuple[RegionResolution, ModelCallAudit]:
        audit = _audit(
            case,
            identity=identity,
            request=request,
            request_bytes=request_bytes,
            response_body=response_body,
            cache_status=cache_status,
            attempts=attempts,
            elapsed_ms=elapsed_ms,
            outcome=outcome,
            selected_choice_id=selected_choice_id,
            reported_confidence=reported_confidence,
            error=error,
            mode=mode,
        )
        return _fallback_resolution(case, audit), audit

    def _elapsed_ms(self, workbook_started: float | None) -> int:
        if workbook_started is None:
            return 0
        return max(0, int(round((self._clock() - workbook_started) * 1000)))


def _visible_cases(
    cases: tuple[RegionAmbiguityCase, ...],
) -> Iterable[RegionAmbiguityCase]:
    return (case for case in cases if case.sheet_visibility == "visible")


def _fallback_resolution(
    case: RegionAmbiguityCase,
    audit: ModelCallAudit | None = None,
) -> RegionResolution:
    return RegionResolution(
        case_id=case.case_id,
        choice_id=case.fallback_choice_id,
        status="local_fallback",
        audit=audit,
    )


def _audit(
    case: RegionAmbiguityCase,
    *,
    mode: WorkbookModelMode,
    identity: ModelIdentity | None,
    request: WorkbookModelRequest | None,
    request_bytes: int,
    response_body: bytes | None,
    cache_status: str,
    attempts: int,
    elapsed_ms: int,
    outcome: str,
    selected_choice_id: str | None = None,
    reported_confidence: float | None = None,
    error: Exception | None = None,
) -> ModelCallAudit:
    provider, provider_redacted = _safe_identity_token(
        identity.provider if identity is not None else None,
        required=identity is not None,
    )
    model, model_redacted = _safe_identity_token(
        identity.model if identity is not None else None,
        required=identity is not None,
    )
    model_revision, revision_redacted = _safe_identity_token(
        identity.revision if identity is not None else None,
        required=False,
    )
    validation_codes = []
    if provider_redacted or model_redacted or revision_redacted:
        validation_codes.append("unsafe_identity_redacted")
    checksum = None
    checksum_error = None
    if response_body is not None:
        try:
            checksum = response_checksum(response_body)
        except Exception as caught:
            checksum_error = caught
            validation_codes.append("response_checksum_error")
    effective_error = error if error is not None else checksum_error
    return ModelCallAudit(
        case_id=case.case_id,
        source_range=case.source_range,
        mode=mode.value,
        provider=provider,
        model=model,
        model_revision=model_revision,
        request_checksum=request.request_checksum if request is not None else None,
        response_checksum=checksum,
        cache_status=cache_status,
        attempts=attempts,
        elapsed_ms=elapsed_ms,
        request_bytes=request_bytes,
        response_bytes=len(response_body) if response_body is not None else 0,
        outcome=outcome,
        selected_choice_id=selected_choice_id,
        reported_confidence=reported_confidence,
        validation_codes=tuple(validation_codes),
        reason_codes=(),
        error_type=_safe_error_type(effective_error),
    )


def _audit_payload(audit: ModelCallAudit) -> dict[str, object]:
    return {field.name: getattr(audit, field.name) for field in fields(ModelCallAudit)}


def _is_response_error(error: Exception) -> bool:
    return isinstance(error, WorkbookModelResponseError)


def _safe_identity_token(
    value: object,
    *,
    required: bool,
) -> tuple[str | None, bool]:
    if value is None and not required:
        return None, False
    if (
        isinstance(value, str)
        and 0 < len(value) <= 64
        and value.isascii()
        and all(character.isalnum() or character in "._-" for character in value)
    ):
        return value, False
    return None, True


def _safe_error_type(error: Exception | None) -> str | None:
    if error is None:
        return None
    try:
        name = type(error).__name__
    except Exception:
        return "ExternalError"
    if (
        type(name) is str
        and 0 < len(name) <= 64
        and name.isascii()
        and all(character.isalnum() or character in "._-" for character in name)
    ):
        return name
    return "ExternalError"

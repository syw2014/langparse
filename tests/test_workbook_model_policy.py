from dataclasses import FrozenInstanceError, replace
from fractions import Fraction

import pytest

from langparse.workbooks.modeling import (
    ModelIdentity,
    ProviderReply,
    RegionAmbiguityCase,
    RegionCellCue,
    RegionChoice,
    WorkbookDisambiguation,
    WorkbookModelConfigurationError,
    WorkbookModelMode,
    WorkbookModelPolicy,
    WorkbookModelRequest,
)


class RecordingAdapter:
    identity = ModelIdentity(provider="recording", model="fixture", revision="1")

    def __init__(self):
        self.requests = []

    def complete(self, request: WorkbookModelRequest, *, timeout_seconds: float):
        self.requests.append((request, timeout_seconds))
        return ProviderReply(body=b"{}", provider_request_id=None, usage={})


def test_workbook_disambiguation_defaults_to_off_without_an_adapter():
    configured = WorkbookDisambiguation.off()

    assert configured.mode is WorkbookModelMode.OFF
    assert configured.adapter is None
    assert configured.policy == WorkbookModelPolicy()


def test_auto_and_required_require_explicit_adapters():
    with pytest.raises(
        WorkbookModelConfigurationError,
        match="auto workbook disambiguation requires an adapter",
    ):
        WorkbookDisambiguation(mode=WorkbookModelMode.AUTO)

    with pytest.raises(
        WorkbookModelConfigurationError,
        match="required workbook disambiguation requires an adapter",
    ):
        WorkbookDisambiguation(mode=WorkbookModelMode.REQUIRED)


def test_off_rejects_an_adapter_to_keep_the_no_network_contract_explicit():
    with pytest.raises(
        WorkbookModelConfigurationError,
        match="off workbook disambiguation cannot carry an adapter",
    ):
        WorkbookDisambiguation(
            mode=WorkbookModelMode.OFF,
            adapter=RecordingAdapter(),
        )


def test_policy_rejects_non_positive_limits():
    with pytest.raises(ValueError, match="timeout_seconds"):
        WorkbookModelPolicy(timeout_seconds=0)
    with pytest.raises(ValueError, match="max_response_bytes"):
        WorkbookModelPolicy(max_response_bytes=0)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("timeout_seconds", True, id="timeout_bool"),
        pytest.param("timeout_seconds", float("nan"), id="timeout_nan"),
        pytest.param("timeout_seconds", float("inf"), id="timeout_inf"),
        pytest.param("workbook_timeout_seconds", float("-inf"), id="workbook_timeout_inf"),
        pytest.param("workbook_timeout_seconds", "20", id="workbook_timeout_string"),
    ],
)
def test_policy_rejects_non_finite_or_non_real_timeouts(field: str, value):
    with pytest.raises(ValueError, match=field):
        replace(WorkbookModelPolicy(), **{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("max_attempts", True, id="attempts_bool"),
        pytest.param("max_cases", 1.0, id="cases_float"),
        pytest.param("max_calls", Fraction(3, 2), id="calls_fraction"),
        pytest.param("max_cells_per_case", float("nan"), id="cells_nan"),
        pytest.param("max_request_bytes", float("inf"), id="request_bytes_inf"),
        pytest.param("max_response_bytes", "128000", id="response_bytes_string"),
    ],
)
def test_policy_requires_exact_positive_non_bool_integer_counts(field: str, value):
    with pytest.raises(ValueError, match=field):
        replace(WorkbookModelPolicy(), **{field: value})


def test_policy_accepts_finite_positive_real_timeouts():
    policy = WorkbookModelPolicy(
        timeout_seconds=Fraction(1, 2),
        workbook_timeout_seconds=3,
    )

    assert policy.timeout_seconds == Fraction(1, 2)
    assert policy.workbook_timeout_seconds == 3


def test_policy_and_configuration_are_immutable():
    configured = WorkbookDisambiguation.auto(RecordingAdapter())

    with pytest.raises(FrozenInstanceError):
        configured.policy.max_calls = 99


def test_provider_reply_usage_is_deeply_immutable_and_shape_checked():
    source_usage = {"input_tokens": 4}
    reply = ProviderReply(
        body=b"{}",
        provider_request_id=None,
        usage=source_usage,
    )

    source_usage["input_tokens"] = 99
    source_usage["output_tokens"] = 2
    assert dict(reply.usage) == {"input_tokens": 4}

    with pytest.raises(TypeError):
        reply.usage["input_tokens"] = 5

    with pytest.raises(TypeError, match="usage keys"):
        ProviderReply(body=b"{}", provider_request_id=None, usage={1: 4})
    with pytest.raises(TypeError, match="usage values"):
        ProviderReply(body=b"{}", provider_request_id=None, usage={"input_tokens": True})
    with pytest.raises(TypeError, match="usage values"):
        ProviderReply(body=b"{}", provider_request_id=None, usage={"input_tokens": "4"})


def test_provider_reply_body_is_validated_and_defensively_copied():
    source = bytearray(b"decision")
    reply = ProviderReply(body=source, provider_request_id=None)

    source[:] = b"mutated!"
    assert reply.body == b"decision"
    assert type(reply.body) is bytes

    for invalid in ("private reply", [123], object()):
        with pytest.raises(TypeError, match="body must be bytes-like"):
            ProviderReply(body=invalid, provider_request_id=None)


def _region_case(
    feature_summary: tuple[tuple[str, object], ...] = (("density", 0.5),),
) -> RegionAmbiguityCase:
    return RegionAmbiguityCase(
        case_id="case-1",
        sheet_name="Sheet1",
        sheet_visibility="visible",
        source_range="A1:B2",
        fact_digest="digest",
        cells=(
            RegionCellCue(
                coordinate="A1",
                display_text="Header",
                value_type="string",
                style_fingerprint="style",
                merge_anchor=None,
                rowspan=1,
                colspan=1,
            ),
        ),
        feature_summary=feature_summary,
        choices=(RegionChoice("table", "logical_table", 0.5),),
        fallback_choice_id="table",
        ambiguity_codes=("close_scores",),
    )


def test_region_feature_summary_is_deeply_immutable_and_scalar_only():
    case = _region_case()

    with pytest.raises(TypeError):
        case.feature_summary[0][1] = 0.6
    with pytest.raises(TypeError, match="feature_summary must be a tuple"):
        _region_case(feature_summary=[("density", 0.5)])
    with pytest.raises(TypeError, match="feature_summary entries"):
        _region_case(feature_summary=(("density", {"value": 0.5}),))

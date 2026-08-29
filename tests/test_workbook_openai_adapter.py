from __future__ import annotations

import json
from unittest import mock

import pytest

from langparse.workbooks.modeling.config import WorkbookModelConfig
from langparse.workbooks.modeling.contract import decode_model_reply
from langparse.workbooks.modeling.openai_adapter import OpenAIWorkbookStructureAdapter
from langparse.workbooks.modeling.ports import WorkbookModelResponseError
from langparse.workbooks.modeling.types import ModelIdentity, ProviderReply, WorkbookModelRequest


def _make_dummy_request(
    case_id: str = "case-1", request_checksum: str = "sha256:1111"
) -> WorkbookModelRequest:
    body = json.dumps(
        {
            "schema_version": 1,
            "prompt_version": "region-choice-v1",
            "privacy_version": "region-privacy-v1",
            "request_checksum": request_checksum,
            "cases": [{"case_id": case_id}],
        }
    ).encode("utf-8")
    return WorkbookModelRequest(
        schema_version=1,
        prompt_version="region-choice-v1",
        privacy_version="region-privacy-v1",
        request_checksum=request_checksum,
        body=body,
        case_ids=(case_id,),
        choice_ids_by_case=((case_id, ("c1", "c2")),),
    )


def test_openai_adapter_identity():
    config = WorkbookModelConfig(api_key="sk-test", model="gpt-4o-mini", base_url=None)
    adapter = OpenAIWorkbookStructureAdapter(config)
    assert isinstance(adapter.identity, ModelIdentity)
    assert adapter.identity.provider == "openai"
    assert adapter.identity.model == "gpt-4o-mini"
    assert adapter.identity.revision is None


def test_openai_adapter_complete_success():
    config = WorkbookModelConfig(
        api_key="sk-test",
        model="gpt-4o-mini",
        base_url=None,
        timeout_seconds=5.0,
    )
    adapter = OpenAIWorkbookStructureAdapter(config)

    mock_client = mock.MagicMock()
    mock_choice = mock.MagicMock()
    mock_choice.message.content = json.dumps(
        {
            "schema_version": 1,
            "request_checksum": "sha256:1111",
            "decisions": [
                {
                    "case_id": "case-1",
                    "status": "selected",
                    "choice_id": "c1",
                    "confidence": 0.95,
                    "reason_codes": ["model_prediction"],
                }
            ],
        }
    )
    mock_usage = mock.MagicMock()
    mock_usage.prompt_tokens = 150
    mock_usage.completion_tokens = 25
    mock_usage.total_tokens = 175

    mock_response = mock.MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.id = "chatcmpl-test-123"
    mock_response.usage = mock_usage

    mock_client.chat.completions.create.return_value = mock_response

    with mock.patch("openai.OpenAI", return_value=mock_client):
        req = _make_dummy_request()
        reply = adapter.complete(req, timeout_seconds=15.0)

        assert isinstance(reply, ProviderReply)
        assert reply.provider_request_id == "chatcmpl-test-123"
        assert reply.usage == {
            "prompt_tokens": 150,
            "completion_tokens": 25,
            "total_tokens": 175,
        }
        decoded = json.loads(reply.body.decode("utf-8"))
        assert decoded["decisions"][0]["status"] == "selected"
        response_format = mock_client.chat.completions.create.call_args.kwargs["response_format"]
        assert response_format["type"] == "json_schema"
        assert response_format["json_schema"]["strict"] is True
        assert response_format["json_schema"]["schema"]["additionalProperties"] is False
        assert mock_client.chat.completions.create.call_args.kwargs["timeout"] == 5.0
        assert mock_client.chat.completions.create.call_args.kwargs["temperature"] == 0
        assert mock_client.chat.completions.create.call_args.kwargs["seed"] == 0


def test_openai_adapter_explicitly_constrains_the_selected_status_for_compatible_providers():
    config = WorkbookModelConfig(api_key="sk-test", model="compatible-model")
    adapter = OpenAIWorkbookStructureAdapter(config)
    mock_client = mock.MagicMock()

    def provider_response(**kwargs):
        system_message = kwargs["messages"][0]["content"]
        status = (
            "selected"
            if "status MUST be exactly 'selected'" in system_message
            and "Never use 'resolved'" in system_message
            and "Use 'unclassified' only when no registered typed choice is supported"
            in system_message
            else "resolved"
        )
        choice = mock.MagicMock()
        choice.message.content = json.dumps(
            {
                "schema_version": 1,
                "request_checksum": "sha256:1111",
                "decisions": [
                    {
                        "case_id": "case-1",
                        "status": status,
                        "choice_id": "c1",
                        "confidence": 0.9,
                        "reason_codes": ["provider_prediction"],
                    }
                ],
            }
        )
        response = mock.MagicMock()
        response.choices = [choice]
        response.id = "chatcmpl-compatible"
        response.usage = None
        return response

    mock_client.chat.completions.create.side_effect = provider_response
    with mock.patch("openai.OpenAI", return_value=mock_client):
        request = _make_dummy_request()
        reply = adapter.complete(request, timeout_seconds=10.0)

    decision = decode_model_reply(reply, request, max_response_bytes=128_000)
    assert decision.status == "selected"
    assert decision.choice_id == "c1"


def test_openai_adapter_complete_api_error():
    config = WorkbookModelConfig(api_key="sk-test", model="gpt-4o-mini")
    adapter = OpenAIWorkbookStructureAdapter(config)

    mock_client = mock.MagicMock()
    mock_client.chat.completions.create.side_effect = RuntimeError(
        "OpenAI connection timeout with sk-secret-value"
    )

    with mock.patch("openai.OpenAI", return_value=mock_client):
        req = _make_dummy_request()
        with pytest.raises(WorkbookModelResponseError) as exc_info:
            adapter.complete(req, timeout_seconds=10.0)
        assert "OpenAI completion failed" in str(exc_info.value)
        assert "sk-secret-value" not in str(exc_info.value)


def test_openai_adapter_missing_dependency():
    config = WorkbookModelConfig(api_key="sk-test", model="gpt-4o-mini")
    adapter = OpenAIWorkbookStructureAdapter(config)

    with mock.patch.dict("sys.modules", {"openai": None}):
        req = _make_dummy_request()
        with pytest.raises(ImportError) as exc_info:
            adapter.complete(req, timeout_seconds=10.0)
        assert "openai" in str(exc_info.value)

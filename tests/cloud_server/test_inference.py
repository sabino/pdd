"""Check the observed client payloads and core adapters without model calls."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from pdd.cloud_server import inference
from pdd.core.cloud import CloudConfig
from pdd.core.execution import is_server_execution, server_execution
from pdd.llm_invoke import _ROUTER_MODEL_OVERRIDE
from pdd.preprocess import preprocess


@pytest.mark.parametrize(
    ("endpoint", "payload", "helper", "result", "field"),
    [
        (
            "generateCode",
            {
                "promptContent": "write a function",
                "searchInput": "function",
                "model": "provider/model",
                "compress": True,
            },
            "code_generator",
            ("code", 0.1, "model"),
            "generatedCode",
        ),
        (
            "generateExample",
            {"promptContent": "function", "codeContent": "code"},
            "context_generator",
            ("example", 0.1, "model"),
            "generatedExample",
        ),
        (
            "generateTest",
            {
                "promptContent": "function",
                "codeContent": "code",
                "existingTests": "tests",
                "sourceFilePath": "src/function.py",
                "testFilePath": "tests/test_function.py",
                "moduleName": "function",
                "mode": "generate",
            },
            "generate_test",
            ("tests", 0.1, "model"),
            "generatedTest",
        ),
        (
            "generateTest",
            {"promptContent": "function", "example": "example"},
            "generate_test",
            ("tests", 0.1, "model"),
            "generatedTest",
        ),
        (
            "generateTest",
            {
                "promptContent": "function",
                "codeContent": "code",
                "existingTests": "tests",
                "coverageReport": "report",
                "mode": "increase",
            },
            "increase_tests",
            ("tests", 0.1, "model"),
            "generatedTest",
        ),
        (
            "generateBugTest",
            {
                "promptContent": "function",
                "codeContent": "code",
                "programContent": "program",
                "currentOutput": "wrong",
                "desiredOutput": "right",
            },
            "bug_to_unit_test",
            ("tests", 0.1, "model"),
            "generatedTest",
        ),
        (
            "fixCode",
            {
                "prompt": "function",
                "code": "code",
                "unitTest": "tests",
                "errors": "error",
                "protectTests": True,
                "codeFileExt": ".py",
            },
            "fix_errors_from_unit_tests",
            (False, True, "tests", "fixed", "analysis", 0.1, "model"),
            "fixedCode",
        ),
        (
            "crashCode",
            {
                "promptContent": "function",
                "codeContent": "code",
                "programContent": "program",
                "errorContent": "error",
                "programPath": "program.py",
                "codePath": "code.py",
            },
            "fix_code_module_errors",
            (False, True, "program", "fixed", "analysis", 0.1, "model"),
            "fixedCode",
        ),
        (
            "verifyCode",
            {
                "promptContent": "function",
                "codeContent": "code",
                "programContent": "program",
                "outputContent": "output",
            },
            "fix_verification_errors",
            {
                "fixed_program": "program",
                "fixed_code": "fixed",
                "explanation": "analysis",
                "verification_issues_count": 0,
                "total_cost": 0.1,
                "model_name": "model",
            },
            "fixedCode",
        ),
        (
            "llmInvoke",
            {
                "prompt": "function",
                "inputJson": {},
                "outputSchema": {"type": "object"},
                "useBatchMode": False,
            },
            "llm_invoke",
            {
                "result": {"answer": "value"},
                "cost": 0.1,
                "model_name": "model",
                "thinking_output": None,
            },
            "result",
        ),
        (
            "llmInvoke",
            {
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": "hello"}]}
                ]
            },
            "llm_invoke",
            {"result": "answer", "cost": 0.1, "model_name": "model"},
            "result",
        ),
    ],
)
def test_core_adapters_accept_client_payloads(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
    payload: dict[str, Any],
    helper: str,
    result: Any,
    field: str,
) -> None:
    mocked = Mock(return_value=result)
    monkeypatch.setattr(inference, helper, mocked)
    response = client.post(
        f"/{endpoint}",
        json={
            "language": "python",
            "strength": 0.9,
            "temperature": 0,
            "time": None,
            "verbose": False,
            **payload,
        },
    )
    assert response.status_code == 200, response.text
    assert field in response.json()
    assert response.json()["totalCost"] == 0.1
    assert response.json()["modelName"] == "model"
    assert mocked.call_args.kwargs["time"] == 0.25
    if endpoint == "generateCode":
        assert mocked.call_args.kwargs["preprocess_prompt"] is False
    if endpoint == "llmInvoke":
        assert mocked.call_args.kwargs["use_cloud"] is False


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"strength": 1.1, "promptContent": "x"},
        {"temperature": -1, "promptContent": "x"},
        {"promptContent": "x", "unexpected": True},
    ],
)
def test_invalid_inference_does_not_call_a_model(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]
) -> None:
    mocked = Mock()
    monkeypatch.setattr(inference, "code_generator", mocked)
    assert client.post("/generateCode", json=payload).status_code == 422
    mocked.assert_not_called()


def test_provider_failure_has_a_safe_http_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        inference, "code_generator", Mock(side_effect=RuntimeError("provider-secret"))
    )
    response = client.post("/generateCode", json={"promptContent": "function"})
    assert response.status_code == 502
    assert "provider-secret" not in response.text


def test_server_context_preserves_directives_as_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with server_execution():
        assert is_server_execution()
        assert not CloudConfig.is_cloud_enabled()
        prompt = "<shell>touch /tmp/should-not-exist</shell><include>/etc/passwd</include><web>https://example.com</web>"
        assert preprocess(prompt, double_curly_brackets=False) == prompt
    assert not is_server_execution()


def test_concurrent_requests_keep_model_overrides_isolated(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def generate(**kwargs: Any) -> tuple[str, float, str]:
        assert is_server_execution()
        assert not CloudConfig.is_cloud_enabled()
        return str(_ROUTER_MODEL_OVERRIDE.get()), 0, "model"

    monkeypatch.setattr(inference, "code_generator", generate)

    def call(model: str) -> str:
        response = client.post(
            "/generateCode", json={"promptContent": "function", "model": model}
        )
        return str(response.json()["generatedCode"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(call, ["model-a", "model-b"])) == ["model-a", "model-b"]
    assert _ROUTER_MODEL_OVERRIDE.get() is None

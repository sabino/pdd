"""Check library deduplication, sharing boundaries, and retrieval provenance."""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from pdd.cloud_server import inference


def test_private_examples_are_idempotent_and_scoped(client: TestClient) -> None:
    body = {
        "command": "generate",
        "searchInput": "calculate sum function",
        "input": {"prompts": [{"content": "sum function", "filename": "sum.prompt"}]},
        "output": {
            "code": [
                {"content": "def sum_values(a, b): return a + b", "filename": "sum.py"}
            ]
        },
        "metadata": {"title": "Sum function", "language": "python", "isPublic": False},
    }
    first = client.post("/submitExample", json=body).json()
    assert client.post("/submitExample", json=body).json() == first
    assert len(client.get("/listExamples").json()["examples"]) == 1
    results = client.get(
        "/searchExamples", params={"query": "sum", "language": "python"}
    ).json()["examples"]
    assert results[0]["id"] == first["exampleId"]
    other = {"Authorization": "Bearer " + "b" * 48}
    assert client.get("/listExamples", headers=other).json() == {"examples": []}
    assert client.get(
        "/searchExamples", headers=other, params={"query": "sum"}
    ).json() == {"examples": []}
    assert client.get(
        "/searchExamples", params={"query": "sum", "language": "rust"}
    ).json() == {"examples": []}
    shared = {**body, "metadata": {**body["metadata"], "isPublic": True}}
    client.post("/submitExample", json=shared)
    assert len(client.get("/listExamples", headers=other).json()["examples"]) == 1


def test_generation_injects_only_accessible_examples_with_provenance(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = {
        "command": "generate",
        "searchInput": "sum function",
        "input": {"prompts": [{"content": "sum function"}]},
        "output": {"code": [{"content": "SUM_EXAMPLE"}]},
        "metadata": {"title": "Sum function", "language": "python"},
    }
    identifier = client.post("/submitExample", json=body).json()["exampleId"]
    mocked = Mock(return_value=("code", 0, "model"))
    monkeypatch.setattr(inference, "code_generator", mocked)
    response = client.post(
        "/generateCode", json={"promptContent": "sum function", "language": "python"}
    )
    assert response.json()["examplesUsed"] == [
        {"id": identifier, "module": identifier, "title": "Sum function"}
    ]
    assert "SUM_EXAMPLE" in mocked.call_args.kwargs["prompt"]
    response = client.post(
        "/generateCode",
        headers={"Authorization": "Bearer " + "b" * 48},
        json={"promptContent": "sum function", "language": "python"},
    )
    assert response.json()["examplesUsed"] == []
    assert "SUM_EXAMPLE" not in mocked.call_args.kwargs["prompt"]

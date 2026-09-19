"""Tests for OpenRouter model metadata lookup."""

import httpx

import src.llm.model_info as model_info


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


async def test_returns_input_modalities(monkeypatch):
    async def fake_get(self, url, **kwargs):
        return FakeResponse({"data": [{"id": "test/model", "architecture": {"input_modalities": ["text", "image"]}}]})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    assert await model_info.get_input_modalities("test/model") == {"text", "image"}


async def test_unknown_model_falls_back_to_text(monkeypatch):
    async def fake_get(self, url, **kwargs):
        return FakeResponse({"data": []})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    assert await model_info.get_input_modalities("nope") == {"text"}


async def test_http_error_falls_back_to_text(monkeypatch):
    async def fake_get(self, url, **kwargs):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    assert await model_info.get_input_modalities("test/model") == {"text"}

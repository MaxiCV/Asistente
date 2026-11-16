import asyncio
import json
import subprocess
import sys

import httpx
import pytest
from app.chat.llm import GeminiAnswerer
from app.chat.prompt import make_prompt
from app.contracts import ChatConfig
from app.core.config import Settings
from google.genai import errors, types
from test_chat_service import passages


@pytest.mark.parametrize("outcome", ["ok", "invalid", "quota", "forbidden", "timeout"])
def test_real_adapter_with_mock_transport(outcome):
    async def scenario():
        requests = []

        async def handle(request):
            requests.append(request)
            assert request.method == "POST" and "gemini-3.5-flash-lite" in str(request.url)
            body = json.loads(request.content)
            assert "additional_properties" not in request.content.decode()
            assert "additionalProperties" not in request.content.decode()
            assert body["generationConfig"]["maxOutputTokens"] == 2048
            assert body["generationConfig"]["responseMimeType"] == "application/json"
            assert (
                "responseSchema" in body["generationConfig"]
                or "responseJsonSchema" in body["generationConfig"]
            )
            if outcome == "timeout":
                raise httpx.ReadTimeout("synthetic private detail")
            if outcome in ("quota", "forbidden"):
                return httpx.Response(
                    429 if outcome == "quota" else 403,
                    json={
                        "error": {
                            "message": "synthetic private detail",
                            "code": 429 if outcome == "quota" else 403,
                        }
                    },
                )
            text = (
                "not json"
                if outcome == "invalid"
                else json.dumps(
                    {"status": "answered", "answer": "Resumen [1]", "cited_sources": [1]}
                )
            )
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {"role": "model", "parts": [{"text": text}]},
                            "finishReason": "STOP",
                        }
                    ]
                },
            )

        config = ChatConfig()
        settings = Settings(_env_file=None, GEMINI_API_KEY="synthetic-key")
        transport = httpx.MockTransport(handle)
        client = httpx.AsyncClient(transport=transport)
        provider = GeminiAnswerer(
            settings,
            config,
            http_options={
                "httpx_async_client": client,
                "timeout": 30000,
                "retry_options": types.HttpRetryOptions(attempts=1),
            },
        )
        assert requests == []  # Constructor must not look up remote model metadata.
        assert provider.llm._client._api_client._http_options.timeout == 30000
        prompt, evidence = make_prompt("Pregunta", passages(), [], config)
        try:
            if outcome == "ok":
                response = await provider.answer(prompt, evidence)
                assert response.cited_sources == [1]
            else:
                with pytest.raises((errors.APIError, ValueError, httpx.TimeoutException)):
                    await provider.answer(prompt, evidence)
            assert len(requests) == 1  # No SDK retry consuming additional quota.
        finally:
            await provider.aclose()

    asyncio.run(scenario())


def test_api_import_and_openapi_are_offline():
    script = """import socket
attempts = []
def blocked(*args, **kwargs):
    attempts.append(True)
    raise RuntimeError("External network forbidden in offline import")
socket.socket.connect = blocked
from app.main import create_app
from app.core.config import Settings
assert "/api/v1/chat" in create_app(Settings(_env_file=None)).openapi()["paths"]
assert not attempts
print("offline-ok")
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=40
    )
    assert result.returncode == 0, result.stderr
    assert "offline-ok" in result.stdout

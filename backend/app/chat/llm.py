import asyncio
import os
from typing import Literal

from pydantic import BaseModel

from app.chat.errors import ChatError
from app.contracts import LlmAnswer


class ProviderAnswer(BaseModel):
    """Respuesta estructurada con estado, texto y números de fuentes citadas."""

    # The SDK's Schema transport rejects additionalProperties from extra='forbid'.
    # Keep strict domain validation in LlmAnswer, after provider parsing.

    status: Literal["answered", "insufficient_evidence"]
    answer: str
    cited_sources: list[int]


class GeminiAnswerer:
    def __init__(self, settings, config, *, http_options=None):
        from google.genai import types
        from llama_index.llms.google_genai import GoogleGenAI

        if not settings.gemini_api_key:
            raise ChatError(
                503, "llm_unavailable", "Configura la clave Gemini para generar respuestas."
            )
        if os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "false").lower() != "false":
            raise ChatError(
                503, "llm_unavailable", "Este chat utiliza Gemini API con clave de proyecto."
            )
        self.config = config
        self.llm = GoogleGenAI(
            model=config.model,
            api_key=settings.gemini_api_key.get_secret_value(),
            temperature=config.temperature,
            max_tokens=config.max_output_tokens,
            context_window=1_048_576,
            max_retries=0,
            file_mode="inline",
            http_options=http_options
            or types.HttpOptions(
                timeout=int(config.timeout_seconds * 1000),
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    async def answer(self, prompt, evidence):
        async with asyncio.timeout(self.config.timeout_seconds):
            raw = await self.llm.astructured_predict(ProviderAnswer, prompt, evidence=evidence)
            return LlmAnswer.model_validate(raw.model_dump())

    async def aclose(self):
        # The pinned adapter exposes no close method; close the underlying SDK clients.
        await self.llm._client.aio.aclose()
        self.llm._client.close()

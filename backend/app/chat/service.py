import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid5

from app.chat.errors import ChatError
from app.chat.history import TurnLocks, request_hash
from app.chat.prompt import INSUFFICIENT, MARKER, make_prompt
from app.contracts import (
    ChatResponse,
    ChatTurn,
    Citation,
    ContextPassage,
    LlmAnswer,
    citation_markers,
)

CONVERSATION_NAMESPACE = UUID("104a4d3e-049c-4cd1-bf39-7a94874b7650")


def validated_answer(raw, passages):
    raw = LlmAnswer.model_validate(raw)
    try:
        used = citation_markers(raw.answer)
    except ValueError:
        return INSUFFICIENT, [], "none", "invalid_citations"
    declared = set(raw.cited_sources)
    allowed = set(range(1, len(passages) + 1))
    if raw.status == "insufficient_evidence":
        return INSUFFICIENT, [], "none", None
    # Text is retained only if the complete citation structure is valid.
    if not used or used != declared or not used <= allowed:
        return INSUFFICIENT, [], "none", "invalid_citations"
    citations = []
    for marker in sorted(used):
        item = passages[marker - 1]
        doc = item.document
        patent_id = next(
            (
                getattr(i, "publication_id", None)
                for i in doc.identities
                if getattr(i, "publication_id", None)
            ),
            None,
        )
        citations.append(
            Citation(
                marker=marker,
                document_id=doc.document_id,
                passage_id=item.passage.passage_id,
                title=doc.title,
                document_type=doc.document_type,
                content_level=doc.content_level,
                source_url=doc.source_url,
                doi=doc.doi,
                publication_id=patent_id,
                publication_date=doc.publication_date,
            )
        )
    levels = {c.content_level for c in citations}
    level = (
        "mixed" if len(levels) > 1 else ("abstract" if "abstract" in levels else "metadata_only")
    )
    answer = MARKER.sub(lambda m: "".join(f"[{int(n)}]" for n in m[1].split(",")), raw.answer)
    return answer, citations, level, None


class ChatService:
    def __init__(self, settings, config, history, retrieve, llm_factory):
        self.settings, self.config, self.history = settings, config, history
        self.retrieve, self.llm_factory = retrieve, llm_factory
        self.locks = TurnLocks()

    async def answer(self, request):
        try:
            async with asyncio.timeout(self.config.operation_timeout_seconds):
                async with self.locks.hold(("request", request.request_id)):
                    saved = await self.history.lookup(request)
                    if saved:
                        return saved.response
                    conversation = request.conversation_id or uuid5(
                        CONVERSATION_NAMESPACE, str(request.request_id)
                    )
                    async with self.locks.hold(("conversation", conversation)):
                        return await self._answer(request, conversation)
        except TimeoutError:
            raise ChatError(
                502,
                "llm_failed",
                "La operación excedió el tiempo disponible. Reintenta el mismo envío.",
            ) from None

    async def _answer(self, request, conversation):
        history = await self.history.read(
            conversation, limit=max(1, self.config.max_history_turns), descending=True
        )
        history.reverse()
        if request.conversation_id and not history:
            raise ChatError(
                404, "conversation_not_found", "La conversación no existe. Inicia una nueva."
            )
        generation = history[-1].response.index_generation if history else request.index_generation
        if history and request.index_generation and request.index_generation != generation:
            raise ChatError(
                409,
                "conversation_generation_mismatch",
                "La conversación conserva su versión del corpus. Inicia una nueva para cambiarla.",
            )
        params = request.retrieval(self.config.default_mode)
        params.index_generation = generation
        # Only this read-only corpus work runs in a thread. After cancellation it cannot
        # call the provider or persist a turn; the surrounding reader closes its client.
        pinned, passages = await asyncio.to_thread(self.retrieve, params, self.config.top_k)
        answer, citations, level, reason = INSUFFICIENT, [], "none", None
        model = None
        if passages:
            try:
                provider = self.llm_factory(self.settings, self.config)
            except ChatError:
                raise
            except Exception:
                raise ChatError(
                    503, "llm_unavailable", "No se pudo iniciar el proveedor Gemini."
                ) from None
            try:
                prompt, evidence = make_prompt(request.question, passages, history, self.config)
                async with asyncio.timeout(self.config.timeout_seconds):
                    raw = await provider.answer(prompt, evidence)
                model = self.config.model
                answer, citations, level, reason = validated_answer(raw, passages)
            except Exception:
                raise ChatError(
                    502,
                    "llm_failed",
                    "Gemini no pudo generar una respuesta válida. Reintenta el mismo envío.",
                ) from None
            finally:
                try:
                    await provider.aclose()
                except Exception:
                    raise ChatError(
                        502, "llm_failed", "No se pudo cerrar la operación de Gemini."
                    ) from None
        cited = {c.marker for c in citations}
        response = ChatResponse(
            conversation_id=conversation,
            turn_id=request.request_id,
            turn_index=history[-1].response.turn_index + 1 if history else 1,
            index_generation=pinned.generation_id,
            mode=params.mode,
            status="answered" if citations else "insufficient_evidence",
            evidence_level=level,
            answer=answer,
            citations=citations,
            model=model,
            created_at=datetime.now(UTC),
            context=[
                ContextPassage(
                    rank=i,
                    document_id=p.document.document_id,
                    passage_id=p.passage.passage_id,
                    text_sha256=p.passage.text_sha256,
                    score=p.score,
                    content_level=p.document.content_level,
                    cited=i in cited,
                )
                for i, p in enumerate(passages, 1)
            ],
        )
        await self.history.save(
            ChatTurn(
                request=request,
                request_sha256=request_hash(request),
                response=response,
                rejection_reason=reason,
            )
        )
        return response

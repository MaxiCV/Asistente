import { useEffect, useRef, useState } from "react";
import { Alert, Button } from "@mui/material";
import { ApiError, request, typeLabel } from "./api";
import type { ChatRequest, ChatResponse, ChatTurn, ConversationResponse, Corpus, Criteria } from "./api";

const SESSION_KEY = "nexo.conversation.v1";
type Session = { conversation_id?: string; index_generation?: string; pending?: ChatRequest };
const levels = {
  abstract: "Basado en resúmenes",
  metadata_only: "Solo metadatos",
  mixed: "Resúmenes y metadatos",
  none: "Evidencia insuficiente",
};
function readSession(): Session {
  try {
    const value = JSON.parse(sessionStorage.getItem(SESSION_KEY) ?? "{}");
    if (!value || typeof value !== "object") return {};
    return {
      conversation_id: typeof value.conversation_id === "string" ? value.conversation_id : undefined,
      index_generation: typeof value.index_generation === "string" ? value.index_generation : undefined,
      pending: value.pending && typeof value.pending.request_id === "string" && typeof value.pending.question === "string" ? value.pending : undefined,
    };
  } catch { return {}; }
}
function message(error: Error) {
  if (!(error instanceof ApiError)) return "No se pudo recuperar la conversación. Reintenta.";
  return ({
    llm_unavailable: "El chat necesita una clave Gemini disponible en el servidor. Puedes seguir usando el buscador.",
    llm_failed: "No se pudo completar la respuesta. Puedes reintentar el mismo envío.",
    chat_history_unavailable: "No se pudo confirmar el historial. Reintenta el mismo envío para comprobar si quedó guardado.",
    conversation_not_found: "Esta conversación ya no está disponible. Inicia una nueva.",
    generation_retired: "La colección de esta conversación fue retirada. Inicia una nueva conversación.",
    conversation_generation_mismatch: "Esta conversación conserva otra versión de la colección. Inicia una nueva para cambiarla.",
    search_mode_unavailable: "Esta versión de la colección solo admite búsqueda semántica.",
    query_not_encodable: "La pregunta supera el límite del buscador local. Acórtala y vuelve a enviarla.",
    request_id_conflict: "El identificador de este envío ya se usó con otros datos. Prepara un nuevo envío.",
  } as Record<string, string>)[error.code ?? ""] ?? error.message;
}

export default function Chat({ active, initialCriteria, corpus, openCitation }: {
  active: boolean;
  initialCriteria: Criteria;
  corpus?: Corpus;
  openCitation: (value: { id: string; generation: string }) => void;
}) {
  const [session, setSession] = useState<Session>(readSession);
  const [filters, setFilters] = useState<Criteria>(initialCriteria);
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [loadError, setLoadError] = useState<Error | null>(null);
  const [storageError, setStorageError] = useState(false);
  const [cursor, setCursor] = useState<number | null>(null);
  const [reload, setReload] = useState(0);
  const input = useRef<HTMLTextAreaElement>(null);
  const controller = useRef<AbortController | null>(null);
  const epoch = useRef(0);
  const sending = useRef(false);
  const initial = useRef(session);
  const currentSession = useRef(session);
  const heading = useRef<HTMLHeadingElement>(null);
  const focusAnswer = useRef(false);

  function persist(value: Session) {
    currentSession.current = value;
    setSession(value);
    try { sessionStorage.setItem(SESSION_KEY, JSON.stringify(value)); }
    catch { setStorageError(true); }
  }
  useEffect(() => {
    if (active) {
      input.current?.focus();
      if (!currentSession.current.conversation_id && !currentSession.current.pending) setFilters(initialCriteria);
    }
  }, [active]);
  useEffect(() => {
    const saved = initial.current;
    if (!saved.conversation_id) return;
    const abort = new AbortController();
    const version = epoch.current;
    setLoading(true);
    setLoadError(null);
    request<ConversationResponse>(`chat/${saved.conversation_id}?limit=100`, abort.signal)
      .then((value) => {
        if (epoch.current !== version) return;
        setTurns(value.turns);
        setCursor(value.next_cursor);
        const last = value.turns.at(-1);
        if (last) setFilters({ q: "", mode: last.response.mode,
          document_type: last.request.document_type, date_from: last.request.date_from ?? "",
          date_to: last.request.date_to ?? "", publication_type: last.request.publication_type ?? "" });
        const pending = currentSession.current.pending;
        persist({ conversation_id: value.conversation_id, index_generation: value.index_generation,
          pending: value.turns.some(t => t.response.turn_id === pending?.request_id) ? undefined : pending });
      })
      .catch((err: Error) => { if (!abort.signal.aborted && epoch.current === version) setLoadError(err); })
      .finally(() => { if (!abort.signal.aborted && epoch.current === version) setLoading(false); });
    return () => abort.abort();
  }, [reload]);
  useEffect(() => () => { controller.current?.abort(); }, []);
  useEffect(() => {
    if (focusAnswer.current && active) heading.current?.focus();
    focusAnswer.current = false;
  }, [turns, active]);

  async function loadMore() {
    if (!session.conversation_id || cursor === null) return;
    const version = epoch.current;
    setLoading(true);
    try {
      const value = await request<ConversationResponse>(`chat/${session.conversation_id}?limit=100&after=${cursor}`);
      if (epoch.current !== version) return;
      setTurns(current => [...current, ...value.turns]);
      setCursor(value.next_cursor);
      setLoadError(null);
    } catch (err) { if (epoch.current === version) setLoadError(err as Error); }
    finally { if (epoch.current === version) setLoading(false); }
  }
  function fresh() {
    epoch.current += 1;
    controller.current?.abort();
    sending.current = false;
    focusAnswer.current = false;
    setBusy(false); setLoading(false); setError(null); setLoadError(null);
    setTurns([]); setCursor(null); setQuestion(""); setFilters(initialCriteria);
    initial.current = {};
    persist({});
    input.current?.focus();
  }
  async function send(body: ChatRequest) {
    if (sending.current) return;
    sending.current = true;
    const version = epoch.current;
    const abort = new AbortController();
    controller.current = abort;
    persist({ ...currentSession.current, pending: body });
    setBusy(true); setError(null);
    try {
      const result = await request<ChatResponse>("chat", abort.signal,
        { method: "POST", body, timeoutMs: 75000 });
      if (epoch.current !== version) return;
      focusAnswer.current = true;
      setTurns(current => [...current.filter(t => t.response.turn_id !== result.turn_id), { request: body, response: result }]
        .sort((a, b) => a.response.turn_index - b.response.turn_index));
      persist({ conversation_id: result.conversation_id, index_generation: result.index_generation });
      setQuestion("");
    } catch (err) {
      if (epoch.current === version && !abort.signal.aborted) setError(err as Error);
    } finally {
      if (epoch.current === version) { sending.current = false; setBusy(false); }
    }
  }
  function submit() {
    if (!question.trim() || busy || loading || session.pending || invalidDates) return;
    void send({ request_id: crypto.randomUUID(), question: question.trim(),
      conversation_id: session.conversation_id, index_generation: session.index_generation,
      mode: filters.mode, document_type: filters.document_type,
      date_from: filters.date_from || undefined, date_to: filters.date_to || undefined,
      publication_type: filters.publication_type || undefined });
  }
  function editPending(semantic = false) {
    if (session.pending) setQuestion(session.pending.question);
    if (semantic) setFilters(current => ({ ...current, mode: "semantic" }));
    persist({ ...session, pending: undefined }); setError(null); input.current?.focus();
  }
  const invalidDates = !!filters.date_from && !!filters.date_to && filters.date_from > filters.date_to;
  const terminal = error instanceof ApiError && ["generation_retired", "conversation_not_found", "conversation_generation_mismatch"].includes(error.code ?? "");
  const editable = error instanceof ApiError && ([409, 422].includes(error.status)) && !terminal;
  const canSend = !busy && !loading && !loadError && !session.pending && !invalidDates && cursor === null;
  const bm25 = !!corpus?.manifest?.bm25 || (!!session.conversation_id && filters.mode !== "semantic");
  function answer(turn: ChatTurn) {
    const text = turn.response.answer.replace(/\[(\d+(?:\s*,\s*\d+)*)\]/g,
      (_, group: string) => group.split(",").map(n => `[${Number(n)}]`).join(""));
    return text.split(/(\[\d+\])/).map((part, index) => {
      const match = /^\[(\d+)\]$/.exec(part);
      const citation = match && turn.response.citations.find(c => c.marker === Number(match[1]));
      return citation ? <button type="button" key={index} className="inline-citation"
        aria-label={`Fuente ${citation.marker}: ${citation.title}`}
        onClick={() => openCitation({ id: citation.document_id, generation: turn.response.index_generation })}>{part}</button> : part;
    });
  }
  return <section className="chat-view" aria-labelledby="chat-title">
    <div className="chat-heading">
      <div><p className="eyebrow">Consulta con fuentes</p><h1 id="chat-title">Conversa con la colección</h1></div>
      <Button variant="outlined" onClick={fresh}>Nueva conversación</Button>
    </div>
    <p className="muted">Respuestas en español a partir de los fragmentos recuperados. Cada referencia abre la ficha de su fuente.</p>
    {storageError && <Alert severity="info">El navegador no permite guardar la sesión. El historial permanece en el servidor, pero esta pestaña no podrá recuperarlo al recargar.</Alert>}
    {loadError && <Alert severity="error" action={<Button onClick={() => setReload(n => n + 1)}>Reintentar</Button>}>{message(loadError)} Usa «Nueva conversación» si ya no existe.</Alert>}
    {loading && <p role="status">Recuperando conversación…</p>}
    {session.index_generation && <p className="chat-generation">Versión de la colección: <code>{session.index_generation}</code></p>}
    <div className="chat-thread" aria-live="polite" aria-relevant="additions" aria-busy={busy}>
      {!turns.length && !loading && <div className="chat-empty">
        <h2>Una pregunta, con evidencia a mano</h2>
        <p>Compara enfoques, explora sensores o revisa qué información está disponible en los resúmenes.</p>
        <button className="chat-example" onClick={() => { setQuestion("¿Qué sensores se utilizan para detectar caídas en el hogar?"); input.current?.focus(); }}>¿Qué sensores se utilizan para detectar caídas en el hogar?</button>
      </div>}
      {turns.map((turn, index) => <article className="chat-turn" key={turn.response.turn_id}>
        <div className="chat-question"><span className="eyebrow">Tu pregunta</span><p>{turn.request.question}</p></div>
        <div className="chat-answer">
          <h2 tabIndex={-1} ref={index === turns.length - 1 ? heading : undefined} className="chat-answer-heading">Respuesta {turn.response.turn_index}</h2>
          <span className={`evidence-badge evidence-${turn.response.evidence_level}`}>{levels[turn.response.evidence_level]}</span>
          <p className="answer-text">{answer(turn)}</p>
          {turn.response.citations.length > 0 && <ol className="chat-sources" aria-label="Fuentes de la respuesta">
            {turn.response.citations.map(c => <li key={c.marker} value={c.marker}><button onClick={() => openCitation({ id: c.document_id, generation: turn.response.index_generation })}>{c.title}</button><span>{c.document_type === "patent" ? `Solicitud · ${c.publication_id ?? "EPO OPS"}` : "Publicación científica"} · {c.content_level === "abstract" ? "Resumen disponible" : "Solo título y metadatos"}</span></li>)}
          </ol>}
          <p className="muted small">Recuperación {turn.response.mode === "semantic" ? "semántica" : turn.response.mode === "lexical" ? "léxica" : "híbrida"} · {turn.request.document_type === "all" ? "Todos los documentos" : turn.request.document_type === "patent" ? "Patentes y solicitudes" : "Publicaciones"}{turn.request.publication_type ? ` · ${typeLabel(turn.request.publication_type)}` : ""}{turn.request.date_from ? ` · Desde ${turn.request.date_from}` : ""}{turn.request.date_to ? ` · Hasta ${turn.request.date_to}` : ""}</p>
        </div>
      </article>)}
    </div>
    {cursor !== null && <Button disabled={loading} onClick={() => void loadMore()}>Cargar siguientes turnos</Button>}
    {session.pending && !busy && <Alert severity={error ? "error" : "info"}>
      {error ? message(error) : "Hay un envío pendiente de confirmar. Puedes recuperarlo sin duplicar el turno."}
      <p className="pending-question">{session.pending.question}</p>
      {terminal ? <Button onClick={fresh}>Nueva conversación</Button> : editable ? <Button onClick={() => editPending(error instanceof ApiError && error.code === "search_mode_unavailable")}>{error instanceof ApiError && error.code === "search_mode_unavailable" ? "Usar modo semántico" : "Editar pregunta"}</Button> : <Button onClick={() => void send(session.pending!)}>Reintentar el mismo envío</Button>}
    </Alert>}
    <form className="chat-compose" aria-label="Pregunta al asistente" onSubmit={event => { event.preventDefault(); submit(); }}>
      <details className="chat-filters"><summary>Modo y filtros de la próxima pregunta</summary>
        <fieldset disabled={busy || loading || !!session.pending || !!loadError || cursor !== null}><legend className="sr-only">Recuperación</legend>
          <label>Modo<select value={filters.mode} onChange={e => setFilters({ ...filters, mode: e.target.value as Criteria["mode"] })}>
            <option value="semantic">Semántica</option><option value="lexical" disabled={!bm25}>Léxica (BM25)</option><option value="hybrid" disabled={!bm25}>Híbrida</option>
          </select></label>
          <label>Documentos<select value={filters.document_type} onChange={e => setFilters({ ...filters, document_type: e.target.value as Criteria["document_type"], publication_type: "" })}>
            <option value="all">Publicaciones y patentes</option><option value="publication">Publicaciones científicas</option><option value="patent">Patentes y solicitudes</option>
          </select></label>
          <label>Tipo<select value={filters.publication_type} onChange={e => setFilters({ ...filters, publication_type: e.target.value })}><option value="">Todos los tipos</option>{corpus?.publication_types.filter(type => filters.document_type === "all" || (filters.document_type === "patent" ? type === "patent" : type !== "patent")).map(type => <option key={type} value={type}>{typeLabel(type)}</option>)}</select></label>
          <label>Desde<input type="date" value={filters.date_from} onChange={e => setFilters({ ...filters, date_from: e.target.value })} /></label>
          <label>Hasta<input type="date" value={filters.date_to} onChange={e => setFilters({ ...filters, date_to: e.target.value })} /></label>
        </fieldset>
      </details>
      {invalidDates && <p role="alert" className="field-error">La fecha inicial debe ser anterior o igual a la final.</p>}
      <label htmlFor="chat-question">Tu pregunta</label>
      <textarea id="chat-question" ref={input} value={question} maxLength={1000} rows={3}
        disabled={busy || loading || !!session.pending} required placeholder="Escribe una pregunta sobre la colección…"
        aria-describedby="chat-help" onChange={e => setQuestion(e.target.value)} />
      <div className="chat-send-row"><span className="muted small">{question.length}/1000</span><Button type="submit" variant="contained" disabled={!canSend || !question.trim()}>{busy ? "Preparando respuesta…" : "Enviar pregunta"}</Button></div>
      <p id="chat-help" className="muted small">Cada pregunta recupera fuentes de nuevo. En un seguimiento, menciona el tema o documento para encontrar contexto útil.</p>
      <p className="chat-privacy">Al enviar, Gemini recibe tu pregunta, fragmentos de la colección y hasta cuatro turnos recientes. El historial se guarda localmente. «Nueva conversación» inicia otro hilo y conserva los anteriores.</p>
    </form>
  </section>;
}

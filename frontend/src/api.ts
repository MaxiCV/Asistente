export type Document = {
  document_type: "publication" | "patent";
  document_id: string;
  title: string;
  authors: { name: string }[];
  publication_date: string | null;
  publication_type: string | null;
  language: string | null;
  doi: string | null;
  source_url: string;
  abstract: string | null;
  content_level: "abstract" | "metadata";
  technology: string;
  evidence: string;
  identities: {
    openalex_id?: string;
    publication_id?: string;
    applicants?: string[];
    snapshot_id: string;
    retrieved_at: string;
  }[];
};
export type Corpus = {
  manifest: { bm25: unknown | null } | null;
  index_generation: string;
  document_count: number;
  abstract_count: number;
  published_at: string;
  publication_types: string[];
  maintenance_status_unavailable: boolean;
  last_run: { status: "running" | "succeeded" | "failed" } | null;
};
export type Criteria = {
  document_type: "publication" | "patent" | "all";
  mode: "semantic" | "lexical" | "hybrid";
  q: string;
  date_from: string;
  date_to: string;
  publication_type: string;
};
export type SearchRequest = Criteria & {
  page: number;
  index_generation?: string;
  attempt: number;
};
export type SearchResponse = {
  mode: Criteria["mode"];
  matched_document_count: number;
  index_generation: string;
  results: { document: Document; score: number }[];
  page: number;
  page_size: number;
  has_more: boolean;
  filtered_document_count: number;
};
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
  ) {
    super(message);
  }
}
export async function request<T>(
  path: string,
  signal?: AbortSignal,
  options: { method?: "GET" | "POST"; body?: unknown; timeoutMs?: number } = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/v1/${path}`, {
      method: options.method ?? "GET",
      headers: options.body === undefined ? undefined : { "Content-Type": "application/json" },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: signal
        ? AbortSignal.any([signal, AbortSignal.timeout(options.timeoutMs ?? 30000)])
        : AbortSignal.timeout(options.timeoutMs ?? 30000),
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ApiError(
      0,
      "No pudimos conectar con la aplicación local. Comprueba que esté iniciada y reintenta.",
    );
  }
  let data;
  try {
    data = await response.json();
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ApiError(
      response.status,
      "La aplicación local no devolvió una respuesta válida. Comprueba que haya terminado de iniciar y reintenta.",
    );
  }
  if (!response.ok)
    throw new ApiError(
      response.status,
      typeof data?.detail?.message === "string"
        ? data.detail.message
        : "No se pudo completar la consulta. Revisa los filtros e inténtalo otra vez.",
      typeof data?.detail?.code === "string" ? data.detail.code : undefined,
    );
  return data as T;
}
export function searchPath(criteria: SearchRequest) {
  const params = new URLSearchParams({
    q: criteria.q,
    mode: criteria.mode,
    document_type: criteria.document_type,
    page: String(criteria.page),
    page_size: "10",
  });
  for (const key of [
    "date_from",
    "date_to",
    "publication_type",
    "index_generation",
  ] as const) {
    if (criteria[key]) params.set(key, criteria[key]);
  }
  return `documents?${params}`;
}
export const typeLabel = (value: string | null) =>
  ({
    article: "Artículo",
    patent: "Patente / solicitud",
    "conference-paper": "Ponencia de congreso",
    other: "Otra publicación",
    review: "Revisión",
    dissertation: "Tesis",
    "book-chapter": "Capítulo de libro",
    preprint: "Prepublicación",
    "proceedings-article": "Artículo de congreso",
  })[value ?? ""] ??
  value ??
  "Tipo sin informar";
export const dateLabel = (value: string | null) =>
  value
    ? new Intl.DateTimeFormat("es-CL", {
        dateStyle: "medium",
        timeZone: "UTC",
      }).format(new Date(value))
    : "Fecha sin informar";
export function reference(document: Document) {
  return `${document.authors.map((a) => a.name).join(", ") || "Autoría sin informar"}. (${document.publication_date?.slice(0, 4) ?? "s. f."}). ${document.title}. ${document.doi ? `https://doi.org/${document.doi}` : document.source_url}`;
}

export type ChatRequest = {
  request_id: string;
  question: string;
  conversation_id?: string;
  index_generation?: string;
  mode: Criteria["mode"];
  document_type: Criteria["document_type"];
  date_from?: string;
  date_to?: string;
  publication_type?: string;
};
export type Citation = {
  marker: number;
  document_id: string;
  passage_id: string;
  title: string;
  document_type: "publication" | "patent";
  content_level: "abstract" | "metadata";
  source_url: string;
  doi: string | null;
  publication_id: string | null;
  publication_date: string | null;
};
export type ChatResponse = {
  conversation_id: string;
  turn_id: string;
  turn_index: number;
  index_generation: string;
  mode: Criteria["mode"];
  status: "answered" | "insufficient_evidence";
  evidence_level: "abstract" | "metadata_only" | "mixed" | "none";
  answer: string;
  citations: Citation[];
  context: { rank: number; document_id: string; passage_id: string; text_sha256: string; cited: boolean }[];
  model: string | null;
  created_at: string;
};
export type ChatTurn = { request: ChatRequest; response: ChatResponse };
export type ConversationResponse = {
  conversation_id: string;
  index_generation: string;
  turns: ChatTurn[];
  next_cursor: number | null;
};

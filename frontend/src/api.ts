export type Document = {
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
    openalex_id: string;
    snapshot_id: string;
    retrieved_at: string;
  }[];
};
export type Corpus = {
  index_generation: string;
  document_count: number;
  abstract_count: number;
  published_at: string;
  publication_types: string[];
  maintenance_status_unavailable: boolean;
  last_run: { status: "running" | "succeeded" | "failed" } | null;
};
export type Criteria = {
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
  ) {
    super(message);
  }
}
export async function request<T>(
  path: string,
  signal?: AbortSignal,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/v1/${path}`, {
      signal: signal
        ? AbortSignal.any([signal, AbortSignal.timeout(30000)])
        : AbortSignal.timeout(30000),
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ApiError(
      0,
      "No pudimos conectar con la aplicación local. Comprueba que esté iniciada y reintenta.",
    );
  }
  const data = await response.json();
  if (!response.ok)
    throw new ApiError(
      response.status,
      typeof data.detail?.message === "string"
        ? data.detail.message
        : "No se pudo completar la consulta. Revisa los filtros e inténtalo otra vez.",
    );
  return data as T;
}
export function searchPath(criteria: SearchRequest) {
  const params = new URLSearchParams({
    q: criteria.q,
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

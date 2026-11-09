import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Skeleton,
  Snackbar,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import {
  ApiError,
  dateLabel,
  reference,
  request,
  searchPath,
  typeLabel,
} from "./api";
import type {
  Corpus,
  Criteria,
  Document,
  SearchRequest,
  SearchResponse,
} from "./api";

const initial: Criteria = {
  q: "",
  date_from: "",
  date_to: "",
  publication_type: "",
};
const examples = [
  "Detección de caídas con cámaras",
  "Wearable fall detection at home",
];
const technology: Record<string, string> = {
  camara: "Cámara",
  vestible: "Dispositivo vestible",
  ambiente: "Sensores del ambiente",
  mixta: "Mixta",
  ND: "No determinada",
};
const evidence: Record<string, string> = {
  laboratorio: "Laboratorio",
  simulada: "Simulada",
  real_hogar: "Entorno real del hogar",
  mixta: "Mixta",
  ND: "No determinada",
};

const filterKeys = ["date_from", "date_to", "publication_type"] as const;
type FilterKey = (typeof filterKeys)[number];

function Icon({ name }: { name: "search" | "arrow" | "close" | "book" }) {
  const paths = {
    search: (
      <>
        <circle cx="10.5" cy="10.5" r="6.5" />
        <path d="m16 16 4 4" />
      </>
    ),
    arrow: (
      <>
        <path d="M7 17 17 7M7 7h10v10" />
      </>
    ),
    close: <path d="m6 6 12 12M18 6 6 18" />,
    book: (
      <>
        <path d="M12 5v15M12 5C8 2 4 3 2 4v15c3-1 6-1 10 1 4-2 7-2 10-1V4c-2-1-6-2-10 1Z" />
      </>
    ),
  };
  return (
    <svg
      className="icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {paths[name]}
    </svg>
  );
}

function Failure({ error, retry }: { error: Error; retry: () => void }) {
  return (
    <Alert
      severity="error"
      action={
        <Button color="inherit" onClick={retry}>
          {error instanceof ApiError && error.status === 409
            ? "Repetir búsqueda"
            : "Reintentar"}
        </Button>
      }
    >
      {error.message}
    </Alert>
  );
}

function Detail({
  selected,
  close,
  restart,
}: {
  selected: { id: string; generation: string } | null;
  close: () => void;
  restart: () => void;
}) {
  const theme = useTheme();
  const mobile = useMediaQuery(theme.breakpoints.down("sm"));
  const [copied, setCopied] = useState(false);
  const [copying, setCopying] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const detail = useQuery({
    queryKey: ["document", selected],
    enabled: !!selected,
    queryFn: ({ signal }) =>
      request<{ document: Document }>(
        `documents/${selected!.id}?index_generation=${encodeURIComponent(selected!.generation)}`,
        signal,
      ),
  });
  const document = detail.data?.document;
  async function copy() {
    setCopying(true);
    setCopyFailed(false);
    let timeout: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        navigator.clipboard.writeText(reference(document!)),
        new Promise<never>((_, reject) => {
          timeout = setTimeout(
            () => reject(new Error("clipboard timeout")),
            2000,
          );
        }),
      ]);
      setCopied(true);
    } catch {
      setCopyFailed(true);
    } finally {
      clearTimeout(timeout);
      setCopying(false);
    }
  }
  return (
    <>
      <Dialog
        className="reading-dialog"
        open={!!selected}
        onClose={close}
        fullScreen={mobile}
        fullWidth
        maxWidth="md"
        aria-labelledby="document-title"
      >
        <DialogTitle id="document-title" className="reading-header">
          <span>Ficha de la publicación</span>
          <IconButton aria-label="Cerrar ficha" onClick={close}>
            <Icon name="close" />
          </IconButton>
        </DialogTitle>
        <DialogContent dividers className="reading-content">
          {detail.isPending && (
            <div role="status" aria-label="Cargando publicación">
              <Skeleton height={80} />
              <Skeleton height={180} />
            </div>
          )}
          {detail.isError && (
            <Failure
              error={detail.error}
              retry={() => {
                if (
                  detail.error instanceof ApiError &&
                  detail.error.status === 409
                ) {
                  close();
                  restart();
                } else void detail.refetch();
              }}
            />
          )}
          {document && (
            <article className="detail">
              <p className="metadata">
                {typeLabel(document.publication_type)} ·{" "}
                {dateLabel(document.publication_date)} ·{" "}
                {document.language?.toUpperCase() ?? "Idioma sin informar"}
              </p>
              <h2>{document.title}</h2>
              <p className="authors">
                {document.authors.map((a) => a.name).join(", ") ||
                  "Autoría sin informar"}
              </p>
              <h3>
                {document.abstract
                  ? "Resumen disponible"
                  : "Sin resumen disponible"}
              </h3>
              <p className="abstract">
                {document.abstract ??
                  "Esta publicación solo contiene metadatos. La fuente no proporcionó un resumen; puedes consultar el documento original desde el enlace de la fuente."}
              </p>
              <dl className="classification">
                <div>
                  <dt>Tecnología</dt>
                  <dd>{technology[document.technology] ?? "No determinada"}</dd>
                </div>
                <div>
                  <dt>Tipo de evidencia</dt>
                  <dd>{evidence[document.evidence] ?? "No determinada"}</dd>
                </div>
              </dl>
              <p className="muted small">
                Clasificación preliminar basada en el título y el resumen
                disponibles.
              </p>
              <h3>Fuente y procedencia</h3>
              <p className="source-links">
                <a href={document.source_url} target="_blank" rel="noreferrer">
                  Abrir fuente original <Icon name="arrow" />
                </a>
                {document.doi && (
                  <>
                    <a
                      href={`https://doi.org/${document.doi}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Consultar DOI <Icon name="arrow" />
                    </a>
                  </>
                )}
              </p>
              <ul className="provenance">
                {document.identities.map((identity) => (
                  <li key={`${identity.snapshot_id}-${identity.openalex_id}`}>
                    <a
                      href={identity.openalex_id}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {identity.openalex_id}
                    </a>
                    <span>
                      Capturado el {dateLabel(identity.retrieved_at)} · Lote{" "}
                      {identity.snapshot_id}
                    </span>
                  </li>
                ))}
              </ul>
              <h3>Referencia</h3>
              <p className="reference" tabIndex={0}>
                {reference(document)}
              </p>
              {copyFailed && (
                <Alert severity="info">
                  El navegador no permitió copiar. Selecciona y copia el texto
                  de la referencia de arriba.
                </Alert>
              )}
            </article>
          )}
        </DialogContent>
        <DialogActions className="reading-actions">
          <Button onClick={close}>Cerrar</Button>
          {document && (
            <Button
              variant="contained"
              disabled={copying}
              onClick={() => void copy()}
            >
              {copying ? "Copiando…" : "Copiar referencia"}
            </Button>
          )}
        </DialogActions>
      </Dialog>
      <Snackbar
        anchorOrigin={{ vertical: "top", horizontal: "center" }}
        open={copied}
        autoHideDuration={3000}
        onClose={() => setCopied(false)}
        message="Referencia copiada"
      />
    </>
  );
}

export default function App() {
  const compact = useMediaQuery("(max-width:700px)");
  const [draft, setDraft] = useState<Criteria>(initial);
  const [criteria, setCriteria] = useState<SearchRequest | null>(null);
  const [selected, setSelected] = useState<{
    id: string;
    generation: string;
  } | null>(null);
  const resultsHeading = useRef<HTMLHeadingElement>(null);
  const queryInput = useRef<HTMLInputElement>(null);
  const corpus = useQuery({
    queryKey: ["corpus"],
    queryFn: ({ signal }) => request<Corpus>("corpus", signal),
    refetchInterval: 15000,
  });
  const ready = useQuery({
    queryKey: ["ready"],
    queryFn: ({ signal }) => request<{ status: string }>("ready", signal),
    refetchInterval: 15000,
  });
  const search = useQuery({
    queryKey: ["search", criteria],
    enabled: !!criteria,
    queryFn: ({ signal }) =>
      request<SearchResponse>(searchPath(criteria!), signal),
  });
  const data = search.data;
  const active = corpus.data;
  const disabled =
    ready.isPending || ready.isError || corpus.isPending || corpus.isError;
  function submit(value = draft) {
    setCriteria({
      ...value,
      q: value.q.trim(),
      index_generation: undefined,
      page: 1,
      attempt: (criteria?.attempt ?? 0) + 1,
    });
    resultsHeading.current?.focus();
  }
  function restart() {
    if (criteria) submit(criteria);
  }
  function changePage(page: number) {
    if (criteria && data)
      setCriteria({
        ...criteria,
        page,
        index_generation: data.index_generation,
      });
    resultsHeading.current?.focus();
  }
  const invalidDates =
    !!draft.date_from && !!draft.date_to && draft.date_from > draft.date_to;
  const pendingFilters =
    !!criteria && filterKeys.some((key) => draft[key] !== criteria[key]);
  const hasFilters = filterKeys.some((key) => draft[key] || criteria?.[key]);
  const appliedFilters = criteria
    ? filterKeys.filter((key) => criteria[key])
    : [];
  function clearFilters(key?: FilterKey) {
    const reset = key
      ? { [key]: "" }
      : { date_from: "", date_to: "", publication_type: "" };
    setDraft((current) => ({ ...current, ...reset }));
    if (criteria) submit({ ...criteria, ...reset });
  }
  function filterLabel(key: FilterKey) {
    if (!criteria) return "";
    return key === "publication_type"
      ? typeLabel(criteria[key])
      : `${key === "date_from" ? "Desde" : "Hasta"} ${dateLabel(criteria[key])}`;
  }
  const resultStart = data?.results.length
    ? (data.page - 1) * data.page_size + 1
    : 0;
  const resultEnd = data
    ? resultStart + Math.max(0, data.results.length - 1)
    : 0;
  return (
    <div className="shell">
      <a className="skip-link" href="#query">
        Ir a la búsqueda
      </a>
      <header className="header">
        <a className="brand" href="/" aria-label="Observatorio, inicio">
          <span aria-hidden="true" className="brand-mark">
            o.
          </span>
          <span>
            Observatorio
            <span className="brand-caption">Biblioteca de investigación</span>
          </span>
        </a>
        <span
          className={`connection ${disabled ? "unavailable" : ""}`}
          role="status"
        >
          {ready.isPending || corpus.isPending
            ? "Conectando…"
            : disabled
              ? "Búsqueda no disponible"
              : "Colección local disponible"}
        </span>
      </header>
      <main>
        <section className="intro" aria-labelledby="page-title">
          <h1 id="page-title">Literatura sobre detección de caídas</h1>
          <p className="intro-copy">
            Explora estudios sobre detección de caídas en el hogar. Busca por
            significado, revisa los resúmenes y conserva sus referencias.
          </p>
        </section>
        {(corpus.isError || ready.isError) && (
          <div className="notice">
            <Failure
              error={
                corpus.error ??
                new Error(
                  "La búsqueda no está lista. El modelo o la colección local no están disponibles.",
                )
              }
              retry={() => {
                void corpus.refetch();
                void ready.refetch();
              }}
            />
          </div>
        )}
        {active?.last_run?.status === "failed" && (
          <div className="notice">
            <Alert severity="warning">
              La última actualización no terminó. Puedes seguir consultando la
              colección publicada.
            </Alert>
          </div>
        )}
        {active?.last_run?.status === "running" && (
          <div className="notice">
            <Alert severity="info">
              Hay una actualización en curso. La colección publicada sigue
              disponible.
            </Alert>
          </div>
        )}
        {active?.maintenance_status_unavailable && (
          <div className="notice">
            <Alert severity="warning">
              No se pudo verificar todo el historial de actualizaciones.
            </Alert>
          </div>
        )}
        <form
          aria-label="Búsqueda de publicaciones"
          onSubmit={(event) => {
            event.preventDefault();
            if (
              !disabled &&
              !search.isFetching &&
              !invalidDates &&
              draft.q.trim()
            )
              submit();
          }}
        >
          <div className="search-panel">
            <label htmlFor="query">¿Qué quieres investigar?</label>
            <div className="query-row">
              <div className="query-input">
                <Icon name="search" />
                <input
                  id="query"
                  ref={queryInput}
                  type="search"
                  maxLength={300}
                  required
                  value={draft.q}
                  placeholder="Ej. detectar caídas con sensores sin cámaras"
                  onChange={(e) => setDraft({ ...draft, q: e.target.value })}
                />
              </div>
              <Button
                type="submit"
                variant="contained"
                disabled={
                  disabled ||
                  search.isFetching ||
                  !draft.q.trim() ||
                  invalidDates
                }
              >
                {search.isFetching ? "Buscando…" : "Buscar"}
              </Button>
            </div>
            <div className="examples">
              <span>Prueba:</span>
              {examples.map((example) => (
                <button
                  type="button"
                  key={example}
                  disabled={disabled || search.isFetching}
                  onClick={() => {
                    const next = { ...draft, q: example };
                    setDraft(next);
                    if (!invalidDates) submit(next);
                  }}
                >
                  {example}
                </button>
              ))}
            </div>
          </div>
          <div className="workspace">
            <aside className="sidebar">
              <details className="filters" open={!compact}>
                <summary>
                  Filtros de publicación{" "}
                  {appliedFilters.length > 0 && (
                    <span
                      className="filter-count"
                      aria-label={`${appliedFilters.length} filtros aplicados`}
                    >
                      {appliedFilters.length}
                    </span>
                  )}
                </summary>
                <div className="filter-fields">
                  <label htmlFor="date-from">
                    Desde
                    <input
                      id="date-from"
                      type="date"
                      aria-invalid={invalidDates}
                      aria-describedby={
                        invalidDates ? "date-error" : "date-help"
                      }
                      value={draft.date_from}
                      onChange={(e) =>
                        setDraft({ ...draft, date_from: e.target.value })
                      }
                    />
                  </label>
                  <label htmlFor="date-to">
                    Hasta
                    <input
                      id="date-to"
                      type="date"
                      aria-invalid={invalidDates}
                      aria-describedby={
                        invalidDates ? "date-error" : "date-help"
                      }
                      value={draft.date_to}
                      onChange={(e) =>
                        setDraft({ ...draft, date_to: e.target.value })
                      }
                    />
                  </label>
                  {invalidDates && (
                    <p role="alert" id="date-error" className="field-error">
                      La fecha inicial debe ser anterior o igual a la final.
                    </p>
                  )}
                  <label htmlFor="publication-type">
                    Tipo
                    <select
                      id="publication-type"
                      value={draft.publication_type}
                      onChange={(e) =>
                        setDraft({ ...draft, publication_type: e.target.value })
                      }
                    >
                      <option value="">Todas las publicaciones</option>
                      {active?.publication_types.map((type) => (
                        <option key={type} value={type}>
                          {typeLabel(type)}
                        </option>
                      ))}
                    </select>
                  </label>
                  {pendingFilters && (
                    <p className="filter-pending" role="status">
                      Cambios sin aplicar
                    </p>
                  )}
                  <Button
                    type="submit"
                    variant="outlined"
                    disabled={
                      disabled ||
                      !draft.q.trim() ||
                      invalidDates ||
                      search.isFetching
                    }
                  >
                    Aplicar filtros
                  </Button>
                  <button
                    className="text-button"
                    type="button"
                    disabled={!hasFilters || disabled || search.isFetching}
                    onClick={() => clearFilters()}
                  >
                    Limpiar filtros
                  </button>
                  <p id="date-help" className="muted small">
                    Las fechas incluyen ambos extremos. Si filtras por fecha, se
                    omiten los documentos sin fecha conocida.
                  </p>
                </div>
              </details>
              <section className="coverage" aria-labelledby="coverage-title">
                <h2 id="coverage-title">En la colección</h2>
                {active && !corpus.isError ? (
                  <>
                    <dl className="corpus-summary">
                      <div>
                        <dt>Publicaciones</dt>
                        <dd>{active.document_count}</dd>
                      </div>
                      <div>
                        <dt>Con resumen</dt>
                        <dd>{active.abstract_count}</dd>
                      </div>
                      <div>
                        <dt>Solo metadatos</dt>
                        <dd>{active.document_count - active.abstract_count}</dd>
                      </div>
                    </dl>
                    <p className="muted small">
                      Publicada el {dateLabel(active.published_at)}
                      <br />
                      Fuente: OpenAlex · Español e inglés
                    </p>
                  </>
                ) : (
                  <p className="muted">
                    {corpus.isPending
                      ? "Consultando colección…"
                      : "Estado no disponible"}
                  </p>
                )}
              </section>
            </aside>
            <section
              className="results"
              aria-labelledby="results-title"
              aria-busy={!!criteria && search.isFetching}
            >
              <div className="results-heading">
                <h2 id="results-title" ref={resultsHeading} tabIndex={-1}>
                  {criteria
                    ? "Resultados de búsqueda"
                    : "Una pregunta, distintas perspectivas"}
                </h2>
                {data && data.results.length > 0 && (
                  <span className="muted small">Página {data.page}</span>
                )}
              </div>
              {criteria && (
                <div className="applied">
                  <p>
                    Consulta: <strong>{criteria.q}</strong>
                  </p>
                  {appliedFilters.length > 0 && (
                    <div
                      className="applied-filters"
                      role="group"
                      aria-label="Filtros aplicados"
                    >
                      {appliedFilters.map((key) => (
                        <button
                          type="button"
                          key={key}
                          className="filter-chip"
                          disabled={disabled || search.isFetching}
                          onClick={() => clearFilters(key)}
                          aria-label={`Quitar filtro: ${filterLabel(key)}`}
                        >
                          {filterLabel(key)}
                          <Icon name="close" />
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
              {data &&
                active &&
                data.index_generation !== active.index_generation && (
                  <Alert
                    severity="info"
                    action={
                      <Button color="inherit" onClick={restart}>
                        Actualizar
                      </Button>
                    }
                  >
                    Hay una nueva versión de la colección. Estos resultados
                    conservan la versión de tu consulta.
                  </Alert>
                )}
              {!criteria && (
                <div className="welcome">
                  <span className="reading-symbol">
                    <Icon name="book" />
                  </span>
                  <h3>Empieza por una idea de investigación</h3>
                  <p>
                    Puedes escribir en español o en inglés. Los resultados se
                    ordenan por similitud semántica y cada publicación aparece
                    una sola vez.
                  </p>
                  <p className="muted small">
                    Los documentos sin resumen se buscan a partir de su título.
                  </p>
                  <Button
                    variant="outlined"
                    type="button"
                    onClick={() => queryInput.current?.focus()}
                  >
                    Escribir una consulta
                  </Button>
                </div>
              )}
              {criteria && search.isFetching && (
                <div role="status" aria-label="Buscando publicaciones">
                  {[0, 1, 2].map((n) => (
                    <div className="result-skeleton" key={n}>
                      <Skeleton width="85%" height={36} />
                      <Skeleton />
                      <Skeleton width="65%" />
                    </div>
                  ))}
                </div>
              )}
              {criteria && search.isError && (
                <Failure
                  error={search.error}
                  retry={() =>
                    search.error instanceof ApiError &&
                    search.error.status === 409
                      ? restart()
                      : void search.refetch()
                  }
                />
              )}
              {data && !search.isFetching && !search.isError && (
                <>
                  <div className="results-summary">
                    <p role="status">
                      {data.results.length > 0
                        ? `${resultStart}–${resultEnd} de ${data.filtered_document_count} publicaciones`
                        : "0 publicaciones"}
                    </p>
                    <p className="results-note">
                      Ordenadas por similitud con tu consulta; esto no garantiza
                      su pertinencia.
                    </p>
                  </div>
                  {data.results.length === 0 ? (
                    <div className="welcome">
                      <h3>No hay publicaciones para estos filtros</h3>
                      <p>
                        Amplía el intervalo de fechas o selecciona todos los
                        tipos de publicación y vuelve a buscar.
                      </p>
                      {appliedFilters.length > 0 && (
                        <Button
                          variant="outlined"
                          type="button"
                          disabled={disabled}
                          onClick={() => clearFilters()}
                        >
                          Buscar sin filtros
                        </Button>
                      )}
                    </div>
                  ) : (
                    <ol className="result-list">
                      {data.results.map(({ document }) => (
                        <li key={document.document_id}>
                          <article className="result">
                            <div className="result-meta">
                              <span>
                                {typeLabel(document.publication_type)} ·{" "}
                                {document.publication_date?.slice(0, 4) ??
                                  "Sin fecha"}
                              </span>
                              <span
                                className={`content-tag ${document.abstract ? "" : "metadata-only"}`}
                              >
                                {document.abstract
                                  ? "Con resumen"
                                  : "Solo metadatos"}
                              </span>
                            </div>
                            <h3>
                              <button
                                type="button"
                                onClick={() =>
                                  setSelected({
                                    id: document.document_id,
                                    generation: data.index_generation,
                                  })
                                }
                              >
                                {document.title}
                              </button>
                            </h3>
                            <p className="authors small">
                              {document.authors
                                .slice(0, 3)
                                .map((a) => a.name)
                                .join(", ") || "Autoría sin informar"}
                              {document.authors.length > 3 && " y otros"}
                            </p>
                            <p className="excerpt">
                              {document.abstract ??
                                "Sin resumen disponible. Revisa los metadatos y la fuente original en la ficha."}
                            </p>
                            <button
                              className="text-button"
                              type="button"
                              onClick={() =>
                                setSelected({
                                  id: document.document_id,
                                  generation: data.index_generation,
                                })
                              }
                            >
                              Ver ficha y referencia <Icon name="arrow" />
                            </button>
                          </article>
                        </li>
                      ))}
                    </ol>
                  )}
                  {data.results.length > 0 && (
                    <nav
                      className="pagination"
                      aria-label="Páginas de resultados"
                    >
                      <Button
                        variant="outlined"
                        type="button"
                        disabled={data.page === 1 || search.isFetching}
                        onClick={() => changePage(data.page - 1)}
                      >
                        Anterior
                      </Button>
                      <span>
                        Página {data.page} de{" "}
                        {Math.max(
                          1,
                          Math.ceil(
                            data.filtered_document_count / data.page_size,
                          ),
                        )}
                      </span>
                      <Button
                        variant="outlined"
                        type="button"
                        disabled={!data.has_more || search.isFetching}
                        onClick={() => changePage(data.page + 1)}
                      >
                        Siguiente
                      </Button>
                    </nav>
                  )}
                </>
              )}
            </section>
          </div>
        </form>
      </main>
      <footer>
        Observatorio · Detección de caídas en el hogar
        <span>Machine learning y deep learning · Colección local</span>
      </footer>
      <Detail
        key={selected?.id ?? "closed"}
        selected={selected}
        close={() => setSelected(null)}
        restart={restart}
      />
    </div>
  );
}

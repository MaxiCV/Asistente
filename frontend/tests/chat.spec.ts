import { test, expect, type Page } from "@playwright/test";

const generation = "test_corpus";
const documentId = "00000000-0000-0000-0000-000000000001";
const passageId = "00000000-0000-0000-0000-000000000002";
const conversationId = "00000000-0000-0000-0000-000000000003";
const doc = {
  document_id: documentId, document_type: "publication", title: "Estudio de sensores para detectar caídas",
  authors: [{ name: "Autora de prueba" }], publication_date: "2025-01-01", publication_type: "article",
  language: "es", doi: null, source_url: "https://example.org/study", abstract: "Resumen sintético para pruebas de interfaz.",
  content_level: "abstract", technology: "ND", evidence: "ND",
  identities: [{ openalex_id: "https://openalex.org/W1", snapshot_id: "test", retrieved_at: "2026-11-15T00:00:00Z" }],
};
function response(body: any, index = 1) {
  return {
    conversation_id: conversationId, turn_id: body.request_id, turn_index: index,
    index_generation: generation, mode: body.mode, status: "answered", evidence_level: "abstract",
    answer: "El resumen describe sensores para detectar caídas [1].", model: "test-provider", created_at: "2026-11-15T00:00:00Z",
    citations: [{ marker: 1, document_id: documentId, passage_id: passageId, title: doc.title, content_level: "abstract", document_type: "publication", source_url: doc.source_url, doi: null, publication_id: null, publication_date: doc.publication_date }],
    context: [{ rank: 1, document_id: documentId, passage_id: passageId, text_sha256: "a".repeat(64), cited: true }],
  };
}
async function setup(page: Page, bm25 = true) {
  await page.route("**/api/v1/ready", route => route.fulfill({ json: { status: "ready", chat: true } }));
  await page.route("**/api/v1/corpus", route => route.fulfill({ json: {
    index_generation: generation, document_count: 3, abstract_count: 2, published_at: "2026-11-15T00:00:00Z",
    publication_types: ["article", "patent"], maintenance_status_unavailable: false, last_run: null,
    manifest: { bm25: bm25 ? {} : null },
  } }));
  await page.route("**/api/v1/documents/*", route => route.fulfill({ json: { index_generation: generation, document: doc } }));
}

test("envía POST, abre citas, recupera el hilo y empieza otro", async ({ page }) => {
  await setup(page);
  const turns: any[] = [];
  await page.route("**/api/v1/chat", async route => {
    expect(route.request().method()).toBe("POST");
    const body = route.request().postDataJSON();
    const result = response(body, turns.length + 1);
    turns.push({ request: body, response: result });
    await route.fulfill({ json: result });
  });
  await page.route(`**/api/v1/chat/${conversationId}*`, route => route.fulfill({ json: {
    conversation_id: conversationId, index_generation: generation, turns, next_cursor: null,
  } }));
  await page.goto("/");
  await page.getByRole("button", { name: "Conversación", exact: true }).click();
  await page.getByLabel("Tu pregunta", { exact: true }).fill("¿Qué sensores se estudian?");
  await page.getByRole("button", { name: "Enviar pregunta" }).click();
  await expect(page.getByText("Basado en resúmenes", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Respuesta 1", exact: true })).toBeFocused();
  expect(turns[0].request.mode).toBe("hybrid");
  await page.getByRole("button", { name: `Fuente 1: ${doc.title}`, exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("dialog")).toContainText(doc.abstract);
  await page.getByRole("button", { name: "Cerrar", exact: true }).click();
  await page.reload();
  await page.getByRole("button", { name: "Conversación", exact: true }).click();
  await expect(page.getByText("¿Qué sensores se estudian?", { exact: true })).toBeVisible();
  await page.getByLabel("Tu pregunta", { exact: true }).fill("¿Qué información aportan sobre sensores en el hogar?");
  await page.getByRole("button", { name: "Enviar pregunta" }).click();
  await expect(page.getByRole("heading", { name: "Respuesta 2" })).toBeVisible();
  expect(turns[1].request.index_generation).toBe(generation);
  expect(turns[1].request.conversation_id).toBe(conversationId);
  await page.getByRole("button", { name: "Nueva conversación", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Respuesta 1" })).toHaveCount(0);
  expect(JSON.parse(await page.evaluate(() => sessionStorage.getItem("nexo.conversation.v1")!))).toEqual({});
});

test("reintenta un envío fallido con el mismo ID y sin duplicar turnos", async ({ page }) => {
  await setup(page);
  const bodies: any[] = [];
  await page.route("**/api/v1/chat", async route => {
    const body = route.request().postDataJSON(); bodies.push(body);
    if (bodies.length === 1) await route.abort("failed");
    else if (bodies.length === 2) await route.fulfill({ status: 500, body: "" });
    else await route.fulfill({ json: response(body) });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Conversación", exact: true }).click();
  await page.getByLabel("Tu pregunta", { exact: true }).fill("¿Qué sensores se usan?");
  await page.getByRole("button", { name: "Enviar pregunta" }).click();
  await page.getByRole("button", { name: "Reintentar el mismo envío" }).click();
  await expect(page.getByText(/La aplicación local no devolvió una respuesta válida/)).toBeVisible();
  await page.getByRole("button", { name: "Reintentar el mismo envío" }).click();
  await expect(page.getByRole("heading", { name: "Respuesta 1" })).toBeVisible();
  expect(bodies).toHaveLength(3); expect(bodies[0]).toEqual(bodies[1]); expect(bodies[0]).toEqual(bodies[2]);
});

test("una respuesta tardía no repuebla una conversación abandonada", async ({ page }) => {
  await setup(page);
  let started!: () => void;
  const arriving = new Promise<void>(resolve => { started = resolve; });
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/v1/chat", async route => {
    const body = route.request().postDataJSON(); started(); await pending;
    await route.fulfill({ json: response(body) }).catch(() => {});
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Conversación", exact: true }).click();
  await page.getByLabel("Tu pregunta", { exact: true }).fill("Primera pregunta");
  await page.getByRole("button", { name: "Enviar pregunta" }).click();
  await arriving;
  await page.getByRole("button", { name: "Nueva conversación", exact: true }).click();
  release();
  await expect(page.getByRole("heading", { name: "Una pregunta, con evidencia a mano" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Respuesta 1" })).toHaveCount(0);
});

test("filtro documental limpiable y vacío léxico explicado", async ({ page }) => {
  await setup(page);
  await page.route("**/api/v1/documents?*", async route => {
    const params = new URL(route.request().url()).searchParams;
    await route.fulfill({ json: { mode: params.get("mode"), filtered_document_count: 3,
      matched_document_count: 0, index_generation: generation, page: 1, page_size: 10, has_more: false, results: [] } });
  });
  await page.goto("/");
  await page.locator("details.filters").evaluate(el => { (el as HTMLDetailsElement).open = true; });
  await page.getByRole("combobox", { name: "Documentos", exact: true }).selectOption("patent");
  await expect(page.getByRole("button", { name: "Limpiar filtros", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "Limpiar filtros", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Documentos", exact: true })).toHaveValue("all");
  await page.getByRole("combobox", { name: "Modo de búsqueda", exact: true }).selectOption("lexical");
  await page.locator("#query").fill("términos sin coincidencia");
  await page.getByRole("button", { name: "Buscar", exact: true }).click();
  await expect(page.getByRole("heading", { name: "No hay coincidencias para estos términos" })).toBeVisible();
});

test("la recuperación de modo incompatible cambia a semántico", async ({ page }) => {
  await setup(page);
  const modes: string[] = [];
  await page.route("**/api/v1/documents?*", async route => {
    const mode = new URL(route.request().url()).searchParams.get("mode")!; modes.push(mode);
    if (mode !== "semantic") await route.fulfill({ status: 409, json: { detail: { code: "search_mode_unavailable", message: "Solo semántica" } } });
    else await route.fulfill({ json: { mode, filtered_document_count: 3, matched_document_count: 0, index_generation: generation, page: 1, page_size: 10, has_more: false, results: [] } });
  });
  await page.goto("/");
  await page.locator("details.filters").evaluate(el => { (el as HTMLDetailsElement).open = true; });
  await page.getByRole("combobox", { name: "Modo de búsqueda", exact: true }).selectOption("hybrid");
  await page.locator("#query").fill("fall");
  await page.getByRole("button", { name: "Buscar", exact: true }).click();
  await page.getByRole("button", { name: "Repetir búsqueda", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Modo de búsqueda", exact: true })).toHaveValue("semantic");
  expect(modes).toEqual(["hybrid", "semantic"]);
});

test("en móvil las fechas inválidas se pueden corregir y no hay desborde", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setup(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Conversación", exact: true }).click();
  await page.getByText("Modo y filtros de la próxima pregunta", { exact: true }).click();
  const chat = page.getByRole("form", { name: "Pregunta al asistente" });
  await chat.getByLabel("Desde", { exact: true }).fill("2026-11-15");
  await chat.getByLabel("Hasta", { exact: true }).fill("2025-01-01");
  await expect(chat.getByRole("alert")).toBeVisible();
  await expect(chat.getByLabel("Hasta", { exact: true })).toBeEnabled();
  await chat.getByLabel("Hasta", { exact: true }).fill("2026-11-15");
  await expect(chat.getByRole("alert")).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

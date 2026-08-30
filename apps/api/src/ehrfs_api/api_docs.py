"""Same-origin API reference assets that work without a public CDN."""

from __future__ import annotations

API_DOCS_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="color-scheme" content="light">
    <meta name="description" content="Local OpenAPI reference for the EHR Form Standardization Platform">
    <title>EHRFS API reference</title>
    <link rel="stylesheet" href="/docs/assets/api-docs.css">
    <script type="module" src="/docs/assets/api-docs.js"></script>
  </head>
  <body>
    <header class="hero">
      <div class="hero-inner">
        <p class="eyebrow">EHR evidence control plane</p>
        <h1>API reference</h1>
        <p class="lede">A same-origin view of the running FastAPI OpenAPI contract.</p>
        <nav aria-label="API reference links">
          <a href="/api/v1/openapi.json">OpenAPI JSON</a>
          <a href="/api/v1/health/ready">Readiness</a>
          <a href="http://localhost:3000">Web application</a>
        </nav>
      </div>
    </header>
    <main>
      <section class="summary" aria-labelledby="contract-title">
        <div>
          <p class="eyebrow">Running contract</p>
          <h2 id="contract-title">Endpoints and schemas</h2>
        </div>
        <label class="search">
          <span>Filter operations</span>
          <input id="operation-filter" type="search" placeholder="Path, method, or summary" disabled>
        </label>
      </section>
      <div id="contract-stats" class="stats" aria-live="polite"></div>
      <div id="docs-root" class="operation-list" aria-live="polite">
        <p class="loading">Loading <a href="/api/v1/openapi.json">the OpenAPI contract</a>…</p>
      </div>
      <noscript>
        <p class="error">JavaScript is disabled. The raw contract remains available as
          <a href="/api/v1/openapi.json">OpenAPI JSON</a>.
        </p>
      </noscript>
    </main>
  </body>
</html>
"""

API_DOCS_CSS = """:root {
  color: #17312e;
  background: #f1f5f5;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-synthesis: none;
}
* { box-sizing: border-box; }
body { margin: 0; min-width: 320px; }
a { color: #145f83; font-weight: 700; }
.hero { color: #fff; background: #12384b; border-bottom: 4px solid #fcc958; }
.hero-inner, main { width: min(1120px, calc(100% - 40px)); margin: 0 auto; }
.hero-inner { padding: 38px 0 34px; }
.eyebrow { margin: 0 0 8px; color: #2a769c; font-size: 12px; font-weight: 800; letter-spacing: .1em; text-transform: uppercase; }
.hero .eyebrow { color: #a8cedf; }
h1, h2 { margin: 0; font-family: Georgia, serif; font-weight: 500; }
h1 { font-size: clamp(38px, 6vw, 58px); }
h2 { font-size: 28px; }
.lede { max-width: 680px; margin: 10px 0 20px; color: #d8e6ec; line-height: 1.6; }
nav { display: flex; flex-wrap: wrap; gap: 10px; }
nav a { padding: 9px 12px; color: #fff; border: 1px solid #5f8292; border-radius: 6px; text-decoration: none; }
nav a:hover, nav a:focus-visible { border-color: #fcc958; outline: none; }
main { padding: 34px 0 70px; }
.summary { display: flex; justify-content: space-between; align-items: end; gap: 24px; }
.search { width: min(380px, 100%); color: #526763; font-size: 12px; font-weight: 750; }
.search span { display: block; margin-bottom: 7px; }
.search input { width: 100%; padding: 11px 12px; color: #17312e; background: #fff; border: 1px solid #bdceca; border-radius: 7px; font: inherit; }
.search input:focus { border-color: #246589; outline: 3px solid #24658922; }
.stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 24px 0; }
.stat { padding: 16px; background: #fff; border: 1px solid #d6e1df; border-radius: 8px; box-shadow: 0 5px 18px #163a3410; }
.stat strong { display: block; font-family: Georgia, serif; font-size: 28px; font-weight: 500; }
.stat span { color: #60716e; font-size: 11px; }
.tag-group { margin-top: 26px; }
.tag-group > h3 { margin: 0 0 10px; color: #234946; font-size: 15px; text-transform: capitalize; }
.operation { margin-bottom: 8px; background: #fff; border: 1px solid #d6e1df; border-radius: 7px; overflow: hidden; }
.operation summary { display: grid; grid-template-columns: 76px minmax(200px, .9fr) minmax(220px, 1.2fr); align-items: center; gap: 12px; padding: 13px 15px; cursor: pointer; }
.operation summary:hover { background: #f8fbfa; }
.method { display: inline-flex; justify-content: center; padding: 5px 7px; color: #fff; background: #246589; border-radius: 4px; font-size: 10px; font-weight: 900; letter-spacing: .06em; }
.method-post { background: #17806b; }
.method-patch, .method-put { background: #946316; }
.method-delete { background: #a7473b; }
.path { overflow-wrap: anywhere; font: 12px ui-monospace, SFMono-Regular, Consolas, monospace; font-weight: 700; }
.operation-title { color: #526763; font-size: 12px; }
.operation-body { padding: 14px 16px 18px 104px; color: #405451; border-top: 1px solid #e5ecea; font-size: 12px; line-height: 1.6; }
.operation-body p { margin: 0 0 10px; }
.operation-body code { color: #174d67; }
.responses { display: flex; flex-wrap: wrap; gap: 7px; }
.response { padding: 3px 7px; background: #edf4f2; border-radius: 4px; font: 10px ui-monospace, SFMono-Regular, Consolas, monospace; }
.loading, .error, .empty { padding: 22px; background: #fff; border: 1px solid #d6e1df; border-radius: 8px; }
.error { color: #8b342b; border-color: #e1b7b0; }
[hidden] { display: none !important; }
@media (max-width: 720px) {
  .hero-inner, main { width: min(100% - 28px, 1120px); }
  .summary { align-items: stretch; flex-direction: column; }
  .search { width: 100%; }
  .stats { grid-template-columns: 1fr; }
  .operation summary { grid-template-columns: 68px minmax(0, 1fr); }
  .operation-title { grid-column: 1 / -1; }
  .operation-body { padding-left: 16px; }
}
"""

API_DOCS_JS = """const root = document.querySelector("#docs-root");
const stats = document.querySelector("#contract-stats");
const filter = document.querySelector("#operation-filter");

function element(name, className, text) {
  const node = document.createElement(name);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function operationCard(method, path, operation) {
  const details = element("details", "operation");
  details.dataset.search = `${method} ${path} ${operation.summary || ""} ${(operation.tags || []).join(" ")}`.toLowerCase();
  const summary = element("summary");
  summary.append(element("span", `method method-${method}`, method.toUpperCase()));
  summary.append(element("code", "path", path));
  summary.append(element("span", "operation-title", operation.summary || operation.operationId || "Operation"));
  details.append(summary);

  const body = element("div", "operation-body");
  if (operation.description) body.append(element("p", "", operation.description));
  const identifier = element("p");
  identifier.append("Operation ID: ", element("code", "", operation.operationId || "—"));
  body.append(identifier);
  const responses = element("div", "responses");
  Object.entries(operation.responses || {}).forEach(([status, response]) => {
    responses.append(element("span", "response", `${status} · ${response.description || "Response"}`));
  });
  body.append(responses);
  details.append(body);
  return details;
}

function render(contract) {
  const operations = [];
  Object.entries(contract.paths || {}).forEach(([path, methods]) => {
    Object.entries(methods).forEach(([method, operation]) => {
      if (["get", "post", "put", "patch", "delete"].includes(method)) {
        operations.push({ method, path, operation });
      }
    });
  });
  const groups = new Map();
  operations.forEach((entry) => {
    const tag = entry.operation.tags?.[0] || "other";
    if (!groups.has(tag)) groups.set(tag, []);
    groups.get(tag).push(entry);
  });

  stats.replaceChildren();
  [
    [operations.length, "operations"],
    [Object.keys(contract.components?.schemas || {}).length, "schemas"],
    [contract.info?.version || "—", "API version"],
  ].forEach(([value, label]) => {
    const card = element("div", "stat");
    card.append(element("strong", "", String(value)), element("span", "", label));
    stats.append(card);
  });

  root.replaceChildren();
  [...groups.entries()].sort(([left], [right]) => left.localeCompare(right)).forEach(([tag, entries]) => {
    const section = element("section", "tag-group");
    section.append(element("h3", "", tag.replaceAll("-", " ")));
    entries.sort((left, right) => left.path.localeCompare(right.path) || left.method.localeCompare(right.method));
    entries.forEach(({ method, path, operation }) => section.append(operationCard(method, path, operation)));
    root.append(section);
  });
  filter.disabled = false;
  filter.addEventListener("input", () => {
    const query = filter.value.trim().toLowerCase();
    let visible = 0;
    root.querySelectorAll(".operation").forEach((card) => {
      card.hidden = query !== "" && !card.dataset.search.includes(query);
      if (!card.hidden) visible += 1;
    });
    let empty = root.querySelector(".empty");
    if (visible === 0 && !empty) {
      empty = element("p", "empty", "No operations match this filter.");
      root.prepend(empty);
    } else if (visible > 0 && empty) {
      empty.remove();
    }
  });
}

fetch("/api/v1/openapi.json", { credentials: "same-origin" })
  .then((response) => {
    if (!response.ok) throw new Error(`OpenAPI request failed with HTTP ${response.status}`);
    return response.json();
  })
  .then(render)
  .catch((error) => {
    root.replaceChildren(element("p", "error", `The API contract could not be loaded: ${error.message}`));
  });
"""

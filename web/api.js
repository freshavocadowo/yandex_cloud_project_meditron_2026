// Клиент API: один интерфейс для двух режимов.
// server  — страница отдана FastAPI: запросы к /api/*.
// browser — статический хостинг (GitHub Pages): тот же Python-конвейер из app/ работает в браузере
//           через Pyodide, история — в localStorage. Документ никуда не отправляется.
const api = (() => {
  const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/";
  const STORE_KEY = "meditron.documents", STORE_LIMIT = 30;

  class ApiError extends Error {
    constructor(detail, status = 0) { super(detail); this.detail = detail; this.status = status; }
  }

  async function json(responsePromise) {
    const response = await responsePromise;
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new ApiError(body.detail || response.statusText, response.status);
    return body;
  }

  let modePromise = null, pythonPromise = null;

  function mode() {
    modePromise ??= fetch("api/schema").then(
      (r) => (r.ok && (r.headers.get("content-type") || "").includes("json") ? "server" : "browser"),
      () => "browser");
    return modePromise;
  }

  function python() {
    pythonPromise ??= (async () => {
      if (!window.loadPyodide) {
        await new Promise((resolve, reject) => {
          const script = document.createElement("script");
          script.src = PYODIDE + "pyodide.js";
          script.onload = resolve;
          script.onerror = reject;
          document.head.append(script);
        });
      }
      const py = await loadPyodide({ indexURL: PYODIDE });
      const [archive] = await Promise.all([
        fetch("py/app.zip").then((r) => { if (!r.ok) throw new Error("app.zip"); return r.arrayBuffer(); }),
        py.loadPackage("charset-normalizer"),
      ]);
      py.unpackArchive(archive, "zip");  // в рабочий каталог, он есть в sys.path
      return py.pyimport("app.browser");
    })().catch((e) => {
      pythonPromise = null;  // следующая попытка загрузит заново
      console.error(e);
      throw new ApiError("pyodide_unavailable");
    });
    return pythonPromise;
  }

  function stored() {
    try { return JSON.parse(localStorage.getItem(STORE_KEY)) || []; } catch { return []; }
  }

  function remember(doc) {
    try {
      const docs = [doc, ...stored().filter((d) => d.id !== doc.id)].slice(0, STORE_LIMIT);
      localStorage.setItem(STORE_KEY, JSON.stringify(docs));
    } catch { /* приватный режим или нет места: история просто не сохранится */ }
  }

  return {
    ApiError,
    mode,

    // начать загрузку Python заранее, пока пользователь читает страницу
    warmUp() { mode().then((m) => m === "browser" && python().catch(() => {})); },

    async schema() {
      if (await mode() === "server") return json(fetch("api/schema"));
      return JSON.parse((await python()).schema());
    },

    async extract(file) {
      if (await mode() === "server") {
        const body = new FormData();
        body.append("file", file, file.name);
        return json(fetch("api/extract", { method: "POST", body }));
      }
      const [module, data] = await Promise.all([python(), file.arrayBuffer()]);
      const doc = JSON.parse(module.extract(new Uint8Array(data), file.name));
      if (doc.detail) throw new ApiError(doc.detail, 400);
      remember(doc);
      return doc;
    },

    async result(id) {
      if (await mode() === "server") return json(fetch("api/results/" + encodeURIComponent(id)));
      const doc = stored().find((d) => d.id === id);
      if (!doc) throw new ApiError("not_found", 404);
      return doc;
    },

    async documents(limit = 20) {
      if (await mode() === "server") return json(fetch(`api/documents?limit=${limit}`));
      return stored().slice(0, limit).map(({ id, filename, pipeline_version, created_at }) =>
        ({ id, filename, status: "ok", pipeline_version, created_at }));
    },

    download(doc) {
      const blob = new Blob([JSON.stringify(doc.json, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${doc.doc_id || "epicrisis"}.json`;
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    },
  };
})();

// GLiNER deep scan — contextual PII (names, places, orgs) in the browser, the LIGHT way.
//
// GLiNER is an encoder NER (not a generative LLM): it returns real character spans it cannot
// hallucinate, runs on CPU/WASM (no WebGPU required), and the model is ~10x smaller than
// Gemma-4. That makes it the recommended default contextual tier — the one that can run almost
// anywhere. Powered by the `gliner` package (Knowledgator) over onnxruntime-web; the model and
// tokenizer download from the HF Hub on first use and the text never leaves the tab.

const GLINER_CDN = "https://esm.sh/gliner@0.0.19";
const TOKENIZER = "onnx-community/gliner_small-v2";
const MODEL_URL = "https://huggingface.co/onnx-community/gliner_small-v2/resolve/main/onnx/model.onnx";
const LABELS = ["person", "location", "organization"];
const MAP = { person: "PERSON", location: "LOCATION", organization: "ORG" };

// Self-contained fetch hook (independent of gemma.js's) so GLiNER downloads are abortable.
// Each module's hook only acts while ITS controller is active and chains through otherwise,
// so installing both is order-independent and safe.
let _orig = null;
let _active = null;
function installFetchHook() {
  if (_orig || typeof globalThis.fetch !== "function") return;
  _orig = globalThis.fetch.bind(globalThis);
  globalThis.fetch = (input, init = {}) => {
    if (!_active) return _orig(input, init);
    let signal = _active.signal;
    if (init.signal) {
      try { signal = AbortSignal.any([init.signal, _active.signal]); } catch { /* older browsers */ }
    }
    return _orig(input, { ...init, signal });
  };
}

export class GlinerScanner {
  constructor() {
    this.backend = "gliner";
    this.gliner = null;
    this.onStatus = () => {};
    this.onProgress = () => {};
    this._abort = null;
    this._cancelled = false;
    this._paused = false;
  }

  get ready() { return this.gliner !== null; }
  cancel() { this._cancelled = true; if (this._abort) this._abort.abort(); }
  pause() { this._paused = true; if (this._abort) this._abort.abort(); }

  async load() {
    this._cancelled = false;
    this._paused = false;
    installFetchHook();
    this.onStatus("loading GLiNER runtime…");
    const mod = await import(GLINER_CDN);
    const Gliner = mod.Gliner || (mod.default && (mod.default.Gliner || mod.default));

    const ctrl = new AbortController();
    this._abort = ctrl;
    _active = ctrl;
    const aborted = new Promise((_, reject) => {
      ctrl.signal.addEventListener(
        "abort",
        () => {
          const reason = this._cancelled ? "cancelled" : "paused";
          reject(Object.assign(new Error(reason), { aborted: true, reason }));
        },
        { once: true }
      );
    });

    try {
      this.onStatus("downloading GLiNER (small, CPU) — first run only, then cached…");
      const g = new Gliner({
        tokenizerPath: TOKENIZER,
        onnxSettings: {
          modelPath: MODEL_URL,
          executionProvider: "wasm", // CPU — works without a GPU
          multiThread: true,
          fetchBinary: true,
        },
        transformersSettings: { useBrowserCache: true },
        maxWidth: 12,
        modelType: "gliner",
      });
      const init = g.initialize();
      init.catch(() => {});
      await Promise.race([init, aborted]);
      this.gliner = g;
      this.onProgress(100);
      this.onStatus("GLiNER ready — running locally on CPU.");
      return this;
    } catch (e) {
      if (e && e.aborted) throw e;
      if (this._cancelled || this._paused) {
        const reason = this._cancelled ? "cancelled" : "paused";
        throw Object.assign(new Error(reason), { aborted: true, reason });
      }
      throw e;
    } finally {
      _active = null;
      this._abort = null;
    }
  }

  async findEntities(text) {
    if (!this.ready) throw new Error("model not loaded");
    const res = await this.gliner.inference({
      texts: [text],
      entities: LABELS,
      threshold: 0.4,
      flatNer: true,
    });
    const ents = Array.isArray(res) && Array.isArray(res[0]) ? res[0] : res || [];
    const spans = [];
    for (const e of ents) {
      const type = MAP[String(e.label || "").toLowerCase()];
      if (!type || typeof e.start !== "number" || typeof e.end !== "number") continue;
      spans.push({
        start: e.start,
        end: e.end,
        type,
        text: e.spanText != null ? e.spanText : text.slice(e.start, e.end),
        valid: null,
        score: typeof e.score === "number" ? e.score : 0.5,
      });
    }
    return spans;
  }
}

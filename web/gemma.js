// Optional Gemma "deep scan" — contextual PII (names, places, orgs) entirely in-browser.
//
// This is the layer where an open generative model earns its keep: there is no checksum
// for "is this a person's name". Gemma runs locally on WebGPU, so the text never leaves
// the tab. It is deliberately NOT in the recall-critical path — the deterministic engine
// (redactable.js) owns structured PII; Gemma only adds soft, contextual spans.
//
// Two backends, both fully local, imported dynamically so the page works offline with zero
// download until the user opts in:
//   • "transformers" — Transformers.js + WebGPU, auto-downloads an ONNX Gemma-4 from the HF
//     Hub by id (the approach used by huggingface.co/spaces/webml-community/Gemma-4-WebGPU).
//   • "mediapipe"    — MediaPipe LLM Inference, loads a local .task/.litertlm Gemma file.

const TRANSFORMERS_CDN = "https://cdn.jsdelivr.net/npm/@huggingface/transformers";
const MEDIAPIPE_CDN = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-genai";
const MEDIAPIPE_WASM = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-genai/wasm";

// The ONNX Gemma-4 used by the webml-community WebGPU space (instruction-tuned, ~2B).
export const DEFAULT_GEMMA4_MODEL = "onnx-community/gemma-4-E2B-it-ONNX";

const LABELS = { person: "PERSON", location: "LOCATION", organization: "ORG" };

// Persistent fetch hook so we can abort Transformers.js downloads. The library captures
// `fetch` at import time and may pass its own signal, so we install the hook ONCE, before
// importing, and merge our signal with theirs. `_activeAbort` is set only during a load.
let _origFetch = null;
let _activeAbort = null;
function installFetchHook() {
  if (_origFetch || typeof globalThis.fetch !== "function") return;
  _origFetch = globalThis.fetch.bind(globalThis);
  globalThis.fetch = (input, init = {}) => {
    if (!_activeAbort) return _origFetch(input, init);
    let signal = _activeAbort.signal;
    if (init.signal) {
      try { signal = AbortSignal.any([init.signal, _activeAbort.signal]); } catch { /* older browsers */ }
    }
    return _origFetch(input, { ...init, signal });
  };
}

export function webgpuAvailable() {
  return typeof navigator !== "undefined" && "gpu" in navigator;
}

// Probe an actual WebGPU adapter (presence of navigator.gpu != a usable adapter).
export async function webgpuAdapter() {
  if (!webgpuAvailable()) return null;
  try {
    return await navigator.gpu.requestAdapter();
  } catch {
    return null;
  }
}

export class GemmaScanner {
  constructor({ backend = "transformers", modelId = DEFAULT_GEMMA4_MODEL } = {}) {
    this.backend = backend;
    this.modelId = modelId;
    this.tokenizer = null;
    this.model = null; // transformers
    this.llm = null; // mediapipe
    this.onStatus = () => {}; // (message: string)
    this.onProgress = () => {}; // (percent: 0..100)
    this._abort = null;
    this._cancelled = false;
    this._paused = false;
  }

  get ready() {
    return this.model !== null || this.llm !== null;
  }

  // Stop an in-progress download. cancel() = abandon; pause() = stop, but whole files already
  // cached are kept, so a later load() resumes from the next file.
  cancel() { this._cancelled = true; if (this._abort) this._abort.abort(); }
  pause() { this._paused = true; if (this._abort) this._abort.abort(); }

  async load(source) {
    if (!webgpuAvailable()) {
      throw new Error("WebGPU unavailable — in-browser Gemma needs a WebGPU-capable browser.");
    }
    return this.backend === "mediapipe" ? this._loadMediapipe(source) : this._loadTransformers();
  }

  async _loadTransformers() {
    this._cancelled = false;
    this._paused = false;
    installFetchHook(); // must run before importing so Transformers.js captures the hooked fetch
    this.onStatus("loading Transformers.js runtime…");
    const { AutoTokenizer, AutoModelForCausalLM } = await import(TRANSFORMERS_CDN);

    // Route this load's downloads through our AbortController.
    const ctrl = new AbortController();
    this._abort = ctrl;
    _activeAbort = ctrl;

    const files = {};
    const progress = (p) => {
      if (p.status === "progress" && p.file && p.total) {
        files[p.file] = { loaded: p.loaded || 0, total: p.total };
        let loaded = 0, total = 0;
        for (const k in files) { loaded += files[k].loaded; total += files[k].total; }
        const pct = total ? Math.round((loaded / total) * 100) : 0;
        this.onProgress(pct);
        this.onStatus(
          `downloading… ${pct}%  (${(loaded / 1048576).toFixed(0)}/${(total / 1048576).toFixed(0)} MB)`
        );
      }
    };

    // Transformers.js may swallow an aborted fetch and never reject, so we race the load
    // against the abort signal — cancel/pause rejects load() promptly and the dangling
    // download (already network-aborted) is ignored.
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
    const race = (p) => {
      p.catch(() => {}); // swallow the dangling promise's later rejection
      return Promise.race([p, aborted]);
    };

    try {
      this.onStatus(`downloading ${this.modelId} (first run only; cached after)…`);
      this.tokenizer = await race(AutoTokenizer.from_pretrained(this.modelId, { progress_callback: progress }));
      this.model = await race(
        AutoModelForCausalLM.from_pretrained(this.modelId, { dtype: "q4", device: "webgpu", progress_callback: progress })
      );
      this.onProgress(100);
      this.onStatus("Gemma-4 ready — running on your GPU, fully local.");
      return this;
    } catch (e) {
      if (e && e.aborted) throw e;
      if (this._cancelled || this._paused || (e && e.name === "AbortError")) {
        const reason = this._cancelled ? "cancelled" : "paused";
        throw Object.assign(new Error(reason), { aborted: true, reason });
      }
      throw e;
    } finally {
      _activeAbort = null;
      this._abort = null;
    }
  }

  async _loadMediapipe(source) {
    this.onStatus("loading MediaPipe runtime…");
    const { FilesetResolver, LlmInference } = await import(MEDIAPIPE_CDN);
    const fileset = await FilesetResolver.forGenAiTasks(MEDIAPIPE_WASM);
    const baseOptions =
      typeof source === "string"
        ? { modelAssetPath: source }
        : { modelAssetBuffer: (await source.stream()).getReader() };
    this.onStatus("loading Gemma weights (first run can be slow)…");
    this.llm = await LlmInference.createFromOptions(fileset, {
      baseOptions, maxTokens: 1024, temperature: 0.0, topK: 1, randomSeed: 1,
    });
    this.onStatus("Gemma ready — running locally on your GPU.");
    return this;
  }

  async _generate(prompt) {
    if (this.backend === "transformers") {
      const messages = [{ role: "user", content: prompt }];
      const inputs = this.tokenizer.apply_chat_template(messages, {
        add_generation_prompt: true,
        return_dict: true,
      });
      const inLen = inputs.input_ids.dims.at(-1);
      const output = await this.model.generate({ ...inputs, max_new_tokens: 512, do_sample: false });
      // Decode only the newly generated tokens (drop the echoed prompt).
      try {
        return this.tokenizer.batch_decode(output.slice(null, [inLen, null]), {
          skip_special_tokens: true,
        })[0] || "";
      } catch {
        return this.tokenizer.batch_decode(output, { skip_special_tokens: true })[0] || "";
      }
    }
    // mediapipe: Gemma turn format, streamed
    const query = `<start_of_turn>user\n${prompt}<end_of_turn>\n<start_of_turn>model\n`;
    return new Promise((resolve, reject) => {
      let acc = "";
      try {
        this.llm.generateResponse(query, (partial, done) => {
          acc += partial;
          if (done) resolve(acc);
        });
      } catch (e) {
        reject(e);
      }
    });
  }

  async findEntities(text) {
    if (!this.ready) throw new Error("model not loaded");
    const prompt =
      "Extract every person name, physical location, and organization from the TEXT.\n" +
      'Respond ONLY with a JSON array of objects like {"text": "...", "label": "person|location|organization"}.\n' +
      "Use the exact substring as it appears. No commentary.\n\nTEXT:\n" +
      text;
    return spansFromModelJson(await this._generate(prompt), text);
  }
}

// Recover {text,label} objects from model output even when the surrounding JSON is
// malformed (small models routinely emit a stray brace, trailing comma, or code fence).
function extractObjects(raw) {
  const start = raw.indexOf("[");
  const end = raw.lastIndexOf("]");
  if (start !== -1 && end > start) {
    try {
      const parsed = JSON.parse(raw.slice(start, end + 1));
      if (Array.isArray(parsed)) return parsed;
    } catch {
      /* fall through to regex recovery */
    }
  }
  const objects = [];
  const textFirst = /\{\s*"text"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"label"\s*:\s*"([^"]*)"\s*\}/g;
  const labelFirst = /\{\s*"label"\s*:\s*"([^"]*)"\s*,\s*"text"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}/g;
  let m;
  while ((m = textFirst.exec(raw))) objects.push({ text: m[1], label: m[2] });
  while ((m = labelFirst.exec(raw))) objects.push({ text: m[2], label: m[1] });
  return objects;
}

// Parse the model's (possibly messy) output and turn each entity into a located span.
export function spansFromModelJson(raw, text) {
  const items = extractObjects(raw);
  if (!items.length) return [];
  const spans = [];
  const cursor = {};
  for (const item of Array.isArray(items) ? items : []) {
    const value = item && item.text;
    const type = item && LABELS[String(item.label || "").toLowerCase()];
    if (!value || !type) continue;
    const from = cursor[value] || 0;
    const idx = text.indexOf(value, from);
    if (idx === -1) continue; // model invented a span not in the text -> drop it
    cursor[value] = idx + value.length;
    spans.push({ start: idx, end: idx + value.length, type, text: value, valid: null, score: 0.75 });
  }
  return spans;
}

// ---- cached-model management (Transformers.js stores model files in the Cache Storage API) ----

export const MODEL_CACHE = "transformers-cache";

// Approximate bytes of cached model files (from content-length headers — no blob reads).
export async function cachedModelBytes() {
  if (typeof caches === "undefined") return 0;
  if (!(await caches.keys()).includes(MODEL_CACHE)) return 0;
  const cache = await caches.open(MODEL_CACHE);
  let bytes = 0;
  for (const req of await cache.keys()) {
    const resp = await cache.match(req);
    const len = resp && resp.headers.get("content-length");
    if (len) bytes += parseInt(len, 10);
  }
  return bytes;
}

// Delete cached model weights to reclaim disk. Returns the bytes freed.
export async function deleteCachedModels() {
  if (typeof caches === "undefined") return 0;
  const freed = await cachedModelBytes();
  for (const name of await caches.keys()) {
    if (/transformers|huggingface|onnx/i.test(name)) await caches.delete(name);
  }
  return freed;
}

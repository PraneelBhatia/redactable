# Form factors — roadmap

The same engine (`redactable.js`) can be delivered in several shapes. Status below.

## ✅ Web app (done)
`index.html` + `redactable.js` + `gemma.js` — the "scrub before you talk to an LLM" tool.
Deterministic core + optional local Gemma-4 (WebGPU). Verified end-to-end (see README).

## ✅ CLI (done — Python)
Already shipped at the repo root: `redactable redact` / `redactable eval`. For a *Node* CLI
that reuses this exact JS engine, wrap `scrub()`:
```js
// bin/redactable.mjs  (TODO)
import { scrub } from "../web/redactable.js";
process.stdin ... -> console.log(scrub(text).text)
```

## ◻ Chrome extension (scaffolded — see `extension/`)
A Manifest V3 popup that scrubs pasted text with the deterministic engine, offline.
**Next steps:**
- [ ] Content script that detects ChatGPT/Claude/Gemini input boxes and offers an inline
      "Scrub before sending" button (intercept the submit, scrub, confirm).
- [ ] Optional Gemma deep scan inside the extension (Offscreen Document + WebGPU; weights in
      `chrome.storage`/OPFS so they're downloaded once).
- [ ] Settings: which policy (mask vs numbered tokens), which entity types.
- [ ] Real icons (`icons/16,48,128.png`).

## ◻ Git pre-commit hook (scaffolded — see `../hooks/pre-commit-redact.sh`)
Block commits that contain unredacted PII (uses the Python CLI).
**Next steps:**
- [ ] Wire into `pre-commit` framework (`.pre-commit-hooks.yaml`).
- [ ] `--fix` mode that writes redacted copies / fails with a diff.

## ◻ Other surfaces (ideas)
- [ ] VS Code extension: "Redact selection".
- [ ] A clipboard daemon ("scrub on copy") — but be careful, that's invasive.
- [ ] A tiny serverless proxy that scrubs before forwarding to an LLM API (server-side variant).

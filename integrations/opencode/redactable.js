// Redactable plugin for opencode — transparent, reversible PII scrubbing on the model call.
//
//   outbound:  experimental.chat.messages.transform  -> real PII in messages headed to the
//              model is replaced with placeholders ([EMAIL_1], [PHONE_1], ...)
//   system:    experimental.chat.system.transform     -> the model is told to keep placeholders
//              verbatim, so the restore step lines up
//   inbound:   experimental.text.complete             -> real values are put back into the
//              assistant's reply, so YOU still see them but the provider never did
//
// The provider only ever sees placeholders; you see real values. Detection runs on
// redactable's deterministic engine (no model, no network) via redactable-helper.py.
//
// Install: copy this file AND redactable-helper.py into ~/.config/opencode/plugin/.
// Requires: pip install redactable
//   If redactable is in a venv, point the plugin at that interpreter:
//     export REDACTABLE_PYTHON=/path/to/.venv/bin/python
//   Optional: REDACTABLE_POLICY (default pii-structured), REDACTABLE_DEBUG=1 (log to /tmp).

import { spawnSync } from "node:child_process"
import { appendFileSync } from "node:fs"
import { fileURLToPath } from "node:url"

const PY = process.env.REDACTABLE_PYTHON || "python3"
const HELPER = fileURLToPath(new URL("./redactable-helper.py", import.meta.url))
const POLICY = process.env.REDACTABLE_POLICY || "pii-structured"

const DEBUG = process.env.REDACTABLE_DEBUG === "1"
const DEBUG_LOG = "/tmp/redactable-plugin.log"
function debug(obj) {
  if (!DEBUG) return
  try {
    appendFileSync(DEBUG_LOG, JSON.stringify(obj) + "\n")
  } catch {}
}

const META =
  "Some values in this conversation have been replaced with placeholders such as " +
  "[EMAIL_1], [PHONE_1], [US_SSN_1], [CREDIT_CARD_1]. Treat each placeholder as the real " +
  "value it stands for, and reproduce it VERBATIM where relevant — never invent, expand, " +
  "renumber, or alter a placeholder."

// cumulative token -> original, across the active session(s)
const keymap = {}

function scrub(texts) {
  try {
    const res = spawnSync(PY, [HELPER], {
      input: JSON.stringify({ texts, policy: POLICY }),
      encoding: "utf8",
      timeout: 15000,
      maxBuffer: 16 * 1024 * 1024,
    })
    if (res.status !== 0 || !res.stdout) return null
    const out = JSON.parse(res.stdout)
    if (out.error) {
      debug({ event: "helper-error", error: out.error })
      return null
    }
    return out
  } catch (e) {
    debug({ event: "spawn-error", error: String(e) })
    return null
  }
}

function restore(text) {
  if (typeof text !== "string" || !text) return text
  let out = text
  for (const [tok, orig] of Object.entries(keymap)) {
    if (out.includes(tok)) out = out.split(tok).join(orig)
  }
  return out
}

export const RedactablePlugin = async () => {
  return {
    // Outbound: scrub PII out of everything heading to the model.
    "experimental.chat.messages.transform": async (_input, output) => {
      const parts = []
      for (const m of output.messages || []) {
        for (const p of m.parts || []) {
          if (p && p.type === "text" && typeof p.text === "string" && p.text.trim()) parts.push(p)
        }
      }
      if (!parts.length) return
      const r = scrub(parts.map((p) => p.text))
      if (!r || !Array.isArray(r.texts)) return
      parts.forEach((p, i) => {
        if (typeof r.texts[i] === "string") p.text = r.texts[i]
      })
      Object.assign(keymap, r.keymap || {})
      debug({ event: "outbound-to-model", sent_texts: parts.map((p) => p.text), keymap: r.keymap })
    },

    // System: instruct the model to keep placeholders verbatim so restore aligns.
    "experimental.chat.system.transform": async (_input, output) => {
      if (Array.isArray(output.system)) output.system.push(META)
    },

    // Inbound: restore the real values into the assistant's reply for display.
    "experimental.text.complete": async (_input, output) => {
      if (output && typeof output.text === "string") output.text = restore(output.text)
    },
  }
}

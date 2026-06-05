# Redactable plugin for opencode

Transparent, reversible PII scrubbing inside [opencode](https://opencode.ai) — for when the
universal [scrub-proxy](../../docs/AGENT-SETUP.md) can't be used because opencode authenticates
with a subscription **OAuth** account (its model traffic doesn't pass through a base-URL proxy).

It does the same thing the proxy does, via opencode's plugin hooks:

- **outbound** (`experimental.chat.messages.transform`) — replaces real PII in messages headed
  to the model with placeholders (`[EMAIL_1]`, `[PHONE_1]`, …)
- **system** (`experimental.chat.system.transform`) — tells the model to keep placeholders verbatim
- **inbound** (`experimental.text.complete`) — restores the real values into the reply you read

The provider only ever sees placeholders; you see real values.

## Install

```bash
pip install redactable                       # detection engine
mkdir -p ~/.config/opencode/plugin
cp redactable.js redactable-helper.py ~/.config/opencode/plugin/
```

If `redactable` is installed in a virtualenv (not the default `python3`), point the plugin at it:

```bash
export REDACTABLE_PYTHON=/path/to/.venv/bin/python
```

Then just launch `opencode`. Confirm it loaded with `opencode mcp list` (plugins load alongside),
or run with `REDACTABLE_DEBUG=1 opencode …` and watch `/tmp/redactable-plugin.log`.

## Options (env vars)

| Var | Default | Purpose |
|---|---|---|
| `REDACTABLE_PYTHON` | `python3` | Interpreter that has `redactable` installed |
| `REDACTABLE_POLICY` | `pii-structured` | Policy pack deciding which PII types to scrub |
| `REDACTABLE_DEBUG` | unset | `1` → log what's sent to the model to `/tmp/redactable-plugin.log` |

## Verify

```bash
rm -f /tmp/redactable-plugin.log
REDACTABLE_DEBUG=1 opencode run "My SSN is 123-45-6789, email me@x.com. Say OK."
python3 -m json.tool /tmp/redactable-plugin.log   # sent_texts should show [US_SSN_1], [EMAIL_1]
```

## Limits

- Detection is the deterministic engine by default (structured PII). Names/free-text need a
  contextual policy via `REDACTABLE_POLICY`.
- The keymap is one cumulative map — ideal for a single active session.
- Uses opencode's `experimental.*` hooks; if a future opencode renames them, update the hook keys.

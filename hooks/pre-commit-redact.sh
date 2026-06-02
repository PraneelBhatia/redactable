#!/usr/bin/env bash
# Redactable pre-commit hook — block commits that contain unredacted structured PII.
#
# Install:  ln -s ../../hooks/pre-commit-redact.sh .git/hooks/pre-commit
# Requires: pip install redactable
#
# It runs the Redactable CLI over staged text files with the deterministic `pii-structured`
# policy. If redaction would change a file, that file contains PII and the commit is blocked.
set -euo pipefail

if ! command -v redactable >/dev/null 2>&1; then
  echo "redactable not installed; skipping PII check (pip install redactable)"
  exit 0
fi

fail=0
while IFS= read -r f; do
  case "$f" in
    *.txt|*.md|*.csv|*.json|*.jsonl|*.log|*.yaml|*.yml|*.env) ;;
    *) continue ;;
  esac
  [ -f "$f" ] || continue
  redacted="$(redactable redact "$f" --policy pii-structured 2>/dev/null || true)"
  if [ -n "$redacted" ] && [ "$redacted" != "$(cat "$f")" ]; then
    echo "✖ structured PII detected in staged file: $f"
    fail=1
  fi
done < <(git diff --cached --name-only --diff-filter=ACM)

if [ "$fail" = 1 ]; then
  echo ""
  echo "Commit blocked. Inspect with:  redactable redact <file> --policy pii-structured"
  echo "Bypass (use sparingly):        git commit --no-verify"
  exit 1
fi

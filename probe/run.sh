#!/usr/bin/env bash
# run.sh <candidate_identity> [api_alias] — one probe run for one candidate.
#
# Drives the candidate over the locked slice through the real write_enrichment into a
# throwaway probe_<label> schema, scores, drops the schema. Conda env (miniforge3), never
# venv (build-step 0). DB creds come from the environment as the scoped `probe` role —
# NEVER a prod-write credential.
#
#   candidate_identity : reporting name + label, e.g. qwen2.5-72b
#   api_alias          : LiteLLM alias to call (default big-thinker — the swappable lane)
set -euo pipefail

IDENTITY="${1:?usage: run.sh <candidate_identity> [api_alias]}"
API_ALIAS="${2:-big-thinker}"
LABEL="${IDENTITY//[^a-zA-Z0-9_]/_}"; LABEL="${LABEL,,}"   # sanitize -> probe_<label> safe

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

# conda env (miniforge3), never venv/pyenv/virtualenv (hard project standard)
# shellcheck disable=SC1091
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate context-reliquary

export PROBE_CANDIDATE_MODEL="$API_ALIAS"

# Thinking-off for the Qwen3 family (handoff §2): they burn the whole budget inside <think>
# on a trivial input and return empty otherwise. Verified mechanism: per-request
# chat_template_kwargs.enable_thinking=false. gemma keeps thinking ON (budget is enough);
# llama models are non-thinking. So we compare extraction, not deliberation length.
case "$IDENTITY" in
  qwen3.5*|qwen3-14b*|qwen3-omni*)
    export PROBE_CANDIDATE_EXTRA_BODY='{"chat_template_kwargs": {"enable_thinking": false}}'
    echo "[run.sh] thinking-OFF for $IDENTITY" ;;
  *)
    unset PROBE_CANDIDATE_EXTRA_BODY 2>/dev/null || true ;;
esac

echo "[run.sh] candidate=$IDENTITY api_alias=$API_ALIAS label=$LABEL"
python -m reliquary_enrichment.probe.cli "$IDENTITY" "$LABEL" \
  --api-model "$API_ALIAS" \
  --slice probe/slice/chunk_ids.txt \
  --out "probe/results/$LABEL"

# refresh the aggregate table
python -m reliquary_enrichment.probe.report probe/results probe/RESULTS.md
echo "[run.sh] done -> probe/results/$LABEL/ , probe/RESULTS.md"

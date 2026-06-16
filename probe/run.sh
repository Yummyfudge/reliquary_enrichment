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
echo "[run.sh] candidate=$IDENTITY api_alias=$API_ALIAS label=$LABEL"
python -m reliquary_enrichment.probe.cli "$IDENTITY" "$LABEL" \
  --api-model "$API_ALIAS" \
  --slice probe/slice/chunk_ids.txt \
  --out "probe/results/$LABEL"

# refresh the aggregate table
python -m reliquary_enrichment.probe.report probe/results probe/RESULTS.md
echo "[run.sh] done -> probe/results/$LABEL/ , probe/RESULTS.md"

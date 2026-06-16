#!/usr/bin/env bash
# probe_loop.sh — audition candidates on the extraction job; ALWAYS restore the default.
#
# Mirrors ~/model_sandbox/audition_loop.sh: for each candidate PROFILE, swap the `big-thinker`
# lane on the swap host, wait for /health, run the probe, score; on ANY failure skip that
# candidate; on exit ALWAYS restore qwen2.5-72b via a trap.
#
# Split deploy (Decision P2): this runs on mcp-hub; the LANE SWAP is done over SSH on llm-lxc
# (192.168.1.120). Needs the ssh key mcp-hub->llm-lxc (Joe cuts it per the key standard) and
# the scoped `probe` DB role creds in the environment (RELIQUARY_ENRICHMENT_PG*).
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SWAP_HOST="${PROBE_SWAP_HOST:-llm-lxc}"
LANE="${PROBE_LANE:-big-thinker}"
API_ALIAS="${PROBE_API_ALIAS:-big-thinker}"
DEFAULT_PROFILE="${PROBE_DEFAULT_PROFILE:-qwen2.5-72b}"
HEALTH_TIMEOUT="${PROBE_HEALTH_TIMEOUT:-600}"   # seconds to wait for a model to load
# candidates from argv, else the default pair (the two clean writers from the audition)
if [ "$#" -gt 0 ]; then CANDIDATES=("$@"); else CANDIDATES=(qwen2.5-72b qwen3-14b); fi

swap_lane() {  # $1 = PROFILE to load on the lane
  local profile="$1"
  echo "[loop] swapping $LANE -> PROFILE=$profile on $SWAP_HOST"
  # lane.env is owner-writable but its DIRECTORY is root-owned, so `sed -i` (which needs a
  # temp file in the dir) and `lane swap` (also seds) fail. Rewrite the file content in place
  # instead — truncate+write the existing inode, no dir temp — then cycle the lane.
  ssh "$SWAP_HOST" "
    f=/home/joe/lanes/lanes/${LANE}/lane.env
    new=\$(sed 's/^PROFILE=.*/PROFILE=${profile}/' \"\$f\") && printf '%s\n' \"\$new\" > \"\$f\"
    /home/joe/lanes/bin/lane down ${LANE}; /home/joe/lanes/bin/lane up ${LANE}
  "
}

health_wait() {  # poll the lane's /health until ready or timeout
  local waited=0
  echo "[loop] waiting for $LANE /health (timeout ${HEALTH_TIMEOUT}s)"
  while [ "$waited" -lt "$HEALTH_TIMEOUT" ]; do
    if ssh "$SWAP_HOST" "curl -sf http://localhost:8000/health >/dev/null 2>&1"; then
      echo "[loop] $LANE healthy after ${waited}s"; return 0
    fi
    sleep 10; waited=$((waited + 10))
  done
  echo "[loop] TIMEOUT waiting for $LANE health"; return 1
}

restore_default() {
  echo "[loop] === restoring default PROFILE=$DEFAULT_PROFILE ==="
  swap_lane "$DEFAULT_PROFILE" && health_wait \
    && echo "[loop] default $DEFAULT_PROFILE restored and healthy" \
    || echo "[loop] WARNING: failed to restore/verify $DEFAULT_PROFILE — CHECK MANUALLY"
}
trap restore_default EXIT   # ALWAYS restore, even on error/Ctrl-C

lane_profile() {  # the profile the lane is ACTUALLY configured to serve
  ssh "$SWAP_HOST" "grep -h '^PROFILE=' /home/joe/lanes/lanes/${LANE}/lane.env | cut -d= -f2" \
    2>/dev/null | tr -d '[:space:]'
}

for cand in "${CANDIDATES[@]}"; do
  echo "[loop] ===== candidate: $cand ====="
  if ! swap_lane "$cand"; then echo "[loop] swap failed for $cand — skipping"; continue; fi
  # GUARD: the swap writes a root-owned lane.env; if it didn't take, the lane still serves the
  # previous model. NEVER run a candidate against the wrong model — verify, else skip loudly.
  actual="$(lane_profile)"
  if [ "$actual" != "$cand" ]; then
    echo "[loop] !! SWAP DID NOT TAKE: lane '$LANE' serves '$actual', not '$cand' — SKIPPING."
    echo "[loop]    (lane.env is root-owned; joe can't change PROFILE. Needs Joe: make"
    echo "[loop]     /home/joe/lanes/lanes/${LANE}/lane.env writable by joe, or pre-swap, or sudo.)"
    continue
  fi
  if ! health_wait;       then echo "[loop] $cand never became healthy — skipping"; continue; fi
  if ! "$REPO/probe/run.sh" "$cand" "$API_ALIAS"; then
    echo "[loop] run.sh failed for $cand — skipping"; continue
  fi
  echo "[loop] $cand scored OK"
done

echo "[loop] all candidates done; RESULTS.md updated. (trap restores $DEFAULT_PROFILE)"

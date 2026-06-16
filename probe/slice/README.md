# `probe/slice/` — the locked test slice

Every candidate runs the **identical** input: a frozen list of `claim_chunk_id`s
(`chunk_ids.txt`), so model differences are the only variable. The slice is the reversal's
**web** — the gold note + every chunk that mentions its actors / conditions / dates — so it is
**cross-linked by construction** (the fix for "random pages aren't connected").

## Files
- **`build_slice.sql`** — the read-only query that derives the slice (engineer-written).
- **`chunk_ids.txt`** — the **frozen fixture** (content-free; UUIDs only). The committed
  source of truth every run reads.

## Freezing it (Architect, Decision P3 — engineer never reads corpus content)
```bash
psql "host=192.168.1.53 dbname=context_reliquary user=probe sslmode=verify-full" \
  -X -A -t -f probe/slice/build_slice.sql -o /tmp/slice.txt
# sanity: target ~60-100 chunks; ensure the gold note 89503c71… is present
wc -l /tmp/slice.txt && grep -c 89503c71 /tmp/slice.txt
cp /tmp/slice.txt probe/slice/chunk_ids.txt && git add probe/slice/chunk_ids.txt
```
Tune `web_terms` in `build_slice.sql` (RN/claim numbers, more Feb-2025 dates) to hit the
~60-100 target. Once committed, **do not regenerate casually** — a frozen slice is what makes
runs comparable across models and across time.

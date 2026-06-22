from __future__ import annotations

"""Discriminative weight + theme-flag — THE CRQ-001 lever (brief §9). Deterministic, NO LLM.

After normalization, each canonical entity gets weight = | distinct chunks it appears in |
(record_store.chunks_by_entity) and is_theme = weight >= cutoff, persisted via set_entity_flags. This
is what the old keyword pass missed:
  * RARE (low weight)      -> a discriminator / locator / join-key (B. Smith, F06.4, a specific date).
    HIGH-RECALL, must-not-miss; full weight as a discriminator; eligible as a link join-key.
  * UBIQUITOUS (high weight) -> a THEME (Long COVID, the claimant, "the claim"). ONE node, flagged
    theme, KEPT NEVER DELETED, on the LINKING STOPLIST (excluded as a SOLE join-key), down-weighted as
    a discriminator.

The cutoff is a tunable knob — a FRACTION of the MAX grounded chunk-degree in THIS run (default 0.4),
NOT a fraction of total chunks. This matters: weight is the GROUNDED degree (chunks_by_entity over
judge-gated records), which is <= the text-occurrence degree, and the audition grounding rate was only
~34-54%. A fraction-of-TOTAL cutoff (e.g. 0.4*131=52) would, at those rates, drag every ubiquitous theme
BELOW it and mis-flag the themes as discriminators (the lever inverting the WRONG way). Anchoring to the
max grounded degree makes the cutoff scale with the actual grounded distribution, so the classification
is robust to the overall grounding rate (adversarially verified). It is CALIBRATED against the frozen
slice (test_discriminative): the known discriminators (B. Smith 2, gold date 3, F06.4 28) land BELOW the
cutoff and the known themes ("the claim" 76, claimant 82, Long COVID 90) land ABOVE — load-bearing: if
the cutoff ever mis-flagged B. Smith as a theme, the whole lever would invert.

TODO (first real grounded run / re-audition): re-validate the 0.4 fraction against ACTUAL grounded
degrees — the current calibration is on text-occurrence (the grounded-degree proxy).

No named buckets — type + weight let an agent group on demand at query time. Glass-box output carries
every entity's weight/is_theme + the theme stoplist the linker (§8) consumes.
"""

from reliquary_enrichment.multipass.pass_base import ChunkRef, Pass, PassContext, PassResult
from reliquary_enrichment.multipass.vocabulary import ENTITY_TYPES

DEFAULT_THEME_FRACTION: float = 0.4


def theme_cutoff(max_grounded_degree: int, theme_fraction: float = DEFAULT_THEME_FRACTION) -> int:
    """The grounded chunk-degree at/above which an entity is a theme — a FRACTION of the MAX grounded
    degree in the run (so it scales with the actual distribution, robust to the overall grounding rate).
    Floor of 2 so a single-chunk entity is never a theme."""
    return max(2, round(theme_fraction * max_grounded_degree))


class DiscriminativeWeightPass(Pass):
    name = "discriminative_weight"
    per_chunk = False

    def __init__(self, *, theme_fraction: float = DEFAULT_THEME_FRACTION) -> None:
        self.theme_fraction = theme_fraction

    def process_all(
        self, chunks: list[ChunkRef], prior: dict[str, PassResult], ctx: PassContext
    ) -> dict:
        entity_store = ctx.extras["entity_store"]
        record_store = ctx.extras["record_store"]

        # Weigh every entity FIRST, then set the cutoff relative to the MAX grounded degree in this run
        # (robust to the overall grounding rate — see the module docstring).
        weighed: list[tuple] = []
        for etype in sorted(ENTITY_TYPES):
            for entity in entity_store.entities_of_type(etype):
                weight = len(record_store.chunks_by_entity(entity.entity_id))
                weighed.append((entity, etype, weight))
        max_degree = max((w for _, _, w in weighed), default=0)
        cutoff = theme_cutoff(max_degree, self.theme_fraction)

        weights: dict[str, dict] = {}
        themes: list[str] = []
        for entity, etype, weight in weighed:
            is_theme = weight >= cutoff
            entity_store.set_entity_flags(entity.entity_id, weight=weight, is_theme=is_theme)
            weights[entity.entity_id] = {
                "type": etype, "canonical": entity.canonical,
                "weight": weight, "is_theme": is_theme,
            }
            if is_theme:
                themes.append(entity.canonical)

        return {
            "theme_cutoff": cutoff,
            "max_grounded_degree": max_degree,
            "total_chunks": len(chunks),
            "theme_fraction": self.theme_fraction,
            "weights": weights,
            "themes": sorted(themes),
            "stoplist": sorted(themes),   # excluded as SOLE link join-keys (§8); kept, never deleted
        }

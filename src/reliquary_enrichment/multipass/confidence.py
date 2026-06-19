from __future__ import annotations

"""Confidence-plateau — the Pass 3 retry bound (Joe's exact rule, 2026-06-17).

Each retry, read the model's self-reported confidence; **STOP when a retry fails to beat the
best-so-far confidence by ≥ epsilon.** Self-terminating: confidence∈[0,1], the running max only
climbs, each "continue" costs ≥ epsilon → at most ~1/epsilon retries can ever fire. The bound
EMERGES from epsilon — no magic count. "Beat best-so-far" (not "beat previous") survives
oscillation/saturation. The full trajectory is retained for ε-tuning (glass box).

This owns ONLY "keep trying?". Whether a record is right is the judge's call at persist; a low
plateau is not a loop failure — it means "more retries won't help." Never read a high plateau as
"correct": self-reported confidence is weak.
"""

from dataclasses import dataclass, field


@dataclass
class ConfidencePlateau:
    epsilon: float = 0.05
    best: float | None = None
    trajectory: list[float] = field(default_factory=list)

    def record(self, confidence: float) -> bool:
        """Record this attempt's confidence; return True if the loop has PLATEAUED (stop).

        The first attempt never plateaus (nothing to beat). A subsequent attempt that fails to
        beat best-so-far by ≥ epsilon is the plateau. Otherwise the running max advances.
        """
        conf = float(confidence)
        is_retry = len(self.trajectory) > 0
        self.trajectory.append(conf)
        if is_retry and self.best is not None and conf < self.best + self.epsilon:
            return True  # plateau — did not improve enough
        self.best = conf if self.best is None else max(self.best, conf)
        return False

    @property
    def best_confidence(self) -> float:
        return self.best if self.best is not None else 0.0

"""Test fakes — in-memory FragmentReader + scriptable GroundingJudge.

Why: the grounding-core (the heart) is unit-tested with NO network and NO DB. These
fakes let a test pin exactly which Fragment exists and exactly what verdict the judge
returns, so every branch of the invariant is exercised deterministically (Decision D2).
"""

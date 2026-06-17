from __future__ import annotations

"""Tests for the post-hang hardening: bounded HTTP (max_tokens + deadline), graceful
skip-and-log on timeout, and the runner progress heartbeat."""

import time

import pytest
import requests

import reliquary_enrichment.grounding.judge as judge_mod
import reliquary_enrichment.probe.extraction as ext_mod
from reliquary_enrichment.grounding.judge import LiteLLMGroundingJudge
from reliquary_enrichment.grounding.types import GroundingError, ReasonCode
from reliquary_enrichment.llm_http import LLMTimeout, post_json
from reliquary_enrichment.probe.extraction import CandidateExtractor
from reliquary_enrichment.probe.runner import ProbeRunner


# --- post_json hard deadline ---------------------------------------------------------
def test_post_json_raises_on_total_deadline(monkeypatch):
    def slow_post(*a, **k):
        time.sleep(2.0)
    monkeypatch.setattr(requests, "post", slow_post)
    with pytest.raises(LLMTimeout):
        post_json("http://x/y", {}, total_deadline=0.2)


def test_post_json_surfaces_request_errors(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("refused")
    monkeypatch.setattr(requests, "post", boom)
    with pytest.raises(requests.RequestException):
        post_json("http://x/y", {}, total_deadline=2.0)


# --- candidate sends max_tokens + bounded ---------------------------------------------
def test_candidate_payload_caps_max_tokens(monkeypatch):
    seen = {}
    def fake_post_json(url, payload, **kw):
        seen["payload"] = payload
        seen["kw"] = kw
        return {"choices": [{"message": {"content": "[]"}}]}
    monkeypatch.setattr(ext_mod, "post_json", fake_post_json)
    CandidateExtractor(model="m", max_tokens=1234, deadline_s=99).extract("some text")
    assert seen["payload"]["max_tokens"] == 1234
    assert seen["kw"]["total_deadline"] == 99


# --- judge sends max_tokens + fails CLOSED on timeout --------------------------------
def test_judge_payload_caps_max_tokens(monkeypatch):
    seen = {}
    def fake_post_json(url, payload, **kw):
        seen["payload"] = payload
        return {"choices": [{"message": {"content": '{"verdict":"grounded"}'}}]}
    monkeypatch.setattr(judge_mod, "post_json", fake_post_json)
    LiteLLMGroundingJudge(max_tokens=321).evaluate("sys", "usr")
    assert seen["payload"]["max_tokens"] == 321


def test_judge_timeout_fails_closed(monkeypatch):
    def timeout_post_json(url, payload, **kw):
        raise LLMTimeout("deadline")
    monkeypatch.setattr(judge_mod, "post_json", timeout_post_json)
    with pytest.raises(GroundingError) as e:
        LiteLLMGroundingJudge().evaluate("sys", "usr")
    assert e.value.reason_code is ReasonCode.JUDGE_UNAVAILABLE


# --- runner: progress heartbeat + extract failure is skipped, not fatal -------------
class _Read:
    def get_chunk(self, cid, *, workstream_id):
        return {"ok": True, "chunk_handle": "F1", "text": "t"}


class _Write:
    def write(self, payload, *, workstream_id):
        return {"ok": True, "record_id": "r"}


class _ExtractorBoom:
    def extract(self, text):
        raise LLMTimeout("wedged")


def test_runner_logs_and_skips_extract_timeout_then_finishes():
    lines = []
    r = ProbeRunner(extractor=_ExtractorBoom(), write_service=_Write(), read_service=_Read(),
                    label="t", candidate_model="m", schema="probe_t",
                    clock=lambda: 0.0, progress=lines.append)
    log = r.run(["aaaaaaaa-0000-0000-0000-000000000000"])
    assert log.extract_errors == 1 and log.records_written == 0   # skipped, run completed
    assert any("EXTRACT FAIL" in ln for ln in lines)
    assert any(ln.startswith("START") for ln in lines) and any(ln.startswith("DONE") for ln in lines)


# --- §2 candidate extra_body (thinking-off) + §3 status heartbeat ---------------------
class _ExtractorOK:
    last_completion_tokens = 120
    def extract(self, text):
        from reliquary_enrichment.probe.extraction import ExtractionProposal
        return [ExtractionProposal(quote="t", record_type="r")]


def test_candidate_extra_body_and_token_capture(monkeypatch):
    seen = {}
    def fake_post_json(url, payload, **kw):
        seen["payload"] = payload
        return {"choices": [{"message": {"content": "[]"}}], "usage": {"completion_tokens": 42}}
    monkeypatch.setattr(ext_mod, "post_json", fake_post_json)
    ex = CandidateExtractor(model="m", extra_body={"chat_template_kwargs": {"enable_thinking": False}})
    ex.extract("some text")
    assert seen["payload"]["chat_template_kwargs"] == {"enable_thinking": False}  # thinking-off merged
    assert seen["payload"]["max_tokens"] >= 1536                                  # handoff §2 floor
    assert ex.last_completion_tokens == 42                                        # for tok/s


def test_runner_emits_15min_status_heartbeat(monkeypatch):
    import reliquary_enrichment.probe.runner as rmod
    monkeypatch.setattr(rmod, "STATUS_INTERVAL_S", 0.0)   # emit a STATUS after each chunk
    t = [0.0]
    def clk():
        t[0] += 1.0
        return t[0]
    lines = []
    r = ProbeRunner(extractor=_ExtractorOK(), write_service=_Write(), read_service=_Read(),
                    label="t", candidate_model="m", schema="probe_t",
                    clock=clk, progress=lines.append)
    r.run(["aaaaaaaa-0000-0000-0000-000000000000", "bbbbbbbb-0000-0000-0000-000000000000"])
    hb = [l for l in lines if l.startswith("[HB")]
    assert hb, "expected an [HB ...] heartbeat line"
    assert "tok/s" in hb[0] and "accept" in hb[0] and "chunks" in hb[0] and "%" in hb[0]

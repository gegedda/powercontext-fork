from __future__ import annotations

from wengu.tracing import Tracer


def test_payload_cannot_override_event_kind() -> None:
    tracer = Tracer()
    tracer.record("powercontext.create_artifact", {"kind": "wengu-topic", "seq": 999, "ts": "stale"})
    event = tracer.recent(1)[0]
    assert event["kind"] == "powercontext.create_artifact"
    assert event["seq"] == 1
    assert tracer.counters()["powercontext.create_artifact"] == 1

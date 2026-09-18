from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_command_center_renders_backend_next_actions_without_lifecycle_inference():
    source = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    start = source.index("  renderScenicNext:function(snapshot){")
    end = source.index("  bindScenicGuidance:function(){", start)
    function_source = source[start:end]

    assert "snapshot.next_actions" in function_source
    assert "snapshot.advice" in function_source
    assert "incident.lifecycle===" not in function_source
    assert "DECIDE_ADVICE" in source
    assert 'data-advice-form="IGNORE"' in source
    assert "data-reason-code required" in source
    assert "PROCEED_WITHOUT_WAITING" in source


def test_command_center_and_field_client_handle_advice_sse_events():
    command_center = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    shared_client = (ROOT / "static" / "shared" / "client.js").read_text(encoding="utf-8")
    field_client = (ROOT / "static" / "assistant" / "app.js").read_text(encoding="utf-8")

    for event_name in ("ADVICE_PENDING", "ADVICE_READY", "ADVICE_FAILED"):
        assert event_name in command_center
        assert event_name in field_client
    assert "onAdvice" in shared_client
    assert "onAdvice" in field_client


def test_field_client_renders_backend_guidance_read_only():
    source = (ROOT / "static" / "assistant" / "app.js").read_text(encoding="utf-8")

    assert "state.scenic.next_actions" in source
    assert "state.scenic.advice" in source
    assert "scenic-readonly-advice" in source
    assert "DECIDE_ADVICE" not in source

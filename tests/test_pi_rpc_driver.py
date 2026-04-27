"""Unit tests for the pure helpers in pi_rpc_driver.

We don't try to test the main RPC loop (that would need a fake `pi`
subprocess) — just the pure event-digest + string-trim helpers.
"""

from pi_rpc_driver import digest_event, truncate


# -----------------------------------------------------------------------------
# truncate
# -----------------------------------------------------------------------------
class TestTruncate:
    def test_short_passes_through(self):
        assert truncate("hello") == "hello"

    def test_collapses_whitespace(self):
        assert truncate("a   b\n\tc") == "a b c"

    def test_truncates_at_limit(self):
        result = truncate("a" * 300, n=10)
        assert len(result) == 10
        assert result.endswith("…")

    def test_handles_none(self):
        assert truncate(None) == ""

    def test_handles_empty(self):
        assert truncate("") == ""


# -----------------------------------------------------------------------------
# digest_event
# -----------------------------------------------------------------------------
class TestDigestResponse:
    def test_get_state_response_skipped(self):
        # get_state polls happen every 30s — too noisy to surface live
        ev = {"type": "response", "command": "get_state", "success": True}
        assert digest_event(ev) is None

    def test_prompt_accepted(self):
        ev = {"type": "response", "command": "prompt", "success": True, "id": "kickoff"}
        out = digest_event(ev)
        assert out is not None
        assert "✓" in out
        assert "prompt" in out
        assert "kickoff" in out

    def test_prompt_rejected(self):
        ev = {"type": "response", "command": "prompt", "success": False, "id": "kickoff"}
        out = digest_event(ev)
        assert out is not None
        assert "✗" in out


class TestDigestMessageUpdate:
    def test_unknown_event_skipped(self):
        ev = {"type": "ping"}
        assert digest_event(ev) is None

    def test_thinking_end_skipped(self):
        # Thinking is verbose internal monologue — surface results, not steps
        ev = {
            "type": "message_update",
            "assistantMessageEvent": {"type": "thinking_end", "content": "long internal trace"},
        }
        assert digest_event(ev) is None

    def test_text_end_with_content(self):
        ev = {
            "type": "message_update",
            "assistantMessageEvent": {
                "type": "text_end",
                "content": "I'll list the repo first.",
            },
        }
        out = digest_event(ev)
        assert out is not None
        assert "💬" in out
        assert "I'll list the repo first." in out

    def test_text_end_falls_back_to_partial(self):
        # Older event shape stores text in partial.content
        ev = {
            "type": "message_update",
            "assistantMessageEvent": {
                "type": "text_end",
                "partial": {"content": [{"type": "text", "text": "from partial"}]},
            },
        }
        out = digest_event(ev)
        assert out is not None
        assert "from partial" in out

    def test_text_end_empty_skipped(self):
        ev = {
            "type": "message_update",
            "assistantMessageEvent": {"type": "text_end", "content": ""},
        }
        assert digest_event(ev) is None

    def test_toolcall_end_with_string_arg(self):
        ev = {
            "type": "message_update",
            "assistantMessageEvent": {
                "type": "toolcall_end",
                "toolCall": {"name": "bash", "arguments": {"command": "ls -la"}},
            },
        }
        out = digest_event(ev)
        assert out is not None
        assert "→ bash" in out
        assert "ls -la" in out

    def test_toolcall_end_with_numeric_arg(self):
        ev = {
            "type": "message_update",
            "assistantMessageEvent": {
                "type": "toolcall_end",
                "toolCall": {"name": "log_experiment", "arguments": {"metric": 13}},
            },
        }
        out = digest_event(ev)
        assert out is not None
        assert "log_experiment" in out
        assert "metric=13" in out

    def test_toolcall_end_no_args(self):
        ev = {
            "type": "message_update",
            "assistantMessageEvent": {
                "type": "toolcall_end",
                "toolCall": {"name": "abort", "arguments": {}},
            },
        }
        out = digest_event(ev)
        assert out is not None
        assert "→ abort()" in out

    def test_toolresult_surfaced(self):
        ev = {
            "type": "message_update",
            "assistantMessageEvent": {
                "type": "toolresult",
                "result": "METRIC todo_count=7",
            },
        }
        out = digest_event(ev)
        assert out is not None
        assert "←" in out
        assert "todo_count" in out

    def test_long_text_truncated(self):
        ev = {
            "type": "message_update",
            "assistantMessageEvent": {
                "type": "text_end",
                "content": "x" * 1000,
            },
        }
        out = digest_event(ev)
        assert out is not None
        # truncate default is 200 chars; one-liner shouldn't be far above that
        assert len(out) < 250
        assert out.endswith("…")

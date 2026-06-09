from __future__ import annotations

from claudecmd.claude_command import (
    ClaudeOptions,
    OUTPUT_STREAM_JSON,
    build_command,
)


def test_builds_basic_json_command():
    cmd = build_command("say hello", ClaudeOptions(), claude_bin="claude")
    assert cmd == ["claude", "-p", "say hello", "--output-format", "json"]


def test_prompt_is_a_single_argv_element():
    # No shell interpolation: a dangerous prompt is one opaque argument.
    nasty = "hi; rm -rf / $(whoami)"
    cmd = build_command(nasty, ClaudeOptions(), claude_bin="claude")
    assert cmd[2] == nasty


def test_passes_through_model():
    cmd = build_command("p", ClaudeOptions(model="opus"), claude_bin="claude")
    assert "--model" in cmd and cmd[cmd.index("--model") + 1] == "opus"


def test_passes_through_max_turns():
    cmd = build_command("p", ClaudeOptions(max_turns=3), claude_bin="claude")
    assert "--max-turns" in cmd and cmd[cmd.index("--max-turns") + 1] == "3"


def test_passes_through_max_budget_usd():
    cmd = build_command("p", ClaudeOptions(max_budget_usd=0.5), claude_bin="claude")
    assert cmd[cmd.index("--max-budget-usd") + 1] == "0.5"


def test_max_budget_whole_number_has_no_trailing_zero():
    cmd = build_command("p", ClaudeOptions(max_budget_usd=2.0), claude_bin="claude")
    assert cmd[cmd.index("--max-budget-usd") + 1] == "2"


def test_allowed_tools_normalized_to_camelcase_flag():
    cmd = build_command(
        "p", ClaudeOptions(allowed_tools="Bash(git:*),Read"), claude_bin="claude"
    )
    assert "--allowedTools" in cmd
    assert cmd[cmd.index("--allowedTools") + 1] == "Bash(git:*),Read"
    assert "--allowed-tools" not in cmd


def test_disallowed_tools_normalized():
    cmd = build_command("p", ClaudeOptions(disallowed_tools="Write"), claude_bin="claude")
    assert cmd[cmd.index("--disallowedTools") + 1] == "Write"


def test_system_prompt_and_append():
    cmd = build_command(
        "p",
        ClaudeOptions(system_prompt="be terse", append_system_prompt="and kind"),
        claude_bin="claude",
    )
    assert cmd[cmd.index("--system-prompt") + 1] == "be terse"
    assert cmd[cmd.index("--append-system-prompt") + 1] == "and kind"


def test_permission_mode_and_no_persistence():
    cmd = build_command(
        "p",
        ClaudeOptions(permission_mode="plan", no_session_persistence=True),
        claude_bin="claude",
    )
    assert cmd[cmd.index("--permission-mode") + 1] == "plan"
    assert "--no-session-persistence" in cmd


def test_resume_session_id():
    cmd = build_command(
        "p", ClaudeOptions(resume_session_id="abc-123"), claude_bin="claude"
    )
    assert cmd[cmd.index("--resume") + 1] == "abc-123"


def test_stream_json_adds_verbose():
    cmd = build_command(
        "p", ClaudeOptions(), output_format=OUTPUT_STREAM_JSON, claude_bin="claude"
    )
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in cmd


def test_default_bin_from_env(monkeypatch):
    monkeypatch.setenv("CLAUDECMD_CLAUDE_BIN", "/opt/fake/claude")
    cmd = build_command("p", ClaudeOptions())
    assert cmd[0] == "/opt/fake/claude"

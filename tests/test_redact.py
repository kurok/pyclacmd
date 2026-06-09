from __future__ import annotations

from claudecmd.redact import REDACTED, redact, redact_argv


def test_redacts_anthropic_key():
    out = redact("key is sk-ant-abcdef0123456789XYZ here")
    assert "sk-ant-" not in out
    assert REDACTED in out


def test_redacts_openai_style_key():
    out = redact("token sk-abcdefghijklmnop0123456789")
    assert REDACTED in out
    assert "sk-abcdef" not in out


def test_redacts_github_token():
    out = redact("ghp_0123456789abcdefABCDEF0123456789abcd")
    assert REDACTED in out
    assert "ghp_" not in out


def test_redacts_authorization_header():
    out = redact("Authorization: Bearer supersecrettokenvalue")
    assert "supersecrettokenvalue" not in out
    assert REDACTED in out
    assert "Authorization:" in out


def test_redacts_env_style_secret():
    out = redact("API_KEY=topsecretvalue123")
    assert "topsecretvalue123" not in out
    assert out.startswith("API_KEY=")
    assert REDACTED in out


def test_redacts_password_assignment():
    out = redact("password: hunter2hunter2")
    assert "hunter2hunter2" not in out
    assert REDACTED in out


def test_leaves_ordinary_text_alone():
    text = "please review the diff in src/main.py and summarize"
    assert redact(text) == text


def test_redact_argv():
    argv = ["claude", "-p", "use API_KEY=secretvalue123 now"]
    out = redact_argv(argv)
    assert out[0] == "claude"
    assert "secretvalue123" not in out[2]

"""claudecmd — a programmatic, scriptable wrapper around the Claude Code CLI.

This package exposes a small CLI (``claudecmd``) that calls the local
``claude`` binary in print/headless mode and returns a stable output
contract (plain text, JSON envelope, raw passthrough, or streamed text).

It is intentionally a thin, well-behaved automation facade — not a
replacement for interactive Claude Code usage.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]

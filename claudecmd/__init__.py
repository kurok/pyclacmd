"""claudecmd — a programmatic, scriptable driver for Claude Code's interactive session.

This package exposes a small CLI (``claudecmd``) that drives the local
``claude`` binary's *interactive* session under a pseudo-terminal and returns
the parsed assistant reply (optionally as a JSON envelope). Driving the
interactive session keeps automated calls on the interactive (subscription)
path rather than separately-priced ``-p``/headless usage.

It is intentionally a thin, well-behaved automation facade.
"""

__version__ = "0.2.2"

__all__ = ["__version__"]

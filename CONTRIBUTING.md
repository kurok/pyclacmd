# Contributing

Thanks for your interest in improving **claudecmd**! Bug reports, ideas, and
pull requests are all welcome.

## Reporting issues

Open an issue at https://github.com/kurok/pyclacmd/issues with:

- your OS, Python version, and `claude --version`,
- the exact `claudecmd` command you ran (redact any secrets),
- what you expected vs. what happened (a `--debug --raw` dump is gold — it
  shows the rendered TUI screen the extractor saw).

Because `claudecmd` scrapes a human-facing TUI, extraction is tuned to Claude
Code's current rendering. If a new Claude Code version changes the interface,
a `--debug --raw` capture is the fastest way to get it fixed.

## Development setup

```bash
git clone https://github.com/kurok/pyclacmd
cd pyclacmd
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

The test suite mocks `pexpect`/`pyte` and the `claude` binary, so **it never
requires a real Claude login** and runs fully offline. Please add tests for any
behavior change. CI runs `pytest` on Python 3.12 / Ubuntu; the package supports
Python 3.8+.

## Pull requests

- Keep changes focused; one logical change per PR.
- Match the surrounding style; keep the CLI's output contract stable.
- Sign off your commits (`git commit -s`) to certify the
  [Developer Certificate of Origin](https://developercertificate.org/).

## License

By contributing you agree that your contributions are licensed under the
project's [MIT License](LICENSE).

# Contributing

Thanks for taking a look. This project is deliberately small; the smallest change
that solves the problem wins.

## Setup

```bash
python -m pip install -e ".[dev]"
```

## Before opening a pull request

```bash
ruff check .
ruff format .
pytest
```

All three must pass. CI runs the same commands on Python 3.11, 3.12 and 3.13.

## Guidelines

- Standard library only. A new runtime dependency needs a strong reason.
- Tests must not touch the network. The HTTP layer is injected through
  `frugalroute._open`, so monkeypatch it as the existing tests do.
- Never log or read a key from anywhere except the environment variable named by
  `api_key_env`.
- Keep the fallback contract intact: the chain moves toward stronger tiers only,
  and only `HTTP 401` stops it.
- Add a `CHANGELOG.md` entry under `[Unreleased]` for user-visible changes.

# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-10-23

### Added

- `timeout` config key (seconds, default 60) applied to every request.
- `--version` flag.
- CI workflow: ruff lint/format and pytest on Python 3.11, 3.12 and 3.13.
- Type hints on the public functions; `ruff` and `pytest` configuration in `pyproject.toml`.

### Changed

- Fallback now halts only on `HTTP 401`. `400`, `403`, `404`, `408`, `429` and
  `5xx` fall forward to the next model.
- Pricing `input`/`output` must be numbers; a string price is rejected at load time.
- `stats` skips malformed log rows (non-object, null, wrongly typed) and reports
  how many it skipped instead of crashing.

### Fixed

- A paid response is no longer discarded when its price cannot be computed; the
  call is returned and logged with `cost_usd: 0`.
- A halted `HTTP 401` attempt is logged with `halted: true`.
- README documents the fallback rule and the log record fields.

## [0.1.0] - 2026-10-23

### Added

- Rule-based prompt classifier (length, code blocks, difficulty keywords) with
  `--tier` override.
- OpenAI-compatible adapter driven by `base_url`, with the key read from the
  environment variable named in `api_key_env`.
- Forward-only fallback across ordered tiers and models.
- JSONL call log and `stats` command with total and per-model spend.
- `ask` command, example TOML config, README, MIT license and a pytest suite
  with a mocked HTTP layer.

[Unreleased]: https://github.com/Flexy01/frugalroute/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Flexy01/frugalroute/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Flexy01/frugalroute/releases/tag/v0.1.0

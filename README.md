# frugalroute

[![CI](https://github.com/Flexy01/frugalroute/actions/workflows/ci.yml/badge.svg)](https://github.com/Flexy01/frugalroute/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)

Route each prompt to the cheapest model that can handle it, fall back to stronger
models only, and log the cost of every call.

No SDK, no runtime dependencies — one file, the standard library, and any
OpenAI-compatible endpoint.

## How it works

1. **Classify** the prompt with cheap rules: length, fenced code blocks and
   difficulty keywords. A short question starts at the cheapest tier; a long
   request that says "refactor" and contains code starts higher.
2. **Call** the first model of that tier over `POST {base_url}/chat/completions`.
3. **Fall forward** if it fails: the next model in the chain, then the next tier.
   The chain only ever moves toward stronger models.
4. **Log** the attempt — model, tier, tokens, cost — as one JSON line.

```
prompt ──▶ classify ──▶ tier cheap ──▶ model A ──ok──▶ answer
                            │
                            └─fail──▶ model B ──▶ model C ──▶ next tier …
```

`HTTP 401` is the one fatal error: an invalid key fails identically for every
model, so the chain stops there. Every other failure — connection errors,
timeouts, 400, 403, 404, 408, 429, 5xx — falls forward.

## Install

Python 3.11+ (uses `tomllib`).

```bash
git clone https://github.com/Flexy01/frugalroute.git
cd frugalroute
python -m pip install -e .
```

That provides the `frugalroute` command. You can also run `python frugalroute.py ...`
without installing anything.

## Configure

Copy `config.example.toml` to `frugalroute.toml` and edit it. The key is read from
the environment variable named by `api_key_env`; it is never written to disk and
never appears in the log.

```toml
base_url = "https://api.openai.com/v1"   # any OpenAI-compatible endpoint
api_key_env = "OPENAI_API_KEY"           # name of the env var holding the key
log_path = "~/.frugalroute/calls.jsonl"  # one JSON object per attempt
timeout = 60                             # seconds, optional

[[tiers]]                 # ordered cheapest -> strongest
name = "cheap"
models = ["gpt-4o-mini", "gpt-4.1-mini"]

[[tiers]]
name = "standard"
models = ["gpt-4o", "gpt-4.1"]

[[tiers]]
name = "strong"
models = ["o3"]

[pricing."gpt-4o-mini"]   # USD per 1M tokens
input = 0.15
output = 0.60
```

Rules the config is validated against at load time:

- `base_url`, `api_key_env` and a non-empty `tiers` array are required.
- Every tier needs `name` and `models`.
- Every model used in a tier needs a `[pricing."<model>"]` table with numeric
  `input` and `output`. A string price is rejected.
- `timeout`, if present, must be a positive number.

Set the key:

```bash
export OPENAI_API_KEY=sk-...                     # bash
$env:OPENAI_API_KEY = "sk-..."                   # PowerShell
```

Point `--config` or `FRUGALROUTE_CONFIG` at a different config file when you keep
several.

## Usage

```bash
frugalroute ask "Summarize this changelog."
frugalroute ask "Refactor this parser and explain the trade-offs." --tier strong
frugalroute ask "$(cat prompt.txt)"
frugalroute stats
frugalroute --version
```

`ask` writes the answer to stdout and the chosen tier, model and cost to stderr,
so `frugalroute ask ... > answer.txt` stays clean.

`stats` reads the JSONL log and prints total and per-model spend:

```
model      calls    prompt  completion     cost_usd
gpt-4o-mini    3      1204         511     0.000487
gpt-4o         1       910         240     0.004675
total          4                            0.005162  (0 failed attempts)
```

Malformed log lines are skipped and counted on stderr; they never abort the report.

Exit codes: `0` success, `1` all models failed, `130` interrupted.

## Log format

Every attempt is appended to `log_path` as one JSON object per line:

| field | meaning |
| --- | --- |
| `ts` | UTC timestamp, ISO 8601 |
| `tier` | tier that was tried |
| `model` | model that was tried |
| `ok` | `true` for an answer, `false` for a failed attempt |
| `prompt_tokens` / `completion_tokens` | usage reported by the endpoint |
| `cost_usd` | price of the call, `0.0` for failures |
| `error` | present when `ok` is `false` |
| `halted` | `true` when the attempt stopped the chain (`HTTP 401`) |

If the endpoint lists a model but reports no `usage`, the answer is returned with
a warning and the call is logged at cost `0` rather than silently dropped. The
same applies when a model is somehow missing from the pricing table.

## Development

```bash
python -m pip install -e ".[dev]"
pytest                       # tests use a mocked HTTP layer, no network, no key
ruff check .
ruff format --check .
```

## Scope

Deliberately out of scope: provider-specific adapters, streaming, a web UI, a
database, PyPI publishing.

## License

MIT — see [LICENSE](LICENSE).

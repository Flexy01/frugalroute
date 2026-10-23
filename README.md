# frugalroute

Route each prompt to the cheapest model that can handle it, fall back to stronger
tiers only, and log the cost of every call.

## Install

Python 3.11+ (uses `tomllib`). No runtime dependencies.

```bash
git clone https://github.com/Flexy01/frugalroute.git
cd frugalroute
pip install -e .          # provides the `frugalroute` command
```

Or run it directly: `python frugalroute.py ...`

## Configure

Copy `config.example.toml` to `frugalroute.toml` and edit it. The API key is read
from the environment variable named by `api_key_env`; it is never stored on disk.

```toml
base_url = "https://api.openai.com/v1"   # any OpenAI-compatible endpoint
api_key_env = "OPENAI_API_KEY"
log_path = "~/.frugalroute/calls.jsonl"

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

Every model listed in `tiers` needs a `[pricing."<model>"]` block.

Set the key:

```bash
export OPENAI_API_KEY=sk-...                     # bash
$env:OPENAI_API_KEY = "sk-..."                   # PowerShell
```

## Usage

```bash
frugalroute ask "Summarize this changelog."
frugalroute ask "Refactor this parser and explain the trade-offs." --tier strong
frugalroute stats
```

`ask` classifies the prompt with cheap rules (length, code blocks, difficulty
keywords) and starts at the matching tier. If a model errors, the next model in
the chain is tried; the chain only moves toward stronger tiers, never back.
The answer goes to stdout, the chosen model and cost to stderr.

`stats` reports total and per-model spend from the JSONL log:

```
model      calls    prompt  completion     cost_usd
gpt-4o-mini    3      1204         511     0.000487
gpt-4o         1       910         240     0.004675
total          4                            0.005162  (0 failed attempts)
```

Every attempt — including failures — is appended to `log_path` as one JSON object
per line with `ts`, `tier`, `model`, `ok`, token counts, `cost_usd`, and `error`.

## Tests

```bash
pip install pytest
pytest
```

## License

MIT

"""Route each prompt to the cheapest sufficient model, with one-way fallback."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_CONFIG_PATH = "frugalroute.toml"
DEFAULT_LOG_PATH = "~/.frugalroute/calls.jsonl"

DIFFICULTY_KEYWORDS = (
    "analyze", "analyse", "architecture", "algorithm", "prove", "proof",
    "refactor", "debug", "optimi", "theorem", "derive", "mathematical",
    "step-by-step", "trade-off", "tradeoff",
)


def load_config(path=None):
    p = Path(path or os.environ.get("FRUGALROUTE_CONFIG") or DEFAULT_CONFIG_PATH).expanduser()
    try:
        with p.open("rb") as fh:
            cfg = tomllib.load(fh)
    except FileNotFoundError:
        raise SystemExit(f"config not found: {p} (see config.example.toml)")
    except tomllib.TOMLDecodeError as exc:
        raise SystemExit(f"invalid TOML in {p}: {exc}")

    missing = [key for key in ("base_url", "api_key_env", "tiers") if key not in cfg]
    if missing:
        raise SystemExit(f"{p}: missing keys: {', '.join(missing)}")
    if not cfg["tiers"]:
        raise SystemExit(f"{p}: tiers must not be empty")
    for i, tier in enumerate(cfg["tiers"]):
        if not tier.get("name") or not tier.get("models"):
            raise SystemExit(f"{p}: tier #{i} needs both 'name' and 'models'")

    pricing = cfg.setdefault("pricing", {})
    unknown = [m for tier in cfg["tiers"] for m in tier["models"] if m not in pricing]
    if unknown:
        raise SystemExit(f'{p}: missing [pricing."<model>"] for: {", ".join(unknown)}')

    cfg["base_url"] = cfg["base_url"].rstrip("/")
    cfg["log_path"] = Path(cfg.get("log_path", DEFAULT_LOG_PATH)).expanduser()
    return cfg


def classify(text, n_tiers):
    """Score a prompt with cheap rules; return a starting tier index and reasons."""
    score = 0
    reasons = []
    if len(text) > 1500:
        score += 1
        reasons.append("long")
    if len(text) > 6000:
        score += 1
        reasons.append("very-long")
    if "```" in text:
        score += 1
        reasons.append("code-block")
    hits = sum(1 for kw in DIFFICULTY_KEYWORDS if kw in text.lower())
    if hits:
        score += 1
        reasons.append("keyword")
    if hits >= 2:
        score += 1
        reasons.append("multi-keyword")
    return min(score, n_tiers - 1), reasons


def tier_index(cfg, name):
    for i, tier in enumerate(cfg["tiers"]):
        if tier["name"] == name:
            return i
    known = ", ".join(t["name"] for t in cfg["tiers"])
    raise SystemExit(f"unknown tier: {name} (have: {known})")


def fallback_chain(cfg, start):
    """Models from `start` upward only — never a weaker tier."""
    return [(tier["name"], model) for tier in cfg["tiers"][start:] for model in tier["models"]]


def _open(req, timeout):
    return urllib.request.urlopen(req, timeout=timeout)


def chat(cfg, model, prompt, timeout=60):
    key = os.environ.get(cfg["api_key_env"])
    if not key:
        raise SystemExit(f"environment variable {cfg['api_key_env']} is not set")
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(
        cfg["base_url"] + "/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    with _open(req, timeout) as resp:
        payload = json.loads(resp.read())
    text = payload["choices"][0]["message"]["content"]
    usage = payload.get("usage") or {}
    return text, int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)


def cost_usd(cfg, model, prompt_tokens, completion_tokens):
    price = cfg["pricing"][model]
    return (prompt_tokens * price["input"] + completion_tokens * price["output"]) / 1_000_000


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_call(cfg, record):
    path = cfg["log_path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def ask(cfg, prompt, tier=None):
    if tier:
        start, reasons = tier_index(cfg, tier), ["manual"]
    else:
        start, reasons = classify(prompt, len(cfg["tiers"]))

    attempts = []
    for tier_name, model in fallback_chain(cfg, start):
        try:
            text, prompt_tokens, completion_tokens = chat(cfg, model, prompt)
        except Exception as exc:  # ponytail: any failure falls forward; tighten if a provider needs classification
            error = f"{type(exc).__name__}: {exc}"
            attempts.append({"model": model, "error": error})
            log_call(cfg, {"ts": _now(), "tier": tier_name, "model": model, "ok": False,
                           "error": error, "prompt_tokens": 0, "completion_tokens": 0,
                           "cost_usd": 0.0})
            continue
        amount = cost_usd(cfg, model, prompt_tokens, completion_tokens)
        log_call(cfg, {"ts": _now(), "tier": tier_name, "model": model, "ok": True,
                       "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                       "cost_usd": amount})
        meta = {"model": model, "tier": tier_name, "tier_index": start,
                "reasons": reasons, "cost_usd": amount, "attempts": attempts}
        return text, meta

    summary = "; ".join(f"{a['model']} -> {a['error']}" for a in attempts)
    raise RuntimeError(f"all models failed: {summary}")


def stats(cfg):
    path = cfg["log_path"]
    total = 0.0
    calls = 0
    failures = 0
    per_model = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not record.get("ok"):
                failures += 1
                continue
            calls += 1
            amount = float(record.get("cost_usd", 0.0))
            total += amount
            row = per_model.setdefault(record["model"], {"calls": 0, "prompt": 0, "completion": 0, "cost": 0.0})
            row["calls"] += 1
            row["prompt"] += int(record.get("prompt_tokens", 0))
            row["completion"] += int(record.get("completion_tokens", 0))
            row["cost"] += amount

    width = max([len(m) for m in per_model] + [5])
    print(f"{'model':<{width}} {'calls':>6} {'prompt':>9} {'completion':>10} {'cost_usd':>12}")
    for model in sorted(per_model, key=lambda m: -per_model[m]["cost"]):
        row = per_model[model]
        print(f"{model:<{width}} {row['calls']:>6} {row['prompt']:>9} {row['completion']:>10} {row['cost']:>12.6f}")
    print(f"{'total':<{width}} {calls:>6} {'':>9} {'':>10} {total:>12.6f}  ({failures} failed attempts)")


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default=argparse.SUPPRESS,
                        help="path to TOML config (default: ./frugalroute.toml)")
    parser = argparse.ArgumentParser(prog="frugalroute", parents=[common],
                                     description="Route prompts to the cheapest sufficient model.")
    sub = parser.add_subparsers(dest="command", required=True)
    ask_cmd = sub.add_parser("ask", parents=[common], help="send one prompt")
    ask_cmd.add_argument("prompt")
    ask_cmd.add_argument("--tier", help="force a starting tier")
    sub.add_parser("stats", parents=[common], help="show logged spend")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    cfg = load_config(getattr(args, "config", None))
    if args.command == "ask":
        try:
            text, meta = ask(cfg, args.prompt, args.tier)
        except RuntimeError as exc:
            print(f"frugalroute: {exc}", file=sys.stderr)
            return 1
        print(text)
        print(f"[{meta['tier']}/{meta['model']}] ${meta['cost_usd']:.6f}", file=sys.stderr)
        return 0
    stats(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

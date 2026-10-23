import json

import pytest

import frugalroute as fr


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def ok(model, prompt_tokens=10, completion_tokens=5, content="hi"):
    return FakeResponse({
        "model": model,
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    })


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", "sk-test")
    return {
        "base_url": "https://example.test/v1",
        "api_key_env": "TEST_API_KEY",
        "log_path": tmp_path / "calls.jsonl",
        "tiers": [
            {"name": "cheap", "models": ["m-cheap"]},
            {"name": "standard", "models": ["m-std-1", "m-std-2"]},
            {"name": "strong", "models": ["m-strong"]},
        ],
        "pricing": {
            "m-cheap": {"input": 0.15, "output": 0.60},
            "m-std-1": {"input": 2.50, "output": 10.0},
            "m-std-2": {"input": 2.00, "output": 8.0},
            "m-strong": {"input": 10.0, "output": 30.0},
        },
    }


def read_log(cfg):
    return [json.loads(line) for line in cfg["log_path"].read_text().splitlines()]


def test_classify_short_prompt_starts_cheapest():
    index, _ = fr.classify("hello there", 3)
    assert index == 0


def test_classify_long_and_code_and_keywords_climb():
    short_code = "```print(1)```"
    assert fr.classify(short_code, 3)[0] == 1

    long_plain = "word " * 400
    assert fr.classify(long_plain, 3)[0] == 1

    hard = ("analyze this refactor step-by-step: " + "x " * 1000 + "\n```py\ncode\n```")
    index, reasons = fr.classify(hard, 3)
    assert index == 2
    assert {"long", "code-block", "keyword"} <= set(reasons)


def test_classify_ignores_substring_false_positives():
    for text in ("I disapprove of this change", "proofread this", "an optimistic estimate"):
        assert fr.classify(text, 3)[0] == 0, text


def test_classify_clamps_to_top_tier():
    assert fr.classify("analyze " * 2000 + "``` ```", 2)[0] == 1


def test_chat_rejects_error_envelope_and_empty_content(cfg, monkeypatch):
    for payload in ({"error": {"message": "overloaded"}},
                    {"choices": [{"message": {"content": None}}]},
                    {"choices": []}):
        monkeypatch.setattr(fr, "_open", lambda req, timeout, p=payload: FakeResponse(p))
        with pytest.raises(RuntimeError):
            fr.chat(cfg, "m-cheap", "hi")


def test_chat_refuses_redirect(cfg, monkeypatch):
    class Redirect:
        def redirect_request(self, *args, **kwargs):
            return fr._NoRedirect().redirect_request(*args, **kwargs)

    with pytest.raises(RuntimeError, match="redirect"):
        Redirect().redirect_request()


def test_log_call_warns_instead_of_crashing(cfg, capsys):
    cfg["log_path"] = cfg["log_path"].parent  # a directory: open("a") fails with OSError
    fr.log_call(cfg, {"ok": True})
    assert "could not write log" in capsys.readouterr().err


def test_ask_stops_on_client_error_without_retrying(cfg, monkeypatch):
    import urllib.error

    seen = []

    def fake_open(req, timeout):
        seen.append(json.loads(req.data)["model"])
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(fr, "_open", fake_open)
    with pytest.raises(SystemExit, match="401"):
        fr.ask(cfg, "hello", tier="standard")
    assert seen == ["m-std-1"]


def test_stats_survives_corrupt_line(cfg, capsys):
    cfg["log_path"].write_text('{"ok": true, "cost_usd": null}\nnot json\n')
    fr.stats(cfg)
    assert "unknown" in capsys.readouterr().out


def test_load_config_rejects_pricing_without_input(tmp_path):
    path = tmp_path / "bad2.toml"
    path.write_text(
        'base_url = "http://x"\napi_key_env = "K"\n'
        '[[tiers]]\nname = "a"\nmodels = ["m"]\n[pricing."m"]\noutput = 1.0\n'
    )
    with pytest.raises(SystemExit, match="input"):
        fr.load_config(path)


def test_fallback_chain_only_moves_up(cfg):
    chain = fr.fallback_chain(cfg, 1)
    assert [model for _, model in chain] == ["m-std-1", "m-std-2", "m-strong"]


def test_cost_usd(cfg):
    assert fr.cost_usd(cfg, "m-std-2", 1_000_000, 0) == pytest.approx(2.00)
    assert fr.cost_usd(cfg, "m-std-2", 0, 1_000_000) == pytest.approx(8.00)
    assert fr.cost_usd(cfg, "m-cheap", 1000, 500) == pytest.approx((1000 * 0.15 + 500 * 0.60) / 1_000_000)


def test_ask_success_logs_and_returns_metadata(cfg, monkeypatch):
    calls = []

    def fake_open(req, timeout):
        calls.append(json.loads(req.data))
        return ok(req.full_url, prompt_tokens=1000, completion_tokens=500)

    monkeypatch.setattr(fr, "_open", fake_open)
    text, meta = fr.ask(cfg, "hello", tier="standard")

    assert text == "hi"
    assert meta["model"] == "m-std-1"
    assert meta["tier"] == "standard"
    assert meta["cost_usd"] == pytest.approx((1000 * 2.5 + 500 * 10.0) / 1_000_000)
    assert calls[0]["messages"][0]["content"] == "hello"

    records = read_log(cfg)
    assert len(records) == 1
    assert records[0]["ok"] is True
    assert records[0]["model"] == "m-std-1"
    assert records[0]["cost_usd"] == pytest.approx(meta["cost_usd"])


def test_ask_falls_forward_on_error_and_never_back_to_weaker_tier(cfg, monkeypatch):
    seen = []

    def fake_open(req, timeout):
        model = json.loads(req.data)["model"]
        seen.append(model)
        if model == "m-std-1":
            raise RuntimeError("boom")
        return ok(model)

    monkeypatch.setattr(fr, "_open", fake_open)
    _, meta = fr.ask(cfg, "hello", tier="standard")

    assert seen == ["m-std-1", "m-std-2"]
    assert meta["model"] == "m-std-2"

    records = read_log(cfg)
    assert [r["ok"] for r in records] == [False, True]
    assert records[0]["model"] == "m-std-1"
    assert records[0]["cost_usd"] == 0.0
    assert "boom" in records[0]["error"]


def test_ask_raises_when_chain_exhausted(cfg, monkeypatch):
    def fake_open(req, timeout):
        raise RuntimeError("down")

    monkeypatch.setattr(fr, "_open", fake_open)
    with pytest.raises(RuntimeError, match="all models failed"):
        fr.ask(cfg, "hello", tier="strong")
    assert len(read_log(cfg)) == 1


def test_stats_sums_total_and_per_model(cfg, monkeypatch, capsys):
    responses = iter([ok("m-cheap", 1000, 1000, "a"), ok("m-strong", 2000, 500, "b")])
    monkeypatch.setattr(fr, "_open", lambda req, timeout: next(responses))

    fr.ask(cfg, "hello", tier="cheap")
    fr.ask(cfg, "hello", tier="strong")
    fr.stats(cfg)

    out = capsys.readouterr().out
    expected_total = (1000 * 0.15 + 1000 * 0.60) / 1_000_000 + (2000 * 10.0 + 500 * 30.0) / 1_000_000
    assert "m-cheap" in out and "m-strong" in out
    assert f"{expected_total:.6f}" in out


def test_missing_api_key_exits(cfg, monkeypatch):
    monkeypatch.delenv("TEST_API_KEY")
    monkeypatch.setattr(fr, "_open", lambda req, timeout: pytest.fail("must not send a request"))
    with pytest.raises(SystemExit, match="TEST_API_KEY"):
        fr.ask(cfg, "hello")


def test_load_config_rejects_missing_pricing(tmp_path, monkeypatch):
    path = tmp_path / "bad.toml"
    path.write_text('base_url = "http://x"\napi_key_env = "K"\n[[tiers]]\nname = "a"\nmodels = ["m"]\n')
    with pytest.raises(SystemExit, match="pricing"):
        fr.load_config(path)

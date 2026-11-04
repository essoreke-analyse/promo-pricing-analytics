"""The assistant is tested without any network call: a fake client replays what an LLM would send."""
import json
from types import SimpleNamespace as NS

from promo_pricing.assistant.agent import Assistant
from promo_pricing.assistant.tools import TOOL_SCHEMAS, TOOLS, call_tool


def tool_call(name, args, id_="call_1"):
    return NS(id=id_, function=NS(name=name, arguments=json.dumps(args)))


def response(content=None, calls=None):
    return NS(choices=[NS(message=NS(content=content, tool_calls=calls))], usage=NS(prompt_tokens=10, completion_tokens=5))


class FakeClient:
    """Returns scripted responses and records the messages it receives."""
    def __init__(self, script):
        self.script, self.seen = list(script), []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kwargs):
        self.seen.append(kwargs["messages"])
        return self.script.pop(0)


def test_every_tool_has_a_schema():
    assert {s["name"] for s in TOOL_SCHEMAS} == set(TOOLS)


def test_tool_errors_are_returned_not_raised():
    out = json.loads(call_tool("get_category_summary", {"category": "yogurt"}))
    assert "error" in out
    assert "error" in json.loads(call_tool("no_such_tool", {}))


def test_category_summary_matches_the_table():
    out = json.loads(call_tool("get_category_summary", {"category": "pizza"}))
    assert out["median_own_price_elasticity"] == -2.68


def test_agent_runs_tool_then_answers():
    client = FakeClient([
        response(calls=[tool_call("get_category_summary", {"category": "pizza"})]),
        response(content="Frozen pizza has a median elasticity of -2.68. [source: elasticity_by_category.csv]"),
    ])
    res = Assistant(client, "fake-model").ask("How price-sensitive is pizza?")
    assert res.error is None
    assert res.answer.startswith("Frozen pizza")
    assert [c["name"] for c in res.tool_calls] == ["get_category_summary"]
    # the tool result was sent back to the model before it answered
    tool_msgs = [m for m in client.seen[1] if m["role"] == "tool"]
    assert '"median_own_price_elasticity": -2.68' in tool_msgs[0]["content"]
    assert res.prompt_tokens == 20 and res.completion_tokens == 10


def test_agent_stops_after_max_steps():
    loop = [response(calls=[tool_call("get_data_quality", {})]) for _ in range(3)]
    res = Assistant(FakeClient(loop), "fake-model", max_steps=3).ask("?")
    assert "could not finish" in res.answer


def test_provider_errors_are_reported():
    class Broken:
        chat = NS(completions=NS(create=lambda **k: (_ for _ in ()).throw(RuntimeError("quota exceeded"))))
    res = Assistant(Broken(), "fake-model").ask("?")
    assert "quota exceeded" in res.error


class RateLimited(Exception):
    status_code = 429


def test_agent_waits_and_retries_on_rate_limits():
    calls = {"n": 0}
    waits = []

    def create(**kwargs):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RateLimited("429 Too Many Requests")
        return response(content="ok")

    client = NS(chat=NS(completions=NS(create=create)))
    res = Assistant(client, "fake-model", backoff_s=1, sleep=waits.append).ask("?")
    assert res.answer == "ok" and res.error is None
    assert waits == [1, 2]                      # exponential backoff, no real sleeping in tests


def test_agent_gives_up_after_max_retries():
    def create(**kwargs):
        raise RateLimited("429 Too Many Requests")
    client = NS(chat=NS(completions=NS(create=create)))
    res = Assistant(client, "fake-model", max_retries=2, sleep=lambda s: None).ask("?")
    assert res.provider_error and "429" in res.error


def test_optional_parameters_accept_null():
    # Groq rejected get_forecast_accuracy(segment=null) when the schema did not allow null (q04, q05)
    out = json.loads(call_tool("get_forecast_accuracy", {"segment": None}))
    assert out["segment"] == "all weeks"
    out = json.loads(call_tool("get_promo_performance", {"category": "pretzels", "mechanic": None, "gross_margin": None}))
    assert out["gross_margin_assumed"] == 0.35
    for schema in TOOL_SCHEMAS:
        props, required = schema["parameters"]["properties"], schema["parameters"].get("required", [])
        for name, p in props.items():
            if name not in required:
                assert "null" in p["type"], f"{schema['name']}.{name} should accept null"


def test_brands_are_returned_with_readable_names():
    out = json.loads(call_tool("get_cross_elasticity", {"category": "pizza", "brand_whose_price_changes": "DiGiorno"}))
    assert out["brand_whose_price_changes"] == "DiGiorno (Kraft)"
    assert "Private label" in [e["brand_whose_sales_move"] for e in out["effects"]]


def test_only_infrastructure_errors_are_provider_failures():
    from promo_pricing.assistant.agent import is_provider_failure

    def err(status):
        e = Exception("x"); e.status_code = status; return e
    assert is_provider_failure(err(429)) and is_provider_failure(err(503)) and is_provider_failure(err(401))
    assert not is_provider_failure(err(400))      # invalid tool call: the model's mistake

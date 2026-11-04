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

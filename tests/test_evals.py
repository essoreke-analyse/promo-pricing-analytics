"""Tests of the evaluation set itself: its expected answers must match the results tables,
and the grader must accept good answers and reject bad ones."""
import json

import pytest

from promo_pricing.assistant.evaluate import extract_numbers, grade, load_questions
from promo_pricing.assistant.tools import call_tool

QUESTIONS = load_questions()


def get_field(data, path):
    for key in str(path).split("."):
        data = data[int(key)] if isinstance(data, list) else data[key]
    return data


def test_twenty_questions_with_unique_ids():
    ids = [q["id"] for q in QUESTIONS]
    assert len(ids) == 20 and len(set(ids)) == 20


@pytest.mark.parametrize("q", [q for q in QUESTIONS if "reference" in q], ids=lambda q: q["id"])
def test_expected_answers_match_the_tools(q):
    ref = q["reference"]
    out = json.loads(call_tool(ref["tool"], ref["args"]))
    actual = float(get_field(out, ref["field"]))
    specs = [x for s in q["numbers"] for x in s.get("any_of", [s])]
    expected = [s for s in specs if abs(float(s["value"]) - actual) <= max(float(s["tol"]), abs(actual) * 0.02)]
    assert expected, f"{q['id']}: tool gives {actual}, not in {q['numbers']}"


def test_number_extraction():
    assert extract_numbers("WAPE of 28,6 % vs 45 %") == [28.6, 45.0]
    assert extract_numbers("a loss of −848 $ and spend of $387,273") == [-848.0, 387273.0]
    assert extract_numbers("387 273 $ et 436k") == [387273.0, 436000.0]


def by_id(i):
    return next(q for q in QUESTIONS if q["id"] == i)


def test_grader_accepts_a_good_answer():
    g = grade(by_id("q01"), "Frozen pizza has a median elasticity of −2.68 [source: elasticity_by_category.csv]",
              ["get_category_summary"])
    assert g["passed"] and g["grounded"]


def test_grader_accepts_share_written_as_percent():
    assert grade(by_id("q04"), "LightGBM reaches a WAPE of 28.6 %.", ["get_forecast_accuracy"])["passed"]


def test_grader_rejects_wrong_number_and_ungrounded_answer():
    g = grade(by_id("q01"), "The elasticity is about -1.5.", [])
    assert not g["passed"] and not g["grounded"]


def test_grader_accepts_equivalent_formulations():
    q = by_id("q09")
    assert grade(q, "Private label gains most: +8.5 % of units for a 10 % DiGiorno price rise.", ["get_cross_elasticity"])["passed"]
    assert grade(q, "Private label: cross-price elasticity 0.85.", ["get_cross_elasticity"])["passed"]
    assert grade(by_id("q10"), "Le présentoir, avec un ROI de 57 %.", ["get_promo_performance"])["passed"]


def test_grader_checks_refusals():
    q = by_id("q18")
    assert grade(q, "The analysis does not cover yogurt: it only includes pizza, cereal, mouthwash and pretzels.", [])["passed"]
    assert not grade(q, "Yogurt has an elasticity of -1.3.", [])["passed"]


def test_provider_errors_are_not_counted_as_wrong_answers():
    from promo_pricing.assistant.agent import AgentResult
    from promo_pricing.assistant.evaluate import run, summary_markdown

    class Down:
        def ask(self, question):
            return AgentResult(answer="", error="RateLimitError: 429", provider_error=True)

    df = run(Down(), QUESTIONS, stop_after_errors=3)
    assert len(df) == 3                         # stopped early instead of failing 20 questions
    md = summary_markdown(df, "test-model")
    assert "No question could be graded" in md and "provider errors (3)" in md


def test_summary_counts_only_graded_questions():
    from promo_pricing.assistant.agent import AgentResult
    from promo_pricing.assistant.evaluate import run, summary_markdown

    class Mixed:
        n = 0
        def ask(self, question):
            self.n += 1
            if self.n == 2:
                return AgentResult(answer="", error="RateLimitError: 429", provider_error=True)
            return AgentResult(answer="Frozen pizza: median elasticity -2.68.",
                               tool_calls=[{"name": "get_category_summary", "arguments": "{}", "result": "{}"}])

    df = run(Mixed(), [by_id("q01"), by_id("q02"), by_id("q01")])
    md = summary_markdown(df, "test-model")
    assert "Accuracy: 2 / 2" in md and "provider errors (1)" in md


def test_grader_ignores_special_hyphens():
    q = by_id("q09")
    answer = "The private‑label brand gains the most: elasticity 0.85."   # non-breaking hyphen
    assert grade(q, answer, ["get_cross_elasticity"])["passed"]


def test_invalid_tool_calls_count_as_wrong_answers():
    from promo_pricing.assistant.agent import AgentResult
    from promo_pricing.assistant.evaluate import run

    class BadCall:
        def ask(self, question):
            return AgentResult(answer="", error="BadRequestError: 400 tool call validation failed", provider_error=False)

    df = run(BadCall(), [by_id("q04")])
    assert bool(df["graded"].iloc[0]) and not df["passed"].iloc[0]

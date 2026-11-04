"""Run the evaluation set against the assistant and grade every answer automatically.

    python -m promo_pricing.assistant.evaluate --provider groq --pause 5

Writes reports/assistant_eval.csv (one line per question) and reports/assistant_eval.md (summary).
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[3]
QUESTIONS = ROOT / "evals" / "questions.yaml"

REFUSAL_WORDS = ["not cover", "does not cover", "doesn't cover", "outside", "out of scope", "not available",
                 "no data", "not in the", "cannot", "can't", "unable", "not part of", "only covers", "only cover",
                 "ne couvre pas", "ne couvre que", "hors", "pas disponible", "pas de données", "ne permet pas",
                 "ne peux pas", "n'est pas", "ne contient pas", "ne porte pas", "uniquement", "seulement"]


def load_questions(path: Path = QUESTIONS) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def extract_numbers(text: str) -> list[float]:
    """All numbers in a text, handling '−', '1,305', '387 273', French '32,6' and '$436k'."""
    t = text.replace("−", "-").replace("–", "-").replace(" ", " ").replace("\xa0", " ")
    t = re.sub(r"(?<=\d)[ ,](?=\d{3}(?!\d))", "", t)          # thousands separators
    t = re.sub(r"(?<=\d),(?=\d{1,2}(?!\d))", ".", t)            # decimal comma
    out = []
    for m in re.finditer(r"-?\d+(?:\.\d+)?\s*[kK]?", t):
        s = m.group().replace(" ", "")
        mult = 1000 if s[-1] in "kK" else 1
        out.append(float(s.rstrip("kK")) * mult)
    return out


def number_found(spec: dict, found: list[float]) -> bool:
    if "any_of" in spec:                       # several equivalent ways to state the same result
        return any(number_found(s, found) for s in spec["any_of"])
    v, tol, kind = float(spec["value"]), float(spec["tol"]), spec.get("kind", "plain")
    cands = found + ([abs(x) for x in found] + [-x for x in found] if spec.get("sign_insensitive") else [])
    for n in cands:
        if kind == "share" and (abs(n - v) <= tol or abs(n / 100 - v) <= tol):
            return True
        if kind == "money" and abs(n - v) <= abs(v) * tol:
            return True
        if kind == "plain" and abs(n - v) <= tol:
            return True
    return False


def normalise(text: str) -> str:
    """Lower case; hyphens of any kind (e.g. non-breaking '‑') and non-breaking spaces become plain spaces,
    so 'private‑label' matches 'private label'."""
    t = text.lower()
    for ch in "\u2010\u2011\u2012\u2013\u2014-\xa0\u202f":
        t = t.replace(ch, " ")
    return " ".join(t.split())


def grade(q: dict, answer: str, tool_names: list[str]) -> dict:
    """Pass if every expected number and keyword group is present (or, for out-of-scope
    questions, if the assistant declines)."""
    text = normalise(answer)
    reasons = []
    if q.get("refuse"):
        if not any(w in text for w in REFUSAL_WORDS):
            reasons.append("did not decline an out-of-scope question")
    for spec in q.get("numbers", []):
        if not number_found(spec, extract_numbers(answer)):
            reasons.append(f"missing number {spec.get('value', spec.get('any_of'))}")
    for group in q.get("keywords", []):
        if not any(normalise(w) in text for w in group):
            reasons.append(f"missing one of {group}")
    expected_tools = q.get("tools", [])
    grounded = (not expected_tools) or any(t in tool_names for t in expected_tools)
    if expected_tools and not grounded:
        reasons.append("expected tool not called")
    return {"passed": not reasons, "grounded": grounded, "reasons": "; ".join(reasons)}


def run(assistant, questions: list[dict], pause: float = 0.0, stop_after_errors: int = 3) -> pd.DataFrame:
    """Ask every question and grade it. Provider failures (quota, network) are recorded as
    'not graded' rather than as wrong answers; the run stops after a few consecutive ones."""
    rows, consecutive = [], 0
    for q in questions:
        res = assistant.ask(q["question"])
        names = [c["name"] for c in res.tool_calls]
        failed = bool(res.error) and res.provider_error        # quota / network: not the model's fault
        if failed:
            g = {"passed": None, "grounded": None, "reasons": res.error}
        elif res.error:                                          # e.g. invalid tool call: the model failed
            g = {"passed": False, "grounded": bool(names), "reasons": res.error}
        else:
            g = grade(q, res.answer, names)
        rows.append({"id": q["id"], "type": q["type"], "question": q["question"], "answer": res.answer,
                     "tools_called": ", ".join(names), "graded": not failed, **g,
                     "latency_s": round(res.latency_s, 2),
                     "prompt_tokens": res.prompt_tokens, "completion_tokens": res.completion_tokens})
        consecutive = consecutive + 1 if failed else 0
        if consecutive >= stop_after_errors:
            print(f"Stopped: {consecutive} provider errors in a row ({res.error}). "
                  "Check the API key, the account limits, or wait and retry.")
            break
        time.sleep(pause)   # free tiers limit requests per minute
    return pd.DataFrame(rows)


def summary_markdown(df: pd.DataFrame, model: str) -> str:
    graded = df[df["graded"]]
    errors = df[~df["graded"]]
    lines = [f"# Assistant evaluation — {model}", ""]
    if len(graded):
        passed = int(graded["passed"].astype(bool).sum())
        by_type = graded.groupby("type").agg(questions=("id", "count"),
                                             passed=("passed", lambda x: int(x.astype(bool).sum())))
        by_type["accuracy"] = (100 * by_type["passed"] / by_type["questions"]).round(0).astype(int).astype(str) + " %"
        lines += [f"**Accuracy: {passed} / {len(graded)} ({100 * passed / len(graded):.0f} %)** · "
                  f"grounded in tools: {100 * graded['grounded'].astype(bool).mean():.0f} % · "
                  f"median latency {graded['latency_s'].median():.1f} s · "
                  f"tokens: {graded['prompt_tokens'].sum():,} in, {graded['completion_tokens'].sum():,} out", "",
                  "| Question type | Questions | Passed | Accuracy |", "|---|---|---|---|"]
        lines += [f"| {t} | {r.questions} | {r.passed} | {r.accuracy} |" for t, r in by_type.iterrows()]
        fails = graded[~graded["passed"].astype(bool)]
        if len(fails):
            lines += ["", "## Wrong answers", "", "| id | question | reason |", "|---|---|---|"]
            lines += [f"| {r.id} | {r.question} | {r.reasons} |" for r in fails.itertuples()]
    else:
        lines += ["**No question could be graded.**"]
    if len(errors):
        lines += ["", f"## Not graded: provider errors ({len(errors)})", "",
                  "These are failures of the API (quota, network), not mistakes of the model.", "",
                  "| id | error |", "|---|---|"]
        lines += [f"| {r.id} | {r.reasons} |" for r in errors.itertuples()]
    return "\n".join(lines) + "\n"


def main(argv=None) -> None:
    from promo_pricing.assistant.agent import Assistant, make_client

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--provider", default=None, help="groq, mistral, openai or ollama (default: LLM_PROVIDER, else groq)")
    p.add_argument("--model", default=None)
    p.add_argument("--pause", type=float, default=1.0, help="seconds between questions (free-tier rate limits)")
    p.add_argument("--only", nargs="*", help="question ids to run, e.g. q01 q12")
    args = p.parse_args(argv)

    client, model = make_client(args.provider)
    model = args.model or model
    questions = [q for q in load_questions() if not args.only or q["id"] in args.only]
    df = run(Assistant(client, model), questions, args.pause)
    out = ROOT / "reports"
    df.to_csv(out / "assistant_eval.csv", index=False)
    (out / "assistant_eval.md").write_text(summary_markdown(df, model), encoding="utf-8")
    print(summary_markdown(df, model))


if __name__ == "__main__":
    main()

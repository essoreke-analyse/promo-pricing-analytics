# Analytics assistant: design, evaluation and deployment

## Design

The assistant answers questions about the study's results in plain language (English or French).
The language model is **not trusted with numbers**: it only decides which tool to call and how to phrase the answer.

```
question ──► LLM ──► tool call (JSON) ──► Python tool reads reports/tables/*.csv ──► result (JSON)
                ▲                                                                      │
                └──────────────────────── result sent back ◄────────────────────────────┘
             answer citing its source table
```

| Tool | What it returns | Table |
|---|---|---|
| `find_products` | products matching a name or brand, with their code | `products.csv` |
| `get_category_summary` | median elasticity, effect and break-even margin of a 10 % price cut | `elasticity_by_category.csv` |
| `get_product_elasticity` | elasticity of one product with its 95 % interval and promotion effects | `own_price_elasticities.csv` |
| `get_cross_elasticity` | effect of one brand's price on the other brands | `cross_price_elasticities.csv` |
| `get_promo_performance` | baseline vs incremental volume, trade spend, profit, ROI by mechanic | `promo_volume_decomposition.csv`, `promo_roi.csv` |
| `get_forecast_accuracy` | WAPE, bias and P10–P90 coverage of the forecast models | `forecast_backtest_metrics.csv` |
| `simulate_promotion` | what-if for one product: volume, revenue, profit, ROI | simulator |
| `get_data_quality` | results of the data-quality checks | `data_quality.csv` |

Design choices:
- **Grounding:** the system prompt forbids numbers that do not come from a tool result in the conversation, and asks for the source table.
- **Errors as feedback:** a wrong argument (unknown product, unknown category) returns an error message to the model, which can correct itself — for example by calling `find_products` first.
- **Scope:** questions outside the study (other products, general knowledge) must be declined.
- **Provider-agnostic:** any OpenAI-compatible API (Mistral, Groq, OpenAI, local Ollama), `temperature = 0`, at most 6 tool rounds.
- **Testable without a model:** `tests/test_assistant.py` replays scripted LLM responses through the real loop.

Code: `src/promo_pricing/assistant/` (`tools.py`, `agent.py`, `evaluate.py`).

## Evaluation

`evals/questions.yaml` holds 20 questions in 5 types: lookup (6), comparison (4), simulation (4), multi-step (3) and out-of-scope (3), in English and French. Each question states what a correct answer must contain:

- **numbers** with a tolerance, accepting equivalent forms (0.326 or 32.6 %, −848 or "a loss of $848", 1,305 or 1 305);
- **keywords** (for example "private label" when asked which brand gains most);
- **refusal** for out-of-scope questions;
- the **tools** expected, to measure whether answers are grounded.

`tests/test_evals.py` checks that every expected number still matches the result tables, so the evaluation set cannot silently drift when the analysis changes, and that the grader accepts good answers and rejects bad ones.

Run it with your key (free tiers limit requests per minute, hence the pause):

```bash
# Windows PowerShell
$env:LLM_PROVIDER="mistral"; $env:LLM_API_KEY="your-key"
python -m promo_pricing.assistant.evaluate --pause 2

# macOS / Linux
LLM_PROVIDER=mistral LLM_API_KEY=your-key python -m promo_pricing.assistant.evaluate --pause 2
```

It writes `reports/assistant_eval.md` (accuracy overall and by question type, grounding rate, latency, tokens, list of failures) and `reports/assistant_eval.csv` (every question, answer, tools called and reason for failure). The app shows the summary in the "Ask the data" tab.

To compare models, run it with `--provider groq` or `--model mistral-large-latest` and keep each report.

## Running and deploying the app

```bash
pip install -e ".[dev,app]"
streamlit run app/streamlit_app.py
```

The app reads only `reports/tables/` and `reports/figures/` (aggregated results, committed to the repository), so it runs without the raw data.

Free deployment on **Streamlit Community Cloud**:
1. Sign in at share.streamlit.io with your GitHub account.
2. "Create app" → repository `promo-pricing-analytics`, branch `main`, main file `app/streamlit_app.py`.
3. Optional — to let visitors use the assistant without their own key, add in *Advanced settings → Secrets*:
   ```toml
   LLM_PROVIDER = "mistral"
   LLM_API_KEY = "your-key"
   ```
   The app limits each session to 20 questions. Never commit the key: `.streamlit/secrets.toml` is in `.gitignore`.

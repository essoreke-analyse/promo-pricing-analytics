"""Promo & Pricing Analytics — interactive app.

Run locally:   streamlit run app/streamlit_app.py
Uses only the aggregated result tables in reports/tables/ (no raw data).
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from promo_pricing.simulator import load_inputs, simulate  # noqa: E402

TABLES, FIGURES = ROOT / "reports" / "tables", ROOT / "reports" / "figures"
REPO = "https://github.com/essoreke-analyse/promo-pricing-analytics"
CAT_LABEL = {"COLD CEREAL": "Cold cereal", "FROZEN PIZZA": "Frozen pizza", "BAG SNACKS": "Pretzels",
             "ORAL HYGIENE PRODUCTS": "Mouthwash"}
CAT_ORDER = ["Frozen pizza", "Cold cereal", "Mouthwash", "Pretzels"]
ORANGE, BLUE, GREY, INK2 = "#eb6834", "#2a78d6", "#8a8984", "#52514e"
MAX_QUESTIONS = 20

st.set_page_config(page_title="Promo & Pricing Analytics", page_icon="📊", layout="wide")


@st.cache_data
def table(name: str) -> pd.DataFrame:
    return pd.read_csv(TABLES / name)


@st.cache_data
def sim_inputs() -> pd.DataFrame:
    return load_inputs(TABLES)


def pct(x, signed=False, nd=0):
    return f"{x:+.{nd}%}" if signed else f"{x:.{nd}%}"


def money(x, signed=False):
    s = f"${abs(x):,.0f}"
    return (("+" if x >= 0 else "−") + s) if signed else s


def kpi(col, label, value, note):
    """A headline number with a neutral note (st.metric deltas would show misleading arrows)."""
    col.metric(label, value)
    col.caption(note.replace("$", r"\$"))      # a pair of $ would be read as a LaTeX formula


def layout(fig, height=360, **kw):
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=40, b=10), legend=dict(orientation="h", y=-0.18),
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", **kw)
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.2)", zeroline=False)
    return fig


# ---------------- sidebar ----------------
with st.sidebar:
    st.markdown("### Promo & Pricing Analytics")
    st.caption("Price elasticity, promotion uplift and weekly forecasting on dunnhumby *Breakfast at the Frat*: "
               "4 categories, 55 products, 77 US stores, 156 weeks (2009–2012).")
    st.markdown(f"[Code and notebooks]({REPO}) · [Two-page client note]({REPO}/blob/main/reports/client_note.pdf)")
    st.caption("Built by Essoréké Kiheou. Only aggregated results are shown; the raw data is not redistributed.")

tab_overview, tab_sim, tab_fc, tab_ai = st.tabs(["Overview", "Promotion simulator", "Forecast", "Ask the data (AI)"])

# ---------------- overview ----------------
with tab_overview:
    st.subheader("What pays off in promotions and pricing")
    roi = table("promo_roi.csv")
    r35 = roi[roi["gross_margin"] == 0.35]
    tpr = r35[r35["mechanic"] == "TPR only"]
    fm = table("forecast_backtest_metrics.csv").query("segment == 'all weeks'").set_index("model")
    el = table("elasticity_by_category.csv").set_index("category")
    c1, c2, c3, c4 = st.columns(4)
    kpi(c1, "Most price-sensitive", "Frozen pizza",
        f"median elasticity {el.loc['FROZEN PIZZA', 'median_elasticity']:.1f}: a 10 % price cut adds about 33 % volume")
    kpi(c2, "Lost by price-cut-only promos", money(-tpr["incremental_profit"].sum()),
        f"gross profit, on {money(tpr['trade_spend'].sum())} of discounts, at a 35 % margin")
    kpi(c3, "Forecast error (WAPE)", pct(fm.loc["lightgbm", "wape"]),
        f"LightGBM, vs {pct(fm.loc['moving_average', 'wape'])} for a moving average")
    kpi(c4, "Low–high range coverage", pct(fm.loc["lightgbm P10-P90", "coverage"]),
        "share of actual sales inside P10–P90 (target 80 %)")

    left, right = st.columns(2)
    with left:
        st.markdown("**Where promoted volume comes from**")
        st.image(str(FIGURES / "07_promo_volume_decomposition.png"), width="stretch")
        st.caption("A price cut alone mostly discounts sales that would have happened anyway; feature and display create the extra volume.")
    with right:
        st.markdown("**Which promotions can pay off**")
        st.image(str(FIGURES / "08_breakeven_margin.png"), width="stretch")
        st.caption("Break-even gross margin per promoted week: TPR-only promotions need margins far above normal grocery levels.")

# ---------------- simulator ----------------
with tab_sim:
    st.subheader("What if we promoted this product next week?")
    inp = sim_inputs()
    col_in, col_out = st.columns([1, 2], gap="large")
    with col_in:
        cat = st.selectbox("Category", CAT_ORDER)
        prods = inp[inp["category_label"] == cat].sort_values("product_name")
        name = st.selectbox("Product", prods["product_name"])
        upc = int(prods.loc[prods["product_name"] == name, "upc"].iloc[0])
        price_change = -st.slider("Price cut (%)", 0, 50, 15, step=5) / 100
        feature = st.checkbox("Feature in the circular")
        display = st.checkbox("In-store display")
        margin = st.slider("Gross margin on the regular price (%)", 15, 60, 35, step=5) / 100
    s = simulate(inp, upc, price_change, feature, display, margin)
    with col_out:
        m1, m2, m3 = st.columns(3)
        m1.metric("Units, all stores, one week", f"{s.chain_units:,.0f}", pct(s.volume_change, signed=True))
        kpi(m2, "Gross profit vs no promotion", money(s.chain_profit_change, signed=True),
            f"{s.roi:+.2f} $ of profit per $ of discount (ROI)" if s.roi is not None else "no discount given")
        kpi(m3, "Break-even gross margin", pct(s.breakeven_margin) if s.breakeven_margin else "—",
            "the promotion adds profit above this margin")
        for w in s.warnings:
            st.warning(w)

        # profit for every discount depth with the same support: shows the best depth at a glance
        depths = np.arange(0, 0.51, 0.05)
        prof = [simulate(inp, upc, -d, feature, display, margin).chain_profit_change for d in depths]
        fig = go.Figure()
        fig.add_bar(x=[f"{d:.0%}" for d in depths], y=prof,
                    marker_color=[ORANGE if abs(d + price_change) < 1e-9 else (BLUE if p >= 0 else GREY) for d, p in zip(depths, prof)],
                    hovertemplate="discount %{x}<br>profit change %{y:$,.0f}<extra></extra>")
        fig.add_hline(y=0, line_color=INK2, line_width=1)
        support = " + ".join([x for x, on in [("feature", feature), ("display", display)] if on]) or "no support"
        st.plotly_chart(layout(fig, title=f"Gross profit change by discount depth ({support}, {margin:.0%} margin)",
                               xaxis_title="price cut", yaxis_title="$ vs no promotion", showlegend=False,
                               xaxis_type="category", yaxis_tickprefix="$", yaxis_tickformat=",.0f"),
                        width="stretch")
        st.caption(f"Orange = your scenario. Elasticity {s.elasticity:.2f} (shrunk estimate), "
                   f"{s.normal_units_per_store:.1f} units per store in a normal week at \\${s.base_price:.2f}, {s.n_stores} stores. "
                   "Fees for the circular or the display are not included.")

# ---------------- forecast ----------------
with tab_fc:
    st.subheader("Weekly forecast, 1 to 4 weeks ahead — backtest")
    metrics = table("forecast_backtest_metrics.csv")
    seg = st.radio("Weeks", ["all weeks", "promotion weeks", "weeks without promotion"], horizontal=True)
    m = metrics[(metrics["segment"] == seg) & (metrics["model"] != "lightgbm P10-P90")].copy()
    names = {"seasonal_naive": "Same week last year", "moving_average": "Moving average",
             "regression": "Regression", "lightgbm": "LightGBM"}
    m["model"] = m["model"].map(names)
    a, b = st.columns(2)
    with a:
        fig = go.Figure(go.Bar(x=m["model"], y=100 * m["wape"], marker_color=[GREY, GREY, BLUE, ORANGE],
                               text=[f"{v:.0%}" for v in m["wape"]], textposition="outside"))
        st.plotly_chart(layout(fig, title="Error (WAPE) — lower is better", yaxis_title="%"), width="stretch")
    with b:
        fig = go.Figure(go.Bar(x=m["model"], y=100 * m["bias"], marker_color=[GREY, GREY, BLUE, ORANGE],
                               text=[f"{v:+.0%}" for v in m["bias"]], textposition="outside"))
        st.plotly_chart(layout(fig, title="Bias: + overstock risk, − stock-out risk", yaxis_title="%"), width="stretch")

    st.markdown("**Example series: forecast and low–high scenario**")
    ex = table("forecast_examples.csv")
    products = table("products.csv").set_index("upc")
    ex["label"] = ex["upc"].map(products["product_name"]) + " — store " + ex["store_id"].astype(str)
    choice = st.selectbox("Series", ex["label"].unique())
    e = ex[ex["label"] == choice].sort_values("week")
    fig = go.Figure()
    fig.add_scatter(x=e["week"], y=e["lightgbm_p90"], line=dict(width=0), showlegend=False, hoverinfo="skip")
    fig.add_scatter(x=e["week"], y=e["lightgbm_p10"], fill="tonexty", fillcolor="rgba(235,104,52,0.2)",
                    line=dict(width=0), name="low–high scenario (P10–P90)")
    fig.add_scatter(x=e["week"], y=e["units"], name="actual", line=dict(color="#0b0b0b", width=2))
    fig.add_scatter(x=e["week"], y=e["lightgbm"], name="LightGBM", line=dict(color=ORANGE, width=2.5))
    fig.add_scatter(x=e["week"], y=e["moving_average"], name="moving average", line=dict(color=GREY, dash="dot"))
    for wk in e.loc[e["any_promo"] == 1, "week"]:
        fig.add_vrect(x0=pd.Timestamp(wk) - pd.Timedelta(days=3.5), x1=pd.Timestamp(wk) + pd.Timedelta(days=3.5),
                      fillcolor="rgba(128,128,128,0.15)", line_width=0)
    st.plotly_chart(layout(fig, height=380, yaxis_title="units per week", yaxis_rangemode="tozero"), width="stretch")
    st.caption("Grey bands = promotion weeks. The promotion plan is known in advance; only sales at least 4 weeks old are used.")

# ---------------- AI assistant ----------------
with tab_ai:
    st.subheader("Ask the data")
    st.caption("An LLM answers questions about the results by calling tools that read the result tables: "
               "every number comes from the analysis, not from the model's memory.")

    def secret(name):
        try:
            return st.secrets.get(name) or os.getenv(name)
        except Exception:
            return os.getenv(name)

    provider = secret("LLM_PROVIDER") or "groq"
    key = secret("LLM_API_KEY")
    with st.expander("Model settings", expanded=not key):
        providers = ["groq", "mistral", "openai", "ollama"]
        provider = st.selectbox("Provider", providers, index=providers.index(provider))
        typed = st.text_input("API key (kept for this session only)", type="password",
                              help="Free key: console.groq.com. Not needed for a local Ollama model.")
        key = typed or key

    eval_md = ROOT / "reports" / "assistant_eval.md"
    if eval_md.exists():
        with st.expander("How reliable is it? Results on the 20-question evaluation set"):
            st.markdown(eval_md.read_text(encoding="utf-8"))

    examples = ["Which category is the most price-sensitive?",
                "When DiGiorno raises its price, which brand gains the most?",
                "Simulate a 20 % discount with a display on Snyder's pretzel rods at a 35 % margin.",
                "Quel mécanisme promo est le plus rentable pour les bretzels ?"]
    cols = st.columns(len(examples))
    clicked = next((q for c, q in zip(cols, examples) if c.button(q, width="stretch")), None)

    st.session_state.setdefault("chat", [])
    for msg in st.session_state["chat"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("tools"):
                with st.expander(f"How I got this — {len(msg['tools'])} tool call(s)"):
                    for t in msg["tools"]:
                        st.code(f"{t['name']}({t['arguments']})\n→ {t['result'][:600]}", language="text")

    question = st.chat_input("Ask about elasticities, promotions, ROI or the forecast…") or clicked
    if question:
        asked = sum(m["role"] == "user" for m in st.session_state["chat"])
        if asked >= MAX_QUESTIONS:
            st.info("Question limit reached for this session.")
        elif not key and provider != "ollama":
            st.info("Add an API key in 'Model settings' to use the assistant.")
        else:
            from promo_pricing.assistant.agent import Assistant, make_client
            st.session_state["chat"].append({"role": "user", "content": question})
            with st.spinner("Looking it up…"):
                client, model = make_client(provider, api_key=key)
                res = Assistant(client, model).ask(question)
            answer = res.answer if not res.error else f"⚠️ The model could not answer: {res.error}"
            st.session_state["chat"].append({"role": "assistant", "content": answer, "tools": res.tool_calls})
            st.rerun()

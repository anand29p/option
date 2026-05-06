from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from string import Template

import pandas as pd
import streamlit as st
from tinydb import TinyDB

from config.settings import IST, LOG_DIR, PAPER_CAPITAL, TRADE_LOG
from utils.global_context import get_global_context
from utils.news_sentiment import get_news_sentiment


st.set_page_config(page_title="Nifty Bot Dashboard", page_icon="📈", layout="wide")


def _inject_styles(dark_mode: bool = False) -> None:
    if dark_mode:
        bg_gradient = "radial-gradient(circle at 0% 0%, #111523 0%, #131a2c 38%, #0f1422 100%)"
        hero_gradient = "linear-gradient(125deg, #0f172a 0%, #1f2b4d 48%, #134e4a 100%)"
        card_bg = "#161d2f"
        card_border = "#283146"
        ink = "#e8edf7"
        muted = "#a9b4cb"
        tag_neutral_bg = "#3a341d"
        section_bg = "#161d2f"
        headline_bg = "#163332"
    else:
        bg_gradient = "radial-gradient(circle at 0% 0%, #eef6ff 0%, #f8fbff 35%, #fcfdff 100%)"
        hero_gradient = "linear-gradient(125deg, #0f172a 0%, #162a52 55%, #0f766e 100%)"
        card_bg = "#ffffff"
        card_border = "#e8edf5"
        ink = "#131722"
        muted = "#5f6678"
        tag_neutral_bg = "#fff6dc"
        section_bg = "#ffffff"
        headline_bg = "#f3fbfa"

    css = Template(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@500;700&display=swap');

        :root {
            --bg-soft: #f5f7fb;
            --ink: $ink;
            --muted: $muted;
            --accent: #0f766e;
            --accent-soft: #e7f6f3;
            --good: #137333;
            --bad: #c62828;
            --neutral: #7a5c00;
            --card-shadow: 0 8px 26px rgba(19, 23, 34, 0.08);
        }

        html, body, [class*="css"] {
            font-family: 'Space Grotesk', sans-serif;
            color: var(--ink);
        }

        .stApp {
            background: $bg_gradient;
        }

        .hero-wrap {
            padding: 1.1rem 1.2rem;
            border-radius: 16px;
            background: $hero_gradient;
            color: #ffffff;
            box-shadow: var(--card-shadow);
            margin-bottom: 1rem;
        }

        .hero-title {
            margin: 0;
            font-size: 2rem;
            letter-spacing: 0.2px;
            font-weight: 700;
        }

        .hero-sub {
            margin: 0.25rem 0 0 0;
            color: rgba(255, 255, 255, 0.85);
            font-size: 0.98rem;
        }

        .metric-card {
            padding: 0.9rem 1rem;
            border-radius: 14px;
            background: $card_bg;
            border: 1px solid $card_border;
            box-shadow: var(--card-shadow);
            min-height: 102px;
        }

        .metric-label {
            color: var(--muted);
            font-size: 0.82rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 0.3rem;
            font-weight: 600;
        }

        .metric-value {
            color: var(--ink);
            font-size: 2rem;
            line-height: 1.05;
            font-weight: 700;
        }

        .metric-value-mono {
            color: var(--ink);
            font-size: 2rem;
            line-height: 1.05;
            font-family: 'JetBrains Mono', monospace;
            font-weight: 700;
        }

        .section-card {
            padding: 1rem;
            border-radius: 14px;
            border: 1px solid $card_border;
            background: $section_bg;
            box-shadow: var(--card-shadow);
        }

        .tag {
            display: inline-block;
            padding: 0.2rem 0.55rem;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0.4px;
            margin-right: 0.45rem;
        }

        .tag-good { background: #e8f5ea; color: var(--good); }
        .tag-bad { background: #fdeaea; color: var(--bad); }
        .tag-neutral { background: $tag_neutral_bg; color: var(--neutral); }
        .tag-accent { background: var(--accent-soft); color: var(--accent); }

        .headline-box {
            border-left: 4px solid #0f766e;
            padding: 0.55rem 0.65rem;
            margin-bottom: 0.45rem;
            border-radius: 8px;
            background: $headline_bg;
        }

        .heat-grid-card {
            padding: 0.6rem 0.7rem;
            border-radius: 12px;
            border: 1px solid $card_border;
            background: $card_bg;
            box-shadow: var(--card-shadow);
            min-height: 88px;
        }

        .heat-title {
            color: var(--muted);
            font-size: 0.78rem;
            text-transform: uppercase;
            font-weight: 600;
            margin-bottom: 0.28rem;
        }

        .heat-price {
            color: var(--ink);
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
            font-size: 1.1rem;
            margin-bottom: 0.15rem;
        }

        .heat-up { color: #14a44d; font-weight: 700; }
        .heat-down { color: #ef4444; font-weight: 700; }
        .heat-flat { color: #9ca3af; font-weight: 700; }

        .small-note {
            color: var(--muted);
            font-size: 0.85rem;
        }
        </style>
        """
    ).substitute(
        ink=ink,
        muted=muted,
        bg_gradient=bg_gradient,
        hero_gradient=hero_gradient,
        card_bg=card_bg,
        card_border=card_border,
        tag_neutral_bg=tag_neutral_bg,
        section_bg=section_bg,
        headline_bg=headline_bg,
    )
    st.markdown(css, unsafe_allow_html=True)


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _sentiment_color(label: str) -> str:
    mapping = {
        "BULLISH": "green",
        "BEARISH": "red",
        "NEUTRAL": "orange",
    }
    return mapping.get((label or "").upper(), "gray")


def _bias_class(label: str) -> str:
    value = (label or "").upper()
    if value == "BULLISH":
        return "tag-good"
    if value == "BEARISH":
        return "tag-bad"
    return "tag-neutral"


def _trend_arrow(pct_value: float) -> str:
    if pct_value > 0:
        return "▲"
    if pct_value < 0:
        return "▼"
    return "●"


def _trend_class(pct_value: float) -> str:
    if pct_value > 0:
        return "heat-up"
    if pct_value < 0:
        return "heat-down"
    return "heat-flat"


def _render_metric_card(label: str, value: str, mono: bool = False) -> None:
    cls = "metric-value-mono" if mono else "metric-value"
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="{cls}">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=60)
def load_global(force: bool = False) -> dict:
    try:
        return get_global_context(force=force).to_dict()
    except Exception as e:
        return {"error": str(e)}


@st.cache_data(ttl=120)
def load_sentiment(force: bool = False) -> dict:
    try:
        return get_news_sentiment(force=force).to_dict()
    except Exception as e:
        return {"error": str(e)}


@st.cache_data(ttl=30)
def load_trades(limit: int = 100) -> list[dict]:
    db_path = Path(LOG_DIR) / "paper_trades.json"
    if not db_path.exists() or db_path.stat().st_size == 0:
        return []

    try:
        db = TinyDB(str(db_path))
        rows = db.all()
    except Exception:
        return []

    rows = sorted(rows, key=lambda x: x.get("date", ""), reverse=True)
    return rows[:limit]


@st.cache_data(ttl=30)
def load_daily_pnl() -> pd.DataFrame:
    csv_path = Path(TRADE_LOG)
    if not csv_path.exists():
        return pd.DataFrame(columns=["date", "net_pnl"])

    daily: dict[str, float] = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            date = row.get("date", "")
            net_pnl = _safe_float(row.get("net_pnl", 0), 0.0)
            if date:
                daily[date] = daily.get(date, 0.0) + net_pnl

    if not daily:
        return pd.DataFrame(columns=["date", "net_pnl"])

    out = pd.DataFrame(
        {"date": sorted(daily.keys())}
    )
    out["net_pnl"] = out["date"].map(daily).round(2)
    out["cum_pnl"] = out["net_pnl"].cumsum().round(2)
    return out


def render_header() -> None:
    now = datetime.now(IST)
    st.markdown(
        f"""
        <div class="hero-wrap">
            <h1 class="hero-title">Nifty Bot Control Surface</h1>
            <p class="hero-sub">Live paper-trading intelligence with global context and sentiment overlays • {now.strftime('%a %d %b %Y')}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


if "ui_dark_mode" not in st.session_state:
    st.session_state.ui_dark_mode = False

_inject_styles(dark_mode=bool(st.session_state.ui_dark_mode))


# Header controls
refresh_col, clear_col, dark_col, cap_col, clock_col = st.columns([1, 1, 1, 2, 1])
with refresh_col:
    if st.button("Refresh Now", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
with clear_col:
    if st.button("Clear Cache", use_container_width=True):
        st.cache_data.clear()
with dark_col:
    dark_mode = st.toggle("Dark Mode", value=bool(st.session_state.ui_dark_mode))
    if dark_mode != bool(st.session_state.ui_dark_mode):
        st.session_state.ui_dark_mode = dark_mode
        st.rerun()
with cap_col:
    st.info("Tip: Streamlit Cloud may sleep when inactive on free tier.")
with clock_col:
    st.markdown(f"<div class='section-card'><div class='metric-label'>TIME (IST)</div><div class='metric-value-mono'>{datetime.now(IST).strftime('%H:%M:%S')}</div></div>", unsafe_allow_html=True)

render_header()

# Top metrics
global_ctx = load_global(force=True)
sent = load_sentiment(force=True)
trades = load_trades(limit=200)
pnl_df = load_daily_pnl()

closed_count = len(trades)
realized = _safe_float(pnl_df["net_pnl"].sum(), 0.0) if not pnl_df.empty else 0.0
capital_now = PAPER_CAPITAL + realized

m1, m2, m3, m4 = st.columns(4)
with m1:
    _render_metric_card("Mode", "PAPER")
with m2:
    _render_metric_card("Closed Trades", f"{closed_count}", mono=True)
with m3:
    _render_metric_card("Realized P&L", f"{realized:,.2f}", mono=True)
with m4:
    _render_metric_card("Capital", f"{capital_now:,.2f}", mono=True)

# Market and sentiment
left, right = st.columns([3, 2])

with left:
    st.subheader("Global Market Context")
    if "error" in global_ctx:
        st.error(global_ctx["error"])
    else:
        st.markdown("<div class='section-card'>", unsafe_allow_html=True)
        st.markdown(
            f"""
            <span class="tag tag-accent">Provider: {global_ctx.get('provider', 'NA')}</span>
            <span class="tag {_bias_class(global_ctx.get('overall_bias', 'NEUTRAL'))}">Overall: {global_ctx.get('overall_bias', 'NEUTRAL')}</span>
            <span class="tag {_bias_class(global_ctx.get('us_bias', 'NEUTRAL'))}">US: {global_ctx.get('us_bias', 'NEUTRAL')}</span>
            <span class="tag {_bias_class(global_ctx.get('asia_bias', 'NEUTRAL'))}">Asia: {global_ctx.get('asia_bias', 'NEUTRAL')}</span>
            """,
            unsafe_allow_html=True,
        )

        gc1, gc2, gc3 = st.columns(3)
        gc1.metric("GIFT Nifty Change", f"{_safe_float(global_ctx.get('gift_nifty_chg', 0.0)):+.3f}%")
        gc2.metric("Crude Change", f"{_safe_float(global_ctx.get('crude_chg', 0.0)):+.3f}%")
        gc3.metric("Snapshot Time", str(global_ctx.get("timestamp", "NA")))

        prices = global_ctx.get("prices", {})
        pct = global_ctx.get("pct_changes", {})
        if prices:
            rows = []
            for name, price in prices.items():
                pct_change = round(_safe_float(pct.get(name, 0.0)), 3)
                rows.append(
                    {
                        "move": _trend_arrow(pct_change),
                        "symbol": name,
                        "price": round(_safe_float(price), 2),
                        "pct_change": pct_change,
                        "trend": "UP" if pct_change > 0 else ("DOWN" if pct_change < 0 else "FLAT"),
                    }
                )
            market_df = pd.DataFrame(rows).sort_values("pct_change", ascending=False)

            st.markdown("#### Market Heat")
            heat_rows = market_df.to_dict("records")
            cols_per_row = 4
            for i in range(0, len(heat_rows), cols_per_row):
                chunk = heat_rows[i:i + cols_per_row]
                cols = st.columns(len(chunk))
                for col, row in zip(cols, chunk):
                    pct_value = _safe_float(row.get("pct_change", 0.0), 0.0)
                    with col:
                        st.markdown(
                            f"""
                            <div class="heat-grid-card">
                                <div class="heat-title">{row.get('symbol', '')}</div>
                                <div class="heat-price">{_safe_float(row.get('price', 0.0), 0.0):,.2f}</div>
                                <div class="{_trend_class(pct_value)}">{_trend_arrow(pct_value)} {pct_value:+.3f}%</div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

            st.markdown("#### Symbol Table")
            st.dataframe(
                market_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "move": st.column_config.TextColumn(" "),
                    "symbol": st.column_config.TextColumn("Symbol"),
                    "price": st.column_config.NumberColumn("Price", format="%.2f"),
                    "pct_change": st.column_config.NumberColumn("% Change", format="%.3f"),
                    "trend": st.column_config.TextColumn("Trend"),
                },
            )
        else:
            st.warning("No global market data available right now.")
        st.markdown("</div>", unsafe_allow_html=True)

with right:
    st.subheader("News Sentiment & Events")
    if "error" in sent:
        st.error(sent["error"])
    else:
        st.markdown("<div class='section-card'>", unsafe_allow_html=True)
        label = str(sent.get("label", "NEUTRAL"))
        color = _sentiment_color(label)
        st.markdown(f"### :{color}[{label}]")
        
        # Main metrics
        m_col1, m_col2, m_col3 = st.columns(3)
        with m_col1:
            st.metric("Score", f"{_safe_float(sent.get('score', 0.0)):+.3f}")
        with m_col2:
            st.metric("Confidence", f"{_safe_float(sent.get('confidence', 0.0))*100:.0f}%")
        with m_col3:
            st.metric("Headlines", sent.get('headline_count', 0))
        
        # Event type display
        event_type = str(sent.get("event_type", "OTHER")).upper()
        event_tag_class = "tag-good" if event_type in ["EARNINGS", "POSITIVE"] else (
            "tag-bad" if event_type in ["LOSS", "NEGATIVE"] else "tag-neutral"
        )
        st.markdown(
            f"<span class='tag {event_tag_class}'>Event: {event_type}</span>",
            unsafe_allow_html=True,
        )
        
        # Active events breakdown
        active_events = sent.get("active_events", [])
        if active_events:
            st.markdown("<div class='small-note'><b>Active Events</b></div>", unsafe_allow_html=True)
            event_cols = st.columns(min(3, len(active_events)))
            for idx, event in enumerate(active_events[:3]):
                with event_cols[idx % 3]:
                    st.markdown(f"<div class='tag tag-accent'>{event}</div>", unsafe_allow_html=True)
        
        # Sentiment sources breakdown
        headline_sources = sent.get("headline_sources", {})
        if headline_sources and isinstance(headline_sources, dict):
            st.markdown("<div class='small-note'><b>Sentiment Sources</b></div>", unsafe_allow_html=True)
            total_headlines = sum(headline_sources.values())
            if total_headlines > 0:
                source_data = []
                for source_name in ["Moneycontrol", "ET", "Business Standard", "NSE"]:
                    count = headline_sources.get(source_name, 0)
                    pct = round(count / total_headlines * 100, 0) if total_headlines > 0 else 0
                    source_data.append({"Source": source_name, "Count": count, "Pct": f"{int(pct)}%"})
                source_df = pd.DataFrame(source_data)
                st.dataframe(source_df, use_container_width=True, hide_index=True)
        
        # Top headlines
        top_headlines = sent.get("top_headlines", [])
        if top_headlines:
            st.markdown("<div class='small-note'><b>Top Headlines</b></div>", unsafe_allow_html=True)
            for item in top_headlines:
                score = _safe_float(item.get("score", 0.0), 0.0)
                tag_class = "tag-good" if score > 0 else ("tag-bad" if score < 0 else "tag-neutral")
                source = str(item.get("source", "")).strip()
                st.markdown(
                    f"""
                    <div class="headline-box">
                        {f'<div class="small-note">{source}</div>' if source else ''}{item.get('headline', '')}
                        <span class="tag {tag_class}" style="float:right; margin-right:0;">{score:+.2f}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        st.markdown("</div>", unsafe_allow_html=True)

# PnL charts
st.subheader("P&L Curve")
if pnl_df.empty:
    st.info("No completed trades yet. P&L curve will appear once exits are logged.")
else:
    chart_df = pnl_df.set_index("date")
    st.line_chart(chart_df[["net_pnl", "cum_pnl"]], height=240)
    st.dataframe(
        pnl_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "net_pnl": st.column_config.NumberColumn("Net P&L", format="%.2f"),
            "cum_pnl": st.column_config.NumberColumn("Cumulative P&L", format="%.2f"),
        },
    )

# Trades
st.subheader("Recent Trades")
if not trades:
    st.info("No trades found in logs/paper_trades.json yet.")
else:
    tdf = pd.DataFrame(trades)

    f1, f2, f3 = st.columns(3)
    index_options = ["All"] + sorted([x for x in tdf.get("index", pd.Series(dtype=str)).dropna().astype(str).unique()])
    strategy_options = ["All"] + sorted([x for x in tdf.get("strategy", pd.Series(dtype=str)).dropna().astype(str).unique()])
    option_options = ["All"] + sorted([x for x in tdf.get("option_type", pd.Series(dtype=str)).dropna().astype(str).unique()])

    with f1:
        selected_index = st.selectbox("Filter by Index", options=index_options, index=0)
    with f2:
        selected_strategy = st.selectbox("Filter by Strategy", options=strategy_options, index=0)
    with f3:
        selected_option = st.selectbox("Filter by Option Type", options=option_options, index=0)

    filtered = tdf.copy()
    if selected_index != "All" and "index" in filtered.columns:
        filtered = filtered[filtered["index"].astype(str) == selected_index]
    if selected_strategy != "All" and "strategy" in filtered.columns:
        filtered = filtered[filtered["strategy"].astype(str) == selected_strategy]
    if selected_option != "All" and "option_type" in filtered.columns:
        filtered = filtered[filtered["option_type"].astype(str) == selected_option]

    st.caption(f"Showing {len(filtered)} of {len(tdf)} trades")

    preferred_cols = [
        "date",
        "symbol",
        "index",
        "strategy",
        "option_type",
        "strike",
        "lots",
        "entry_price",
        "exit_price",
        "net_pnl",
        "exit_reason",
    ]
    cols = [c for c in preferred_cols if c in filtered.columns]
    if cols:
        st.dataframe(filtered[cols], use_container_width=True, hide_index=True)
    else:
        st.dataframe(filtered, use_container_width=True, hide_index=True)

st.caption("This Streamlit app is a monitoring dashboard. Run the bot loop separately for continuous trading scans.")

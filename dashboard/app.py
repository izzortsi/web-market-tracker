import os
import math
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
import plotly.graph_objects as go
from dash import Dash, dcc, html, Input, Output, State

API_BASE = os.environ.get("API_BASE", "http://localhost:8000")
GLOBAL_URL = f"{API_BASE}/api/global/metrics"
CANDIDATES_URL = f"{API_BASE}/api/screener/candidates"
PROMOTED_URL = f"{API_BASE}/api/screener/promoted"
PAPER_SUMMARY_URL = f"{API_BASE}/api/paper/summary"
PAPER_POSITIONS_URL = f"{API_BASE}/api/paper/positions"
PAPER_TRADES_URL = f"{API_BASE}/api/paper/trades"

app = Dash(__name__)
app.title = "Market Tracker"


def _empty_figure(title: str, color: str) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        title=title,
        margin=dict(l=40, r=10, t=30, b=30),
        height=220,
        paper_bgcolor="#111c2b",
        plot_bgcolor="#111c2b",
        font=dict(color="#e6edf3"),
        uirevision="market-tracker",
    )
    return fig


def _line_figure(title: str, series: List[Dict[str, Any]], color: str) -> go.Figure:
    fig = go.Figure()
    x_vals = [datetime.fromtimestamp(p["t"] / 1000) for p in series]
    y_raw = [p["v"] for p in series]
    y_plot = [math.copysign(math.log10(1 + abs(v)), v) for v in y_raw]
    fig.add_trace(
        go.Scatter(
            x=x_vals,
            y=y_plot,
            mode="lines",
            line=dict(color=color),
            customdata=y_raw,
            hovertemplate="%{x}<br>raw=%{customdata:.4f}<extra></extra>",
        )
    )
    fig.update_layout(
        title=title,
        margin=dict(l=40, r=10, t=30, b=30),
        height=220,
        paper_bgcolor="#111c2b",
        plot_bgcolor="#111c2b",
        font=dict(color="#e6edf3"),
        yaxis=dict(title="symlog (log10(1+|v|))"),
    )
    return fig


def _candlestick_figure(ohlc: List[Dict[str, Any]]) -> go.Figure:
    fig = go.Figure(
        data=[
            go.Candlestick(
                x=[datetime.fromtimestamp(o["t"] / 1000) for o in ohlc],
                open=[o["o"] for o in ohlc],
                high=[o["h"] for o in ohlc],
                low=[o["l"] for o in ohlc],
                close=[o["c"] for o in ohlc],
                increasing_line_color="#00c896",
                decreasing_line_color="#ff6b6b",
            )
        ]
    )
    fig.update_layout(
        margin=dict(l=30, r=10, t=10, b=20),
        height=200,
        paper_bgcolor="#111c2b",
        plot_bgcolor="#111c2b",
        font=dict(color="#e6edf3"),
        uirevision="market-tracker",
        xaxis=dict(
            showgrid=False,
            showticklabels=True,
            tickformat="%H:%M",
            nticks=5,
            rangeslider=dict(visible=False),
            zeroline=False,
        ),
        yaxis=dict(showgrid=True, zeroline=False),
    )
    return fig


def _safe_get(url: str, timeout: int = 2) -> Optional[Dict[str, Any]]:
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


def _series_from_global(samples: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for s in samples:
        t = s.get("tick_sec")
        v = s.get(key)
        if t is None or v is None:
            continue
        out.append({"t": t * 1000, "v": v})
    return out


def _sparkline(klines: List[Dict[str, Any]], height: int = 70) -> go.Figure:
    if not klines:
        fig = go.Figure()
        fig.update_layout(
            margin=dict(l=0, r=0, t=0, b=0),
            height=height,
            paper_bgcolor="#111c2b",
            plot_bgcolor="#111c2b",
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
        )
        return fig

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=[datetime.fromtimestamp(o["t"] / 1000) for o in klines],
            y=[o["c"] for o in klines],
            mode="lines",
            line=dict(color="#e6edf3", width=1),
        )
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        height=height,
        paper_bgcolor="#111c2b",
        plot_bgcolor="#111c2b",
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
    )
    return fig


def _keltner_sparkline(klines: List[Dict[str, Any]], keltner: Optional[Dict[str, Any]], height: int = 80) -> go.Figure:
    fig = _sparkline(klines, height=height)
    if not keltner:
        return fig
    multiples = keltner.get("multiples") or {}
    if not klines or not multiples:
        return fig
    x_vals = [datetime.fromtimestamp(o["t"] / 1000) for o in klines]
    for _, band in multiples.items():
        fig.add_trace(
            go.Scatter(
                x=x_vals,
                y=[band["upper"]] * len(klines),
                mode="lines",
                line=dict(color="#ff6b6b", width=1, dash="dot"),
                showlegend=False,
            )
        )
        fig.add_trace(
            go.Scatter(
                x=x_vals,
                y=[band["lower"]] * len(klines),
                mode="lines",
                line=dict(color="#00c896", width=1, dash="dot"),
                showlegend=False,
            )
        )
    return fig


def _build_candidate_slots(
    prev_slots: Optional[List[Optional[Dict[str, Any]]]],
    candidates: List[Dict[str, Any]],
) -> List[Optional[Dict[str, Any]]]:
    slots: List[Optional[Dict[str, Any]]] = list(prev_slots or [])
    slots = (slots + [None] * 10)[:10]

    prev_symbols = {slot.get("symbol") for slot in slots if slot and slot.get("symbol")}
    candidates_by_symbol = {c.get("symbol"): c for c in candidates if c.get("symbol")}

    next_slots: List[Optional[Dict[str, Any]]] = []
    for slot in slots:
        sym = slot.get("symbol") if slot else None
        if sym and sym in candidates_by_symbol:
            next_slots.append(candidates_by_symbol[sym])
        else:
            next_slots.append(None)

    new_candidates = [
        c
        for c in sorted(candidates, key=lambda c: c.get("score", 0), reverse=True)
        if c.get("symbol") and c.get("symbol") not in prev_symbols
    ]

    new_iter = iter(new_candidates)
    for i, slot in enumerate(next_slots):
        if slot is None:
            try:
                next_slots[i] = next(new_iter)
            except StopIteration:
                break

    return next_slots


def _candidate_rows(slots: List[Optional[Dict[str, Any]]]) -> List[html.Tr]:
    rows: List[html.Tr] = []
    row_style = {"height": "28px"}
    empty_cell = html.Td("\u00a0")

    for c in slots[:10]:
        if not c:
            rows.append(html.Tr([empty_cell] * 8, style=row_style))
            continue
        last_price = c.get("last_price")
        price_change_pct = c.get("price_change_pct")
        rows.append(
            html.Tr(
                [
                    html.Td(c.get("symbol") or ""),
                    html.Td(f'{c.get("score", 0):.4f}'),
                    html.Td(f'{c.get("range_pos", 0):.4f}'),
                    html.Td(f'{c.get("sigma_1m", 0):.6f}'),
                    html.Td(f'{c.get("quote_volume_24h", 0):.2f}'),
                    html.Td(f'{c.get("fee_threshold", 0):.6f}'),
                    html.Td(f'{last_price:.6f}' if last_price is not None else ""),
                    html.Td(f'{price_change_pct:.2f}%' if price_change_pct is not None else ""),
                ],
                style=row_style,
            )
        )

    while len(rows) < 10:
        rows.append(html.Tr([empty_cell] * 8, style=row_style))

    header = html.Tr(
        [
            html.Th("Symbol"),
            html.Th("Score"),
            html.Th("Range Pos"),
            html.Th("σ(1m)"),
            html.Th("QuoteVol 24h"),
            html.Th("Fee Threshold"),
            html.Th("Last"),
            html.Th("24h %"),
        ],
        style=row_style,
    )
    return [header, *rows]


def _keltner_overlay(klines: List[Dict[str, Any]], keltner: Dict[str, Any]) -> go.Figure:
    fig = _candlestick_figure(klines)
    multiples = keltner.get("multiples") or {}
    for k, band in multiples.items():
        fig.add_trace(
            go.Scatter(
                x=[datetime.fromtimestamp(o["t"] / 1000) for o in klines],
                y=[band["upper"]] * len(klines),
                mode="lines",
                line=dict(color="#ff6b6b", width=1, dash="dot"),
                name=f"{k} upper",
                showlegend=False,
            )
        )
        fig.add_trace(
            go.Scatter(
                x=[datetime.fromtimestamp(o["t"] / 1000) for o in klines],
                y=[band["lower"]] * len(klines),
                mode="lines",
                line=dict(color="#00c896", width=1, dash="dot"),
                name=f"{k} lower",
                showlegend=False,
            )
        )
    return fig


def _promoted_card(symbol: str, state: Optional[Dict[str, Any]]) -> html.Div:
    if state is None:
        return html.Div(className="card", children=[html.Div(f"{symbol}: warming up…")])

    klines = state.get("klines", [])
    keltner = state.get("keltner") or {}
    basis = keltner.get("basis")
    atr = keltner.get("atr")

    fig = _keltner_overlay(klines, keltner)

    return html.Div(
        className="card",
        children=[
            html.Div(
                className="card-header",
                children=[
                    html.Div(symbol, className="sym"),
                    html.Div(state.get("interval", ""), className="meta"),
                ],
            ),
            html.Div(
                className="stats",
                children=[
                    html.Span(f"Basis: {basis:.4f}" if basis is not None else "Basis: -"),
                    html.Span(f"ATR: {atr:.4f}" if atr is not None else "ATR: -"),
                ],
            ),
            dcc.Graph(
                figure=fig,
                config={"displayModeBar": True, "displaylogo": False, "modeBarButtonsToAdd": ["resetScale2d"]},
            ),
        ],
    )


def _paper_summary_view(summary: Optional[Dict[str, Any]]) -> html.Div:
    if summary is None:
        return html.Div("Paper trading disabled or no data", className="card")
    return html.Div(
        className="card",
        children=[
            html.Div("Paper Trading Summary", className="card-header"),
            html.Div(
                className="stats",
                children=[
                    html.Span(f"Equity: {summary.get('equity', 0):.2f}"),
                    html.Span(f"Positions: {summary.get('positions', 0)}"),
                    html.Span(f"Orders: {summary.get('orders', 0)}"),
                    html.Span(f"Trades: {summary.get('trades', 0)}"),
                ],
            ),
        ],
    )


def _positions_table(positions: List[Dict[str, Any]]) -> html.Table:
    rows = []
    for p in positions[:3]:
        sym = p.get("symbol")
        state = _safe_get(f"{API_BASE}/api/symbols/{sym}") if sym else None
        spark = _keltner_sparkline(state.get("klines", []) if state else [], state.get("keltner", {}) if state else {})
        rows.append(
            html.Tr(
                [
                    html.Td(sym or ""),
                    html.Td(f'{p.get("qty", 0):.6f}'),
                    html.Td(f'{p.get("avg_price", 0):.6f}'),
                    html.Td(f'{p.get("current_pnl", 0):.2f}'),
                    html.Td(f'{p.get("realized_pnl", 0):.2f}'),
                    html.Td(dcc.Graph(figure=spark, config={"displayModeBar": False}), style={"width": "160px"}),
                ]
            )
        )

    while len(rows) < 3:
        rows.append(html.Tr([html.Td("") for _ in range(6)]))

    header = html.Tr(
        [
            html.Th("Symbol"),
            html.Th("Qty"),
            html.Th("Avg Price"),
            html.Th("Current PnL"),
            html.Th("Realized PnL"),
            html.Th("Price (Keltner)"),
        ]
    )
    return html.Table([html.Thead(header), html.Tbody(rows)], className="candidate-table")


def _trades_table(trades: List[Dict[str, Any]]) -> html.Table:
    if not trades:
        return html.Table([html.Tbody([html.Tr([html.Td("No trades")])])], className="candidate-table")
    header = html.Tr(
        [
            html.Th("Time"),
            html.Th("Symbol"),
            html.Th("Side"),
            html.Th("Qty"),
            html.Th("Price"),
            html.Th("Realized PnL"),
        ]
    )
    rows = []
    for t in trades:
        ts = t.get("ts_ms", 0)
        rows.append(
            html.Tr(
                [
                    html.Td(datetime.fromtimestamp(ts / 1000).strftime("%H:%M:%S")),
                    html.Td(t.get("symbol")),
                    html.Td(t.get("side")),
                    html.Td(f'{t.get("qty", 0):.6f}'),
                    html.Td(f'{t.get("price", 0):.6f}'),
                    html.Td(f'{t.get("realized_pnl", 0):.2f}'),
                ]
            )
        )
    return html.Table([html.Thead(header), html.Tbody(rows)], className="candidate-table")


app.layout = html.Div(
    className="page",
    children=[
        html.H1("Market Tracker"),
        dcc.Interval(id="refresh", interval=1000, n_intervals=0),
        dcc.Store(id="candidate-cache", data=[]),
        html.Div(
            className="metrics",
            children=[
                dcc.Graph(
                    id="pbar",
                    figure=_empty_figure("Aggregate Momentum (P̄)", "#00c896"),
                    config={"displayModeBar": True, "displaylogo": False, "modeBarButtonsToAdd": ["resetScale2d"]},
                ),
                dcc.Graph(
                    id="fbar",
                    figure=_empty_figure("Aggregate Force (F̄)", "#ff6b6b"),
                    config={"displayModeBar": True, "displaylogo": False, "modeBarButtonsToAdd": ["resetScale2d"]},
                ),
            ],
            style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "8px"},
        ),
        html.Div(
            className="section",
            children=[
                html.H3("Candidates"),
                html.Div(id="candidate-table", style={"height": "320px"}),
            ],
        ),
        html.Div(
            className="section",
            children=[
                html.H3("Promoted Symbols"),
                html.Div(id="promoted-cards", className="cards"),
            ],
        ),
        html.Div(
            className="section",
            children=[
                html.H3("Paper Trading"),
                html.Div(id="paper-summary"),
                html.Div(
                    className="paper-tables",
                    children=[
                        html.Div([html.H4("Positions"), html.Div(id="paper-positions")], style={"width": "62%"}),
                        html.Div([html.H4("Recent Trades"), html.Div(id="paper-trades")], style={"width": "38%"}),
                    ],
                    style={"display": "flex", "gap": "12px"},
                ),
            ],
        ),
    ],
)


@app.callback(
    Output("pbar", "figure"),
    Output("fbar", "figure"),
    Output("candidate-table", "children"),
    Output("promoted-cards", "children"),
    Output("paper-summary", "children"),
    Output("paper-positions", "children"),
    Output("paper-trades", "children"),
    Output("candidate-cache", "data"),
    Input("refresh", "n_intervals"),
    State("candidate-cache", "data"),
)
def update_dashboard(_: int, candidate_cache: Optional[List[Optional[Dict[str, Any]]]]):
    global_data = _safe_get(GLOBAL_URL)
    candidates_data = _safe_get(CANDIDATES_URL)
    promoted_data = _safe_get(PROMOTED_URL)
    paper_summary = _safe_get(PAPER_SUMMARY_URL)
    paper_positions = _safe_get(PAPER_POSITIONS_URL)
    paper_trades = _safe_get(PAPER_TRADES_URL)

    if global_data is None:
        empty = html.Div("API unreachable", className="card")
        slots = _build_candidate_slots(candidate_cache, [])
        candidate_rows = _candidate_rows(slots)
        candidate_table = html.Table(
            [html.Thead(candidate_rows[0]), html.Tbody(candidate_rows[1:])],
            className="candidate-table",
            style={"tableLayout": "fixed", "width": "100%", "height": "100%"},
        )
        return (
            _empty_figure("Aggregate Momentum (P̄)", "#00c896"),
            _empty_figure("Aggregate Force (F̄)", "#ff6b6b"),
            candidate_table,
            [empty],
            empty,
            empty,
            empty,
            slots,
        )

    series = global_data.get("series", [])
    pbar_series = _series_from_global(series, "Pbar")
    fbar_series = _series_from_global(series, "Fbar")

    pbar_fig = _line_figure("Aggregate Momentum (P̄)", pbar_series, "#00c896")
    fbar_fig = _line_figure("Aggregate Force (F̄)", fbar_series, "#ff6b6b")

    candidates = (candidates_data or {}).get("candidates", [])
    slots = _build_candidate_slots(candidate_cache, candidates)
    candidate_rows = _candidate_rows(slots)
    candidate_table = html.Table(
        [html.Thead(candidate_rows[0]), html.Tbody(candidate_rows[1:])],
        className="candidate-table",
        style={"tableLayout": "fixed", "width": "100%", "height": "100%"},
    )

    promoted = (promoted_data or {}).get("promoted", [])
    cards = []
    for sym in promoted:
        state = _safe_get(f"{API_BASE}/api/symbols/{sym}")
        cards.append(_promoted_card(sym, state))
    if not cards:
        cards = [html.Div("No promoted symbols", className="card")]

    paper_summary_view = _paper_summary_view(paper_summary)
    positions_view = _positions_table((paper_positions or {}).get("positions", []) if paper_positions else [])
    trades_view = _trades_table((paper_trades or {}).get("trades", []) if paper_trades else [])

    return pbar_fig, fbar_fig, candidate_table, cards, paper_summary_view, positions_view, trades_view, slots


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)

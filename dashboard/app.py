import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
import plotly.graph_objects as go
from dash import Dash, dcc, html, Input, Output

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
    fig.add_trace(
        go.Scatter(
            x=[datetime.fromtimestamp(p["t"] / 1000) for p in series],
            y=[p["v"] for p in series],
            mode="lines",
            line=dict(color=color),
        )
    )
    fig.update_layout(
        title=title,
        margin=dict(l=40, r=10, t=30, b=30),
        height=220,
        paper_bgcolor="#111c2b",
        plot_bgcolor="#111c2b",
        font=dict(color="#e6edf3"),
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


def _candidate_table(candidates: List[Dict[str, Any]]) -> html.Table:
    header = html.Tr(
        [
            html.Th("Symbol"),
            html.Th("Score"),
            html.Th("Range Pos"),
            html.Th("σ(1m)"),
            html.Th("QuoteVol 24h"),
            html.Th("Fee Threshold"),
        ]
    )
    rows = []
    for c in candidates:
        rows.append(
            html.Tr(
                [
                    html.Td(c.get("symbol")),
                    html.Td(f'{c.get("score", 0):.4f}'),
                    html.Td(f'{c.get("range_pos", 0):.4f}'),
                    html.Td(f'{c.get("sigma_1m", 0):.6f}'),
                    html.Td(f'{c.get("quote_volume_24h", 0):.2f}'),
                    html.Td(f'{c.get("fee_threshold", 0):.6f}'),
                ]
            )
        )
    return html.Table([html.Thead(header), html.Tbody(rows)], className="candidate-table")


def _promoted_card(symbol: str, state: Optional[Dict[str, Any]]) -> html.Div:
    if state is None:
        return html.Div(className="card", children=[html.Div(f"{symbol}: warming up…")])

    klines = state.get("klines", [])
    keltner = state.get("keltner") or {}
    basis = keltner.get("basis")
    atr = keltner.get("atr")
    multiples = keltner.get("multiples") or {}

    band_text = ", ".join([f"{k}: [{v['lower']:.2f},{v['upper']:.2f}]" for k, v in multiples.items()])

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
                    html.Span(f"Bands: {band_text}" if band_text else "Bands: -"),
                ],
            ),
            dcc.Graph(
                figure=_candlestick_figure(klines),
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
    if not positions:
        return html.Table([html.Tbody([html.Tr([html.Td("No positions")])])], className="candidate-table")
    header = html.Tr(
        [
            html.Th("Symbol"),
            html.Th("Qty"),
            html.Th("Avg Price"),
            html.Th("Realized PnL"),
        ]
    )
    rows = []
    for p in positions:
        rows.append(
            html.Tr(
                [
                    html.Td(p.get("symbol")),
                    html.Td(f'{p.get("qty", 0):.6f}'),
                    html.Td(f'{p.get("avg_price", 0):.6f}'),
                    html.Td(f'{p.get("realized_pnl", 0):.2f}'),
                ]
            )
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
                ]
            )
        )
    return html.Table([html.Thead(header), html.Tbody(rows)], className="candidate-table")


app.layout = html.Div(
    className="page",
    children=[
        html.H1("Market Tracker"),
        dcc.Interval(id="refresh", interval=1000, n_intervals=0),
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
        ),
        html.Div(
            className="section",
            children=[
                html.H3("Candidates"),
                html.Div(id="candidate-table"),
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
                        html.Div([html.H4("Positions"), html.Div(id="paper-positions")]),
                        html.Div([html.H4("Recent Trades"), html.Div(id="paper-trades")]),
                    ],
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
    Input("refresh", "n_intervals"),
)
def update_dashboard(_: int):
    global_data = _safe_get(GLOBAL_URL)
    candidates_data = _safe_get(CANDIDATES_URL)
    promoted_data = _safe_get(PROMOTED_URL)
    paper_summary = _safe_get(PAPER_SUMMARY_URL)
    paper_positions = _safe_get(PAPER_POSITIONS_URL)
    paper_trades = _safe_get(PAPER_TRADES_URL)

    if global_data is None:
        empty = html.Div("API unreachable", className="card")
        return (
            _empty_figure("Aggregate Momentum (P̄)", "#00c896"),
            _empty_figure("Aggregate Force (F̄)", "#ff6b6b"),
            empty,
            [empty],
            empty,
            empty,
            empty,
        )

    series = global_data.get("series", [])
    pbar_series = _series_from_global(series, "Pbar")
    fbar_series = _series_from_global(series, "Fbar")

    pbar_fig = _line_figure("Aggregate Momentum (P̄)", pbar_series, "#00c896")
    fbar_fig = _line_figure("Aggregate Force (F̄)", fbar_series, "#ff6b6b")

    candidates = (candidates_data or {}).get("candidates", [])
    candidate_table = _candidate_table(candidates[:20]) if candidates else html.Div("No candidates")

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

    return pbar_fig, fbar_fig, candidate_table, cards, paper_summary_view, positions_view, trades_view


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)

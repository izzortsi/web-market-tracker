import os
from datetime import datetime
from typing import Any, Dict, List

import requests
import plotly.graph_objects as go
from dash import Dash, dcc, html, Input, Output

API_URL = os.environ.get("API_URL", "http://localhost:8000/api/market/summary")

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
        xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        yaxis=dict(showgrid=True, zeroline=False),
    )
    return fig


app.layout = html.Div(
    className="page",
    children=[
        html.H1("Market Tracker"),
        dcc.Interval(id="refresh", interval=1000, n_intervals=0),
        html.Div(
            className="metrics",
            children=[
                dcc.Graph(id="momentum", figure=_empty_figure("Aggregate Momentum", "#00c896")),
                dcc.Graph(id="accel", figure=_empty_figure("Aggregate Acceleration", "#ff6b6b")),
            ],
        ),
        html.Div(id="cards", className="cards"),
    ],
)


@app.callback(
    Output("momentum", "figure"),
    Output("accel", "figure"),
    Output("cards", "children"),
    Input("refresh", "n_intervals"),
)
def update_dashboard(_: int):
    try:
        resp = requests.get(API_URL, timeout=2)
        if resp.status_code != 200:
            return (
                _empty_figure("Aggregate Momentum", "#00c896"),
                _empty_figure("Aggregate Acceleration", "#ff6b6b"),
                [html.Div("Warming up…", className="card")],
            )
        payload = resp.json()
    except Exception:
        return (
            _empty_figure("Aggregate Momentum", "#00c896"),
            _empty_figure("Aggregate Acceleration", "#ff6b6b"),
            [html.Div("API unreachable", className="card")],
        )

    momentum_fig = _line_figure("Aggregate Momentum", payload["market"]["momentum"], "#00c896")
    accel_fig = _line_figure("Aggregate Acceleration", payload["market"]["acceleration"], "#ff6b6b")

    cards = []
    for sym in payload["top"]:
        stats = html.Div(
            className="stats",
            children=[
                html.Span(f'24h: {sym["change24hPct"]:.2f}%', className="pos" if sym["change24hPct"] >= 0 else "neg"),
                html.Span(f'|HL|: {sym["hlDiffAbs"] * 100:.2f}%'),
                html.Span(f'Accel: {(sym.get("accel") or 0):.4f}'),
                html.Span(f'Score: {sym["score"]:.3f}'),
            ],
        )
        cards.append(
            html.Div(
                className="card",
                children=[
                    html.Div(
                        className="card-header",
                        children=[
                            html.Div(
                                children=[
                                    html.Div(sym["sym"], className="sym"),
                                    html.Div(f'Cap rank: {sym["capRank"]}', className="meta"),
                                ]
                            ),
                            html.Div(f'${sym["last"]:.4f}', className="price"),
                        ],
                    ),
                    stats,
                    dcc.Graph(figure=_candlestick_figure(sym["ohlc"]), config={"displayModeBar": False}),
                ],
            )
        )

    return momentum_fig, accel_fig, cards


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)

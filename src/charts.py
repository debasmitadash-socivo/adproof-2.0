"""Plotly figure builders for the Gradio UI.

Kept in a module of their own so the chart code can be unit-tested without
spinning up Gradio, and so ``app.py`` stays focused on UI wiring.

Every builder returns a ``plotly.graph_objects.Figure``.
"""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

__all__ = [
    "daily_envelope_chart",
    "roi_distribution_chart",
    "click_factors_chart",
    "visual_scores_chart",
    "sensitivity_chart",
]

_BAND_COLOR = "rgba(59, 130, 246, 0.18)"
_LINE_COLOR = "#2563eb"
_GOOD = "#10b981"
_BAD = "#ef4444"
_NEUTRAL_GRID = "#e5e7eb"


def _layout(fig: go.Figure, title: str, height: int = 360,
            xtitle: str = "", ytitle: str = "") -> go.Figure:
    fig.update_layout(
        title=title, height=height,
        xaxis_title=xtitle, yaxis_title=ytitle,
        margin=dict(l=60, r=20, t=50, b=50),
        plot_bgcolor="white",
        xaxis=dict(gridcolor=_NEUTRAL_GRID),
        yaxis=dict(gridcolor=_NEUTRAL_GRID),
    )
    return fig


# ===========================================================================
# Daily curve with p10-p90 confidence band
# ===========================================================================

def daily_envelope_chart(mc, metric: str = "clicks") -> go.Figure:
    """Median daily curve of ``metric`` with a shaded p10-p90 band."""
    envelope = mc.daily_envelope(metric)
    if not envelope:
        return _layout(go.Figure(), f"Daily {metric} (no data)")
    days = sorted(envelope.keys())
    p10 = [envelope[d]["p10"] for d in days]
    p50 = [envelope[d]["p50"] for d in days]
    p90 = [envelope[d]["p90"] for d in days]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=days + days[::-1], y=p90 + p10[::-1],
        fill="toself", fillcolor=_BAND_COLOR,
        line=dict(color="rgba(0,0,0,0)"),
        name="p10-p90 band", showlegend=True,
        hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=days, y=p50, mode="lines+markers",
        line=dict(color=_LINE_COLOR, width=2.5),
        marker=dict(size=6), name="median",
    ))
    return _layout(fig, f"Daily {metric} (sample of audience)",
                   xtitle="Day", ytitle=metric.capitalize())


# ===========================================================================
# ROI distribution histogram across Monte Carlo runs
# ===========================================================================

def roi_distribution_chart(mc) -> go.Figure:
    """Histogram of predicted ROI per Monte Carlo run."""
    ctrs = np.asarray(mc.sample_ctrs, dtype=float)
    convs = np.asarray(mc.sample_conversion_rates, dtype=float)
    if mc.budget <= 0 or mc.mean_aov <= 0:
        return _layout(go.Figure(), "Predicted ROI (insufficient data)")
    clicks = ctrs * mc.total_impressions
    purchases = clicks * convs
    revenue = purchases * mc.mean_aov
    roi_pct = (revenue - mc.budget) / mc.budget * 100

    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=roi_pct, nbinsx=max(8, min(20, mc.n_runs // 2)),
        marker=dict(color=_LINE_COLOR, line=dict(color="white", width=1)),
        name="ROI per run",
    ))
    fig.add_vline(x=0, line_dash="dot", line_color=_BAD,
                  annotation_text="break-even", annotation_position="top")
    median = float(np.median(roi_pct))
    fig.add_vline(x=median, line_dash="dash", line_color=_GOOD,
                  annotation_text=f"median {median:+.0f}%",
                  annotation_position="top right")
    return _layout(fig, "Predicted ROI distribution",
                   xtitle="ROI (%)", ytitle="Number of runs")


# ===========================================================================
# Click-logit factor decomposition (horizontal bar)
# ===========================================================================

def click_factors_chart(factors: dict) -> go.Figure:
    """Horizontal bar chart of mean logit contributions, sorted by magnitude.

    'base' is excluded because it is the anchor, not a driver.
    """
    items = [(k, float(v)) for k, v in (factors or {}).items() if k != "base"]
    items.sort(key=lambda kv: abs(kv[1]), reverse=True)
    if not items:
        return _layout(go.Figure(), "Click drivers (no data)")
    labels = [k.replace("_", " ").title() for k, _ in items]
    values = [v for _, v in items]
    colors = [_GOOD if v >= 0 else _BAD for v in values]

    fig = go.Figure(go.Bar(
        x=values, y=labels, orientation="h",
        marker=dict(color=colors),
        text=[f"{v:+.2f}" for v in values],
        textposition="outside",
    ))
    fig.update_layout(yaxis=dict(autorange="reversed"))
    return _layout(fig, "Mean click-logit contributions (per exposed agent)",
                   xtitle="Logit contribution", height=320)


# ===========================================================================
# Visual analysis scores (compact bar)
# ===========================================================================

def visual_scores_chart(visual_result) -> go.Figure:
    if visual_result is None:
        return _layout(go.Figure(), "Visual scores (none)")
    keys = list(visual_result.scores.keys())
    vals = [visual_result.scores[k] for k in keys]
    labels = [k.replace("_", " ").title() for k in keys]
    colors = [_GOOD if v >= 0.65 else _BAD if v <= 0.45 else _LINE_COLOR
              for v in vals]

    fig = go.Figure(go.Bar(
        x=labels, y=vals, marker=dict(color=colors),
        text=[f"{v:.2f}" for v in vals], textposition="outside",
    ))
    fig.update_yaxes(range=[0, 1.05])
    title = (f"Visual analysis ({visual_result.provider} / "
             f"{visual_result.model})")
    return _layout(fig, title, xtitle="", ytitle="Score (0-1)", height=320)


# ===========================================================================
# Sensitivity sweep
# ===========================================================================

def sensitivity_chart(rows: list, x_key: str, y_key: str,
                      x_label: str, y_label: str, title: str) -> go.Figure:
    """Line/bar of a sensitivity sweep across one lever."""
    if not rows:
        return _layout(go.Figure(), f"{title} (no data)")
    xs = [r[x_key] for r in rows]
    ys = [r[y_key] for r in rows]
    is_numeric = all(isinstance(x, (int, float)) for x in xs)

    if is_numeric:
        fig = go.Figure(go.Scatter(
            x=xs, y=ys, mode="lines+markers",
            line=dict(color=_LINE_COLOR, width=2.5),
            marker=dict(size=9),
        ))
    else:
        fig = go.Figure(go.Bar(
            x=[str(x) for x in xs], y=ys,
            marker=dict(color=_LINE_COLOR),
            text=[f"{v:.2f}" if isinstance(v, float) else str(v)
                  for v in ys], textposition="outside",
        ))
    return _layout(fig, title, xtitle=x_label, ytitle=y_label)

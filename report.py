"""Static HTML report -- drives the same wizard pipeline as the live app.

Lets you preview the simulator's output on any Python 3.9+ environment with
numpy / pandas / networkx / pillow / plotly. Bypasses Gradio entirely.

Examples
--------
    python report.py --image data/raw/demo_ad.png

    python report.py --image data/raw/demo_ad.png \\
        --company "Lumen Skincare is a DTC premium brand for women 25-40" \\
        --audience "urban millennials, fashion-aware, shop online weekly" \\
        --platform meta_instagram --format meta_ig_reels \\
        --budget 15000 --days 14 --runs 20 --open
"""
from __future__ import annotations

import argparse
import re
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from audience_match import match_audience  # noqa: E402
from brief import CampaignBrief, CreativeAssets  # noqa: E402
from company_profile import parse_company  # noqa: E402
from llm import have_any_key  # noqa: E402
from pipeline import DISCLAIMER, run_wizard_simulation  # noqa: E402
from platforms import (FORMATS, list_platforms,  # noqa: E402
                        platform_formats, platform_name)


_PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.35.0.min.js"
_DEFAULT_COMPANY = ("Lumen Skincare is a DTC premium skincare brand for "
                    "women 25-40 who want clean ingredients and visible "
                    "results.")
_DEFAULT_AUDIENCE = ("Urban millennial women, fashion-aware, shop online "
                     "weekly, follow beauty creators on Instagram.")

_CSS = """
:root { --fg:#0f172a; --muted:#64748b; --accent:#4f46e5; --bg:#f8fafc;
        --card:#ffffff; --border:#e2e8f0; --warn-bg:#fef3c7;
        --warn-border:#f59e0b; --warn-fg:#78350f; }
* { box-sizing: border-box; }
body { font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI",
       Helvetica, sans-serif; margin: 0; padding: 0 0 48px;
       color: var(--fg); line-height: 1.55; background: var(--bg); }
.shell { max-width: 1180px; margin: 0 auto; padding: 28px 36px; }
.brand { font-weight: 700; font-size: 26px; letter-spacing: -0.01em;
         color: #0f172a; margin: 0; }
.tagline { color: var(--muted); margin: 2px 0 0; font-size: 14px; }
.hero { background: linear-gradient(135deg,#4f46e5,#7c3aed); color: white;
        padding: 26px 30px; border-radius: 14px; margin: 22px 0 18px; }
.hero .label { font-size: 12px; opacity: 0.85; letter-spacing: 0.06em;
                text-transform: uppercase; }
.hero .value { font-size: 42px; font-weight: 700; margin-top: 4px;
                line-height: 1.1; }
.hero .sub { font-size: 14px; margin-top: 8px; opacity: 0.95; }
.metric-row { display: grid; grid-template-columns: repeat(4,1fr); gap: 14px;
              margin: 14px 0; }
.metric { background: var(--card); border: 1px solid var(--border);
          padding: 14px 16px; border-radius: 10px; }
.metric .label { font-size: 11px; color: var(--muted); letter-spacing:0.06em;
                  text-transform: uppercase; }
.metric .value { font-size: 22px; font-weight: 700; margin-top: 4px; }
.metric .sub { font-size: 12px; color: var(--muted); margin-top: 4px; }
.card { background: var(--card); border: 1px solid var(--border);
        border-radius: 10px; padding: 16px 18px; margin: 12px 0; }
.card h3 { margin: 0 0 8px; font-size: 14px; color: var(--muted);
            font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; }
.card .row { display: flex; flex-wrap: wrap; gap: 8px 22px; font-size: 14px; }
.pill { display: inline-block; padding: 3px 9px; border-radius: 999px;
        background: #e0e7ff; color: #3730a3; font-size: 11.5px; font-weight: 500; }
h2 { color: #0f172a; border-bottom: 1px solid var(--border);
     padding-bottom: 6px; margin-top: 36px; font-size: 20px; }
h3 { color: #0f172a; margin-top: 18px; font-size: 16px; }
p  { margin: 10px 0; }
em { color: var(--muted); }
strong { color: #0f172a; }
code { background: #eef2ff; padding: 2px 6px; border-radius: 4px;
       font-size: 0.9em; }
table { border-collapse: collapse; margin: 16px 0; width: 100%;
        background: var(--card); border: 1px solid var(--border);
        border-radius: 10px; overflow: hidden; }
th, td { padding: 10px 14px; border-bottom: 1px solid var(--border);
         text-align: right; font-variant-numeric: tabular-nums; font-size: 14px; }
th:first-child, td:first-child { text-align: left; }
th { background: #f1f5f9; font-weight: 600; font-size: 12.5px;
     color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
tr:last-child td { border-bottom: none; }
ul { padding-left: 22px; }
li { margin-bottom: 6px; }
hr { border: none; border-top: 1px solid var(--border); margin: 24px 0; }
.chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 22px;
              margin: 14px 0; }
.chart-grid > div { background: var(--card); border: 1px solid var(--border);
                    border-radius: 10px; padding: 8px; }
@media (max-width: 880px) { .chart-grid, .metric-row {
       grid-template-columns: 1fr; } }
.disclaimer { background: var(--warn-bg);
              border-left: 4px solid var(--warn-border);
              padding: 14px 18px; margin-top: 36px;
              font-size: 13px; color: var(--warn-fg); border-radius: 4px; }
"""


# ---------------------------------------------------------------------------
# Tiny markdown -> HTML converter
# ---------------------------------------------------------------------------

def _md_inline(text: str) -> str:
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![A-Za-z0-9_])_([^_]+)_(?![A-Za-z0-9_])",
                  r"<em>\1</em>", text)
    return text


def _is_block_start(line: str) -> bool:
    s = line.strip()
    return (s.startswith("#") or s.startswith("- ")
            or s.startswith("|") or s == "---")


def md_to_html(md: str) -> str:
    lines = md.split("\n")
    out: list = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]; stripped = line.strip()
        if ("|" in line and i + 1 < n
                and re.match(r"^\s*\|?\s*[-:|\s]+\|", lines[i + 1])):
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            i += 2; body = []
            while i < n and "|" in lines[i] and lines[i].strip():
                body.append([c.strip()
                             for c in lines[i].strip().strip("|").split("|")])
                i += 1
            tbl = ["<table>", "<thead><tr>"]
            tbl += [f"<th>{_md_inline(c)}</th>" for c in header]
            tbl += ["</tr></thead>", "<tbody>"]
            for row in body:
                tbl.append("<tr>" + "".join(
                    f"<td>{_md_inline(c)}</td>" for c in row) + "</tr>")
            tbl += ["</tbody></table>"]
            out.append("\n".join(tbl)); continue
        if stripped.startswith("### "):
            out.append(f"<h3>{_md_inline(stripped[4:])}</h3>"); i += 1; continue
        if stripped.startswith("## "):
            out.append(f"<h2>{_md_inline(stripped[3:])}</h2>"); i += 1; continue
        if stripped.startswith("# "):
            out.append(f"<h1>{_md_inline(stripped[2:])}</h1>"); i += 1; continue
        if stripped.startswith("- "):
            items = []
            while i < n and lines[i].strip().startswith("- "):
                items.append(_md_inline(lines[i].strip()[2:])); i += 1
            out.append("<ul>" + "".join(f"<li>{it}</li>"
                                         for it in items) + "</ul>")
            continue
        if stripped == "---":
            out.append("<hr>"); i += 1; continue
        if not stripped:
            i += 1; continue
        para = []
        while i < n and lines[i].strip() and not _is_block_start(lines[i]):
            para.append(lines[i].strip()); i += 1
        if para:
            out.append(f"<p>{_md_inline(' '.join(para))}</p>")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# HTML assembly
# ---------------------------------------------------------------------------

def _hero(insights, mc) -> str:
    roas = mc.predicted_roas["p50"]
    roi = mc.predicted_roi["p50"] * 100
    verdict = insights["headline"]
    verdict_cls = insights["verdict_class"]
    color = {
        "strong": "#10b981",
        "positive": "#4f46e5",
        "break_even": "#f59e0b",
        "underperforming": "#ef4444",
    }.get(verdict_cls, "#4f46e5")
    label = verdict_cls.replace("_", " ").title()
    return (f"<div class='hero' style='background:linear-gradient(135deg,"
            f"{color},#1e293b)'>"
            f"<div class='label'>{label} forecast</div>"
            f"<div class='value'>{roas:.2f}× ROAS</div>"
            f"<div class='sub'>Median return: {roi:+.0f}% &middot; "
            f"{verdict}</div></div>")


def _metric_row(mc) -> str:
    ctr = (sum(mc.sample_ctrs) / max(len(mc.sample_ctrs), 1)) * 100
    cells = [
        ("Predicted clicks",
         f"{mc.predicted_clicks['p50']:,.0f}",
         f"p10 {mc.predicted_clicks['p10']:,.0f} — "
         f"p90 {mc.predicted_clicks['p90']:,.0f}"),
        ("Predicted conversions",
         f"{mc.predicted_conversions['p50']:,.0f}",
         f"p10 {mc.predicted_conversions['p10']:,.0f} — "
         f"p90 {mc.predicted_conversions['p90']:,.0f}"),
        ("Sample CTR",
         f"{ctr:.3f}%",
         f"on {mc.audience_size:,} personas"),
        ("Mean buyer AOV",
         f"${mc.mean_aov:,.0f}",
         f"{mc.n_runs} runs"),
    ]
    chunks = "".join(
        f"<div class='metric'><div class='label'>{c[0]}</div>"
        f"<div class='value'>{c[1]}</div>"
        f"<div class='sub'>{c[2]}</div></div>" for c in cells)
    return f"<div class='metric-row'>{chunks}</div>"


def _context_cards(result, run_meta) -> str:
    p = result["profile"]; m = result["match"]
    b = result["brief"]; fmt = b.format
    src_p = "LLM-parsed" if p.source == "llm" else "heuristic"
    src_m = "LLM-matched" if m.source == "llm" else "keyword-matched"
    return f"""
<div class='card'>
  <h3>Company</h3>
  <div class='row'>
    <span><strong>{p.company_name or '(unnamed)'}</strong></span>
    <span><strong>Industry:</strong> {p.industry or '—'}</span>
    <span><strong>Model:</strong> {p.business_model.upper()}</span>
    <span><strong>Category:</strong> {p.product_category}</span>
    <span><strong>Price:</strong> {p.price_position}</span>
    <span class='pill'>{src_p}</span>
  </div>
</div>
<div class='card'>
  <h3>Audience match</h3>
  <div class='row'>
    <span><strong>Segment:</strong> {m.segment}</span>
    <span><strong>Confidence:</strong> {m.confidence:.0%}</span>
    <span class='pill'>{src_m}</span>
  </div>
  <p style='margin:8px 0 0;color:#475569'>{m.rationale}</p>
</div>
<div class='card'>
  <h3>Campaign brief</h3>
  <div class='row'>
    <span><strong>Platform:</strong> {fmt.platform_name}</span>
    <span><strong>Format:</strong> {fmt.name}</span>
    <span><strong>Objective:</strong> {b.objective}</span>
    <span><strong>Budget:</strong> ${b.budget:,.0f}</span>
    <span><strong>Days:</strong> {b.days}</span>
    <span><strong>Benchmark CTR:</strong> {fmt.benchmarks['ctr']*100:.2f}%</span>
    <span><strong>CPM:</strong> ${b.effective_cpm:.0f}</span>
  </div>
  <p style='margin:8px 0 0;color:#475569'><strong>Best for:</strong> {fmt.best_for}</p>
</div>
"""


def build_html(result: dict, run_meta: dict) -> str:
    figs = result["figures"]
    chart_html = {k: f.to_html(include_plotlyjs=False, full_html=False,
                                 div_id=f"chart-{k}")
                  for k, f in figs.items()}
    headline_html = md_to_html(result["headline_md"])
    visual_html = md_to_html(result["visual_md"])
    narrative_html = md_to_html(result["narrative_md"])
    disclaimer_html = md_to_html(DISCLAIMER)
    hero = _hero(result["insights"], result["mc"])
    metrics = _metric_row(result["mc"])
    cards = _context_cards(result, run_meta)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ad Simulator — Campaign Forecast</title>
<script src="{_PLOTLY_CDN}"></script>
<style>{_CSS}</style>
</head>
<body>
<div class='shell'>
<h1 class='brand'>Ad Simulator</h1>
<p class='tagline'>Generated {run_meta['timestamp']} · agent-based forecast over {run_meta['n_runs']} Monte Carlo runs</p>
{hero}
{metrics}
{cards}
{headline_html}
<h2>Charts</h2>
<div class='chart-grid'>
  <div>{chart_html['daily']}</div>
  <div>{chart_html['roi']}</div>
  <div>{chart_html['factors']}</div>
  <div>{chart_html['visual']}</div>
  <div>{chart_html['sens_budget']}</div>
  <div>{chart_html['sens_reach']}</div>
</div>
<h2>Visual analysis</h2>
{visual_html}
<h2>Why this ad performs</h2>
{narrative_html}
<div class='disclaimer'>{disclaimer_html}</div>
</div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Render the simulator's wizard pipeline as a static HTML "
                    "report (drives the same engine as the live app).")
    ap.add_argument("--image", required=True, help="Ad image path.")
    ap.add_argument("--video", default=None, help="Ad video path (optional).")
    ap.add_argument("--company", default=_DEFAULT_COMPANY,
                    help="Company description (free text).")
    ap.add_argument("--audience", default=_DEFAULT_AUDIENCE,
                    help="Target audience description (free text).")
    ap.add_argument("--platform", default="meta_instagram",
                    choices=list_platforms(),
                    help="Advertising platform.")
    ap.add_argument("--format", default="meta_ig_reels",
                    choices=sorted(FORMATS.keys()),
                    help="Ad format within the platform.")
    ap.add_argument("--objective", default="consideration",
                    choices=("awareness", "consideration", "conversion"))
    ap.add_argument("--headline", default="Glow without the guesswork")
    ap.add_argument("--primary-text",
                    default="Clean ingredients, visible results in 4 weeks. "
                            "Loved by 12k+ women.")
    ap.add_argument("--description", default="")
    ap.add_argument("--cta", default="Shop now")
    ap.add_argument("--link", default="https://example.com")
    ap.add_argument("--budget", type=float, default=15_000.0)
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--reach", type=float, default=0.35)
    ap.add_argument("--provider", default="auto",
                    choices=("auto", "heuristic", "claude", "openai"))
    ap.add_argument("--target-conv", type=float, default=0.025)
    ap.add_argument("--out", default="report.html")
    ap.add_argument("--open", action="store_true",
                    help="Open the report in your default browser.")
    return ap


def main() -> None:
    args = _build_arg_parser().parse_args()

    def _progress(p, desc):
        print(f"[{p*100:5.0f}%] {desc}", flush=True)

    print(f"LLM understanding: {'on' if have_any_key() else 'OFF (heuristic)'}")

    profile = parse_company(args.company, prefer_llm=have_any_key())
    print(f"Profile: {profile.short_summary()}  [source: {profile.source}]")

    match = match_audience(args.audience, prefer_llm=have_any_key())
    print(f"Audience: {match.segment} "
          f"(conf {match.confidence:.2f}) — {match.rationale}")

    # Validate platform/format combination.
    fmt_options = {f.id for f in platform_formats(args.platform)}
    if args.format not in fmt_options:
        print(f"WARN: format '{args.format}' isn't available on platform "
              f"'{args.platform}'; defaulting to the first format of that "
              f"platform.")
        args.format = next(iter(fmt_options))

    brief = CampaignBrief(
        objective=args.objective, platform_id=args.platform,
        format_id=args.format, budget=args.budget, days=args.days,
        daily_reach=args.reach, n_runs=args.runs,
        target_conversion_rate=args.target_conv,
    )
    assets = CreativeAssets(
        image_path=args.image, video_path=args.video,
        headline=args.headline, primary_text=args.primary_text,
        description=args.description, cta=args.cta, link=args.link,
    )

    result = run_wizard_simulation(
        profile=profile, match=match, brief=brief, assets=assets,
        visual_provider=args.provider, progress_callback=_progress,
    )

    run_meta = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "n_runs": args.runs,
    }
    html = build_html(result, run_meta)
    out_path = Path(args.out).resolve()
    out_path.write_text(html, encoding="utf-8")
    print(f"\nReport written to: {out_path}")
    print(f"Open in browser:   file://{out_path}")
    if args.open:
        try:
            webbrowser.open(f"file://{out_path}")
        except Exception:
            pass


if __name__ == "__main__":
    main()

"""Ad Simulator -- multi-step wizard Gradio app.

Five-step flow:
    1. Company       -- free-text description -> structured CompanyProfile
    2. Audience      -- free-text description -> matched persona segment
    3. Campaign      -- objective, platform, ad format, budget, days, reach
    4. Creative      -- upload image/video + copy slots required by the format
    5. Forecast      -- ROAS / ROI / CTR with bands, charts, narrative

Backed by ``src/pipeline.run_wizard_simulation``. LLM-powered understanding
via Claude / GPT-4o when an API key is present, heuristic fallback otherwise.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import gradio as gr

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from src.audience_match import match_audience  # noqa: E402
from src.brief import CampaignBrief, CreativeAssets, validate_creative  # noqa: E402
from src.company_profile import parse_company  # noqa: E402
from src.llm import have_any_key  # noqa: E402
from src.pipeline import DISCLAIMER, get_resources, run_wizard_simulation  # noqa: E402
from src.platforms import (  # noqa: E402
    PLATFORMS, get_format, list_platforms, platform_formats, platform_name,
)


# ===========================================================================
# Theme + custom CSS for a real-app feel
# ===========================================================================

_THEME = gr.themes.Soft(
    primary_hue=gr.themes.colors.indigo,
    secondary_hue=gr.themes.colors.slate,
    neutral_hue=gr.themes.colors.slate,
    font=("Inter", "system-ui", "-apple-system", "sans-serif"),
).set(
    body_background_fill="#f8fafc",
    block_background_fill="#ffffff",
    block_border_width="1px",
    block_radius="12px",
    block_shadow="0 1px 3px rgba(0,0,0,0.04)",
    block_label_text_weight="600",
    button_primary_background_fill="#4f46e5",
    button_primary_background_fill_hover="#4338ca",
    button_primary_text_color="white",
)

_CSS = """
.app-shell { max-width: 1200px; margin: 0 auto; }
.app-title { font-weight: 700; font-size: 28px; letter-spacing: -0.01em; }
.app-tagline { color: #64748b; margin-top: -4px; font-size: 14px; }
.stepper { display: flex; gap: 8px; margin: 14px 0 20px;
            font-size: 13px; color: #64748b; }
.stepper .step { padding: 6px 12px; border-radius: 999px;
                  background: #e2e8f0; }
.stepper .step.active { background: #4f46e5; color: white; font-weight: 600; }
.profile-card { background: #f1f5f9; border: 1px solid #e2e8f0;
                 padding: 14px 16px; border-radius: 10px; margin: 12px 0; }
.benchmark-card { background: #eef2ff; border: 1px solid #c7d2fe;
                  padding: 14px 16px; border-radius: 10px; margin: 8px 0;
                  font-size: 13.5px; }
.hero { background: linear-gradient(135deg,#4f46e5,#7c3aed); color: white;
        padding: 22px 26px; border-radius: 14px; margin: 6px 0 16px; }
.hero .label { font-size: 13px; opacity: 0.85; letter-spacing: 0.04em;
                text-transform: uppercase; }
.hero .value { font-size: 38px; font-weight: 700; margin-top: 4px; }
.hero .sub { font-size: 14px; margin-top: 4px; opacity: 0.92; }
.metric-row { display: grid; grid-template-columns: repeat(4,1fr); gap: 12px;
              margin-bottom: 12px; }
.metric { background: #ffffff; border: 1px solid #e2e8f0; padding: 12px 14px;
          border-radius: 10px; }
.metric .label { font-size: 12px; color: #64748b; text-transform: uppercase;
                  letter-spacing: 0.04em; }
.metric .value { font-size: 20px; font-weight: 700; margin-top: 4px; }
.metric .sub { font-size: 12px; color: #64748b; margin-top: 2px; }
.warn-pill { display: inline-block; padding: 2px 8px; border-radius: 999px;
              background: #fef3c7; color: #92400e; font-size: 12px;
              margin-right: 6px; }
.err-pill  { display: inline-block; padding: 2px 8px; border-radius: 999px;
              background: #fee2e2; color: #991b1b; font-size: 12px;
              margin-right: 6px; }
.info-pill { display: inline-block; padding: 2px 8px; border-radius: 999px;
              background: #dbeafe; color: #1e40af; font-size: 12px;
              margin-right: 6px; }
footer { display: none; }
"""


# ===========================================================================
# Step-handler helpers
# ===========================================================================

def _stepper(active: int) -> str:
    labels = ["1 · Company", "2 · Audience", "3 · Campaign",
              "4 · Creative", "5 · Forecast"]
    items = []
    for i, label in enumerate(labels, 1):
        cls = "step active" if i == active else "step"
        items.append(f'<span class="{cls}">{label}</span>')
    return f'<div class="stepper">{"".join(items)}</div>'


def _profile_card(profile) -> str:
    if profile is None or not profile.raw_description:
        return ""
    src = ("LLM-parsed" if profile.source == "llm"
           else "heuristic" if profile.source == "heuristic"
           else profile.source)
    bits = [
        f"<strong>{profile.company_name or '(unnamed)'}</strong> "
        f"<span class='info-pill'>{src}</span>",
        f"<strong>Industry:</strong> {profile.industry or '—'}",
        f"<strong>Business model:</strong> {profile.business_model.upper()}",
        f"<strong>Category:</strong> {profile.product_category}",
        f"<strong>Price position:</strong> {profile.price_position}",
    ]
    if profile.value_proposition:
        bits.append(f"<strong>Value prop:</strong> "
                    f"{profile.value_proposition}")
    if profile.target_customer_summary:
        bits.append(f"<strong>Customer:</strong> "
                    f"{profile.target_customer_summary}")
    return f"<div class='profile-card'>{' &middot; '.join(bits)}</div>"


def _match_card(m) -> str:
    if m is None:
        return ""
    src = "LLM-matched" if m.source == "llm" else "keyword-matched"
    secondary = ("; secondary fits: " + ", ".join(m.secondary_segments)
                 if m.secondary_segments else "")
    return ("<div class='profile-card'>"
            f"<strong>Best-fit segment: {m.segment}</strong> "
            f"<span class='info-pill'>{src}</span> "
            f"<span class='info-pill'>confidence {m.confidence:.0%}</span>"
            f"<br/><span style='color:#475569'>{m.rationale}{secondary}</span>"
            "</div>")


def _benchmark_card(format_id: str) -> str:
    try:
        fmt = get_format(format_id)
    except KeyError:
        return ""
    b = fmt.benchmarks
    ctr = b.get("ctr", 0) * 100
    cpm = b.get("cpm", 0)
    cpc = b.get("cpc")
    rng = b.get("ctr_range")
    rng_txt = (f" (range {rng[0]*100:.2f}–{rng[1]*100:.2f}%)"
               if rng else "")
    asset_chips = " ".join(f"<span class='info-pill'>{a}</span>"
                            for a in fmt.asset_types[:6])
    cpc_txt = f" · CPC ${cpc:.2f}" if cpc else ""
    cpm_txt = f"CPM ${cpm:.0f}" if cpm else "CPM n/a (cost-per-click format)"
    return (f"<div class='benchmark-card'>"
            f"<strong>{fmt.platform_name} / {fmt.name}</strong><br/>"
            f"Benchmark CTR {ctr:.2f}%{rng_txt} · {cpm_txt}{cpc_txt}<br/>"
            f"<strong>Best for:</strong> {fmt.best_for}<br/>"
            f"<strong>Tone:</strong> {fmt.tone}<br/>"
            f"<strong>Required assets:</strong> {asset_chips}"
            "</div>")


def _validation_pills(issues: list) -> str:
    if not issues:
        return ("<div style='color:#15803d;font-size:13px'>"
                "All checks passed for the chosen format.</div>")
    chunks = []
    for v in issues:
        cls = ("err-pill" if v["severity"] == "error"
               else "warn-pill" if v["severity"] == "warning"
               else "info-pill")
        chunks.append(f"<div style='margin:4px 0'>"
                      f"<span class='{cls}'>{v['severity']}</span>"
                      f"{v['message']}</div>")
    return "".join(chunks)


# ===========================================================================
# Tab handlers
# ===========================================================================

def handle_company(description: str, state: dict):
    profile = parse_company(description, prefer_llm=have_any_key())
    state = {**(state or {}), "profile": profile}
    return state, _profile_card(profile)


def handle_audience(description: str, state: dict):
    match = match_audience(description, prefer_llm=have_any_key())
    state = {**(state or {}), "audience_text": description, "match": match}
    return state, _match_card(match)


def on_platform_change(platform_id: str):
    fmts = platform_formats(platform_id)
    default = fmts[0].id if fmts else None
    return gr.Dropdown(
        choices=[(f.name, f.id) for f in fmts], value=default,
    ), _benchmark_card(default) if default else ""


def on_format_change(format_id: str):
    return _benchmark_card(format_id)


def handle_creative_validation(format_id, image, video, headline,
                                primary_text, description, cta, link):
    brief_stub = CampaignBrief(format_id=format_id) if format_id else None
    if brief_stub is None:
        return "<i>Select a format first.</i>"
    assets = CreativeAssets(
        image_path=image, video_path=video, headline=headline or "",
        primary_text=primary_text or "", description=description or "",
        cta=cta or "", link=link or "",
    )
    issues = validate_creative(brief_stub, assets)
    return _validation_pills(issues)


def _build_hero_html(insights, mc) -> str:
    roas = mc.predicted_roas["p50"]
    roi = mc.predicted_roi["p50"] * 100
    verdict = insights["headline"]
    verdict_cls = insights["verdict_class"]
    accent = {
        "strong": ("#10b981", "Strong"),
        "positive": ("#4f46e5", "Positive"),
        "break_even": ("#f59e0b", "Break-even"),
        "underperforming": ("#ef4444", "Underperforming"),
    }.get(verdict_cls, ("#4f46e5", "Forecast"))
    color = accent[0]
    return (f"<div class='hero' style='background:linear-gradient(135deg,"
            f"{color},#1e293b)'>"
            f"<div class='label'>{accent[1]} forecast</div>"
            f"<div class='value'>{roas:.2f}x ROAS</div>"
            f"<div class='sub'>Median return: {roi:+.0f}% &middot; "
            f"{verdict}</div></div>")


def _build_metric_row(mc) -> str:
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
    chips = "".join(
        f"<div class='metric'><div class='label'>{c[0]}</div>"
        f"<div class='value'>{c[1]}</div>"
        f"<div class='sub'>{c[2]}</div></div>"
        for c in cells)
    return f"<div class='metric-row'>{chips}</div>"


def handle_run(state, objective, platform_id, format_id, budget, days,
                daily_reach, n_runs, image, video, headline, primary_text,
                description, cta, link, provider, progress=gr.Progress()):
    if not state or "profile" not in state:
        raise gr.Error("Complete Step 1 (Company) first.")
    if "match" not in state:
        raise gr.Error("Complete Step 2 (Audience) first.")
    brief = CampaignBrief(
        objective=objective, platform_id=platform_id, format_id=format_id,
        budget=float(budget), days=int(days),
        daily_reach=float(daily_reach), n_runs=int(n_runs),
    )
    assets = CreativeAssets(
        image_path=image, video_path=video, headline=headline or "",
        primary_text=primary_text or "", description=description or "",
        cta=cta or "", link=link or "",
    )
    try:
        result = run_wizard_simulation(
            profile=state["profile"], match=state["match"],
            brief=brief, assets=assets,
            visual_provider=provider,
            progress_callback=lambda p, d: progress(p, desc=d),
        )
    except ValueError as exc:
        raise gr.Error(str(exc))

    figs = result["figures"]
    mc = result["mc"]
    hero = _build_hero_html(result["insights"], mc)
    metrics = _build_metric_row(mc)
    return (
        gr.Tabs(selected=4),                      # jump to Forecast tab
        hero, metrics,
        result["headline_md"],
        figs["daily"], figs["roi"], figs["factors"], figs["sens_budget"],
        figs["sens_reach"], figs["visual"],
        result["visual_md"], result["narrative_md"], result["json_str"],
    )


def jump_to(tab_id: int):
    return gr.Tabs(selected=tab_id)


# ===========================================================================
# Build UI
# ===========================================================================

def _build_ui() -> gr.Blocks:
    platform_ids = list_platforms()
    platform_choices = [(platform_name(p), p) for p in platform_ids]
    default_platform = "meta_instagram"
    default_format_choices = [(f.name, f.id)
                              for f in platform_formats(default_platform)]
    default_format = default_format_choices[0][1]

    llm_on = have_any_key()
    llm_chip = ("<span class='info-pill'>LLM understanding: on</span>"
                if llm_on else
                "<span class='warn-pill'>heuristic only (no API key)</span>")

    with gr.Blocks(title="Ad Simulator", theme=_THEME, css=_CSS) as demo:
        wizard_state = gr.State({})

        gr.HTML(
            "<div class='app-shell'>"
            "<div class='app-title'>Ad Simulator</div>"
            "<div class='app-tagline'>Score your ad before you ship it. "
            f"5-step flow · agent-based model · {llm_chip}</div></div>"
        )
        stepper_html = gr.HTML(_stepper(1))

        with gr.Tabs(elem_id="wizard_tabs") as tabs:

            # ----------------------- Step 1: Company -----------------------
            with gr.Tab("Company", id=0):
                gr.Markdown(
                    "### Tell us about your company\n"
                    "Write a few sentences: what you sell, your "
                    "business model, your customer, your price position. "
                    "We'll parse it into a structured profile."
                )
                company_text = gr.Textbox(
                    lines=5, label="Company description",
                    placeholder="e.g. Lumen Skincare is a DTC premium "
                                "skincare brand for women 25-40 who want "
                                "clean ingredients and visible results...")
                with gr.Row():
                    parse_btn = gr.Button("Understand my company",
                                          variant="secondary")
                    next1_btn = gr.Button("Continue to audience →",
                                          variant="primary")
                profile_view = gr.HTML()

            # ----------------------- Step 2: Audience ----------------------
            with gr.Tab("Audience", id=1):
                gr.Markdown(
                    "### Describe your target audience\n"
                    "Plain English is fine -- demographics, behaviour, "
                    "interests. We'll match it to the closest synthetic "
                    "segment in our panel."
                )
                audience_text = gr.Textbox(
                    lines=3, label="Target audience description",
                    placeholder="e.g. urban millennials, fashion-aware, "
                                "shop online weekly, follow beauty creators")
                with gr.Row():
                    back_2 = gr.Button("← Back")
                    match_btn = gr.Button("Match audience",
                                          variant="secondary")
                    next2_btn = gr.Button("Continue to campaign →",
                                          variant="primary")
                match_view = gr.HTML()

            # ----------------------- Step 3: Campaign ----------------------
            with gr.Tab("Campaign", id=2):
                gr.Markdown("### Set up your campaign")
                with gr.Row():
                    objective_in = gr.Radio(
                        ["awareness", "consideration", "conversion"],
                        value="consideration", label="Campaign objective")
                with gr.Row():
                    platform_in = gr.Dropdown(
                        choices=platform_choices,
                        value=default_platform, label="Platform")
                    format_in = gr.Dropdown(
                        choices=default_format_choices,
                        value=default_format, label="Ad format")
                benchmark_view = gr.HTML(_benchmark_card(default_format))
                with gr.Row():
                    budget_in = gr.Slider(500, 200_000, value=10_000,
                                          step=500, label="Budget (USD)")
                    days_in = gr.Slider(7, 30, value=14, step=1,
                                        label="Campaign days")
                with gr.Row():
                    reach_in = gr.Slider(0.10, 0.90, value=0.35, step=0.05,
                                         label="Daily reach (fraction "
                                               "of audience)")
                    runs_in = gr.Slider(10, 30, value=20, step=1,
                                        label="Monte Carlo runs")
                with gr.Row():
                    back_3 = gr.Button("← Back")
                    next3_btn = gr.Button("Continue to creative →",
                                          variant="primary")

            # ----------------------- Step 4: Creative ----------------------
            with gr.Tab("Creative", id=3):
                gr.Markdown(
                    "### Upload your ad creative\n"
                    "Provide the asset(s) the chosen format expects. "
                    "Required slots and copy limits are checked below."
                )
                with gr.Row():
                    with gr.Column():
                        image_in = gr.Image(type="filepath",
                                             label="Image (PNG / JPG)",
                                             height=220)
                        video_in = gr.File(label="Video (optional, MP4)",
                                            file_types=["video"])
                    with gr.Column():
                        headline_in = gr.Textbox(
                            label="Headline",
                            placeholder="e.g. Glow without the guesswork")
                        primary_text_in = gr.Textbox(
                            lines=3, label="Primary text / caption",
                            placeholder="e.g. Clean ingredients, visible "
                                        "results in 4 weeks. Loved by 12k+ "
                                        "women.")
                        description_in = gr.Textbox(
                            label="Description (optional)")
                        with gr.Row():
                            cta_in = gr.Textbox(label="CTA",
                                                 placeholder="Shop now")
                            link_in = gr.Textbox(
                                label="Destination URL (optional)",
                                placeholder="https://example.com")
                        provider_in = gr.Dropdown(
                            ["auto", "heuristic", "claude", "openai"],
                            value="auto",
                            label="Visual analysis provider")
                validation_view = gr.HTML()
                with gr.Row():
                    back_4 = gr.Button("← Back")
                    run_btn = gr.Button("Run simulation",
                                        variant="primary", size="lg")

            # ----------------------- Step 5: Forecast ----------------------
            with gr.Tab("Forecast", id=4):
                hero_view = gr.HTML()
                metrics_view = gr.HTML()
                headline_md_out = gr.Markdown()
                with gr.Tabs():
                    with gr.Tab("Daily curve"):
                        daily_plot = gr.Plot()
                    with gr.Tab("ROI distribution"):
                        roi_plot = gr.Plot()
                    with gr.Tab("Click drivers"):
                        factors_plot = gr.Plot()
                    with gr.Tab("Sensitivity: budget"):
                        sens_budget_plot = gr.Plot()
                    with gr.Tab("Sensitivity: reach"):
                        sens_reach_plot = gr.Plot()
                    with gr.Tab("Visual scores"):
                        visual_plot = gr.Plot()
                with gr.Accordion("Visual analysis details", open=True):
                    visual_md_out = gr.Markdown()
                with gr.Accordion("Why this ad performs", open=True):
                    narrative_out = gr.Markdown()
                with gr.Accordion("Raw output (JSON)", open=False):
                    json_out = gr.Code(language="json", lines=18)
                back_5 = gr.Button("← Back to creative")

        gr.HTML("<div class='app-shell' style='margin-top:24px;color:#64748b;"
                "font-size:12.5px;border-top:1px solid #e2e8f0;"
                "padding-top:14px'>" + DISCLAIMER + "</div>")

        # ---------------- wiring ---------------------------------------
        parse_btn.click(handle_company, [company_text, wizard_state],
                        [wizard_state, profile_view])
        next1_btn.click(handle_company, [company_text, wizard_state],
                        [wizard_state, profile_view]).then(
            lambda: (jump_to(1), _stepper(2)), None, [tabs, stepper_html])

        match_btn.click(handle_audience, [audience_text, wizard_state],
                        [wizard_state, match_view])
        next2_btn.click(handle_audience, [audience_text, wizard_state],
                        [wizard_state, match_view]).then(
            lambda: (jump_to(2), _stepper(3)), None, [tabs, stepper_html])
        back_2.click(lambda: (jump_to(0), _stepper(1)),
                      None, [tabs, stepper_html])

        platform_in.change(on_platform_change, [platform_in],
                            [format_in, benchmark_view])
        format_in.change(on_format_change, [format_in], [benchmark_view])
        next3_btn.click(lambda: (jump_to(3), _stepper(4)),
                         None, [tabs, stepper_html])
        back_3.click(lambda: (jump_to(1), _stepper(2)),
                      None, [tabs, stepper_html])

        for inp in (format_in, image_in, video_in, headline_in,
                     primary_text_in, description_in, cta_in, link_in):
            inp.change(handle_creative_validation,
                        [format_in, image_in, video_in, headline_in,
                         primary_text_in, description_in, cta_in, link_in],
                        [validation_view])
        back_4.click(lambda: (jump_to(2), _stepper(3)),
                      None, [tabs, stepper_html])
        back_5.click(lambda: (jump_to(3), _stepper(4)),
                      None, [tabs, stepper_html])

        run_btn.click(
            handle_run,
            inputs=[wizard_state, objective_in, platform_in, format_in,
                    budget_in, days_in, reach_in, runs_in,
                    image_in, video_in, headline_in, primary_text_in,
                    description_in, cta_in, link_in, provider_in],
            outputs=[tabs, hero_view, metrics_view, headline_md_out,
                     daily_plot, roi_plot, factors_plot, sens_budget_plot,
                     sens_reach_plot, visual_plot, visual_md_out,
                     narrative_out, json_out],
        ).then(lambda: _stepper(5), None, [stepper_html])

    return demo


def main() -> None:
    get_resources()                                  # warm personas + calib
    demo = _build_ui()
    demo.launch()


if __name__ == "__main__":
    main()

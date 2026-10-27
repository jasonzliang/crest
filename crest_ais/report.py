"""Render the analyzed public-paper comparison as an offline HTML document.

Analysis owns the estimand, ranks, intervals, and counts. This module formats
those values; it never estimates a missing score or supplies a verdict.
"""

from collections import defaultdict
from html import escape
import json
import math
import os
from pathlib import Path
from urllib.parse import quote, urlsplit

from .navigation import CSS as NAVIGATION_CSS, site_header
from .protocol import validate_verdict


COLORS = ("#0b5967", "#b4652b", "#5e628c", "#526b46", "#8a4665")
SHORT_NAMES = {
    "sakana_agentic_scientist": "Sakana Agentic Scientist (v3)",
    "sakana_ai_scientist": "Sakana AI Scientist (v1)",
    "sakana_ai_scientist_v2": "Sakana AI Scientist (v2)",
    "scientistone": "ScientistOne",
    "scientisttwo": "ScientistTwo",
}
PROJECT_URLS = {
    "sakana_agentic_scientist": "https://pub.sakana.ai/agentic-scientist/",
    "sakana_ai_scientist": "https://sakana.ai/ai-scientist/",
    "sakana_ai_scientist_v2": "https://github.com/SakanaAI/AI-Scientist-v2",
    "scientistone": "https://scientist-one.github.io/",
    "scientisttwo": "https://scientist-two.github.io/",
}


def _text(value):
    return escape(str(value), quote=True) if value is not None else "Unavailable"


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _percentage(value):
    return _number(value) and 0 <= value <= 100


def _pct(value):
    return f"{value:.1f}%" if _percentage(value) else "Unavailable"


def _count(value):
    return f"{value:,}" if isinstance(value, int) and value >= 0 else "Unavailable"


def _ready(report):
    coverage = report.get("coverage", {})
    expected = coverage.get("expected_jobs")
    return (report.get("status") == "complete" and isinstance(expected, int) and expected > 0
            and coverage.get("completed_jobs") == expected and coverage.get("usable_jobs") == expected)


def _agent_order(report):
    order = list(report.get("agents", {}))
    if _ready(report):
        rows = {row["agent"]: row for row in report.get("rankings", [])}
        order.sort(key=lambda agent: (rows.get(agent, {}).get("rank") is None,
                                      rows.get(agent, {}).get("rank") or math.inf))
    return order


def _label(report, agent):
    return SHORT_NAMES.get(agent, report.get("agents", {}).get(agent) or agent)


def _confidence_label(report):
    uncertainty = report.get("uncertainty", {})
    value = uncertainty.get("confidence_level", uncertainty.get("confidence"))
    return f"{100 * value:g}%" if _number(value) and 0 < value < 1 else None


def _interval(value):
    if not isinstance(value, dict):
        return None
    low, high = value.get("low"), value.get("high")
    return (low, high) if _percentage(low) and _percentage(high) and low <= high else None


def _web_link(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    return value if parsed.scheme.lower() in ("http", "https") and parsed.netloc else None


def _pdf_link(paper, data_root, destination):
    path = paper.get("pdf_path")
    if isinstance(path, str) and path:
        root = data_root.resolve()
        target = (root / path).resolve()
        if target.is_relative_to(root):
            return quote(os.path.relpath(target, destination.parent.resolve()), safe="/.")
    return _web_link(paper.get("pdf_url"))


def _svg_bar(value, color, label):
    """An observed estimate on a fixed 0–100 domain, including true zeroes."""
    if not _percentage(value):
        return '<span class="unavailable">Unavailable</span>'
    description = f"{label}: {_pct(value)}"
    chunks = [
        f'<svg class="bar" viewBox="0 0 400 34" preserveAspectRatio="none" role="img" aria-label="{_text(description)}">',
        f'<title>{_text(description)}</title>',
        '<rect x="4" y="10" width="392" height="14" rx="2" fill="#edf2f3"/>',
        '<path d="M200 4V30" stroke="#91a4ad" stroke-dasharray="2 3"/>',
        f'<rect x="4" y="10" width="{value * 3.92:.3f}" height="14" rx="2" fill="{color}"/>',
    ]
    chunks.append(f'<circle class="mean-dot" cx="{4 + value * 3.92:.3f}" cy="17" r="4" '
                  'fill="#172c3e" stroke="white" stroke-width="1"/>')
    chunks.append("</svg>")
    return "".join(chunks)


def _overall(report, ready, colors):
    rows = {row["agent"]: row for row in report.get("rankings", [])}
    order = _agent_order(report)
    parts = ['<section id="overall" aria-labelledby="overall-heading">',
             '<div class="section-heading"><h2 id="overall-heading">Observed overall ranking</h2>',
             '<span class="unit">Win percentage · higher = more pairwise preferences</span></div>']
    if not ready:
        parts.append('<div class="notice"><strong>Ranking withheld</strong><p>'
                     'The planned comparison is incomplete. Overall ranks and win percentages '
                     'will appear after every planned judgment is usable.</p></div>')
    parts.append('<div id="overall-chart" class="overall-chart">')
    for agent in order:
        row = rows.get(agent, {})
        score = row.get("overall_pct") if ready else None
        rank = row.get("rank") if ready else None
        score_attr = f' data-score="{score}"' if _percentage(score) else ""
        rank_label = f'<span class="rank" aria-label="Rank {_text(rank)}">{_text(rank)}</span>' if rank is not None else ""
        rank_attr = f' data-rank="{_text(rank)}"' if rank is not None else ""
        name = _text(_label(report, agent))
        if agent in PROJECT_URLS:
            name = f'<a href="{PROJECT_URLS[agent]}">{name}</a>'
        parts.append(f'<div class="overall-row" data-agent="{_text(agent)}"{score_attr}{rank_attr}>'
                     f'<div class="agent-label">{rank_label}<strong>{name}</strong></div>'
                     f'{_svg_bar(score, colors[agent], _label(report, agent))}'
                     f'<div class="score{ " unavailable-score" if not _percentage(score) else ""}">'
                     f'<strong>{_pct(score)}</strong></div></div>')
    parts.append('</div><div class="chart-axis" aria-hidden="true"><div class="axis-ticks">'
                 '<span>0%</span><span>50%</span><span>100%</span></div></div>')
    if ready:
        parts.append('<p class="chart-legend"><span class="dot-key" aria-hidden="true"></span>'
                     'Dot = observed win percentage · 50% = an even split</p>')
    opponents = max(0, len(report.get("agents", {})) - 1)
    parts.append('<p class="chart-note">Each judgment selects one overall winner, considering '
                 'New, Useful, and Surprising jointly. We average the win percentages against '
                 f'the other {_count(opponents)} scientist{ "s" if opponents != 1 else ""}, '
                 'giving each opponent equal weight even when sampled pair counts differ. '
                 'This need not equal the share of all raw votes. Scores apply to the opponent '
                 'set in this comparison; adding a scientist changes that set. '
                 'This describes the judges’ preferences for these papers, not absolute '
                 'creativity. Equal scores share a rank.</p>')
    if ready:
        parts.append('<p class="small">The ranking describes the sampled pairs; the ranking across '
                     'all eligible pairs remains uncertain.</p>')
    parts.append(_sampling_uncertainty(report, ready))
    parts.append('</section>')
    return "".join(parts)


def _sampling_uncertainty(report, ready):
    uncertainty = report.get("uncertainty", {})
    confidence = _confidence_label(report)
    exploratory = uncertainty.get("inference_scope") == "exploratory_fixed_size_reference"
    label = ("Exploratory reference range" if exploratory else
             f"{confidence} sampling range" if confidence else "Sampling range (confidence unavailable)")
    explanation = (
        'We increased the sample after the initial results were observed. These exploratory reference '
        'ranges use a calculation intended for a sample size chosen in advance. '
        'No confidence guarantee is claimed for this extended run. '
        if exploratory else
        'Only a sample of paper pairs was judged. These conservative ranges describe how '
        'sampling affects the scores across all eligible pairs, for these judges, prompts, '
        'and paper orders. '
    )
    parts = ['<details id="sampling-uncertainty"><summary>Sampling uncertainty: what these scores can tell us</summary>',
             f'<p class="small">{explanation}They do not measure judge disagreement, '
             'correctness, or future system performance. Wide ranges leave the ranking across '
             'all eligible pairs uncertain; overlapping ranges do not mean the systems are equal.</p>',
             '<div class="table-scroll" role="region" aria-label="Sampling ranges" tabindex="0">'
             f'<table><thead><tr><th scope="col">Scientist</th><th scope="col">{_text(label)}</th>'
             '</tr></thead><tbody>']
    rows = {row["agent"]: row for row in report.get("rankings", [])}
    for agent in _agent_order(report):
        interval = _interval((rows.get(agent, {}).get("intervals") or {}).get("overall")) if ready else None
        value = f"{interval[0]:.1f}–{interval[1]:.1f}%" if interval else "Unavailable"
        parts.append(f'<tr><th scope="row">{_text(_label(report, agent))}</th><td>{value}</td></tr>')
    parts.append('</tbody></table></div><details><summary>Statistical method and assumptions</summary>'
                 '<p class="small">The calculation treats the response to every possible paper pair '
                 'as fixed, with only the sampled pairs changing. Keeping model settings fixed '
                 'does not guarantee the same reply on another call. These bounds exclude '
                 'variation between repeated calls, changes in the provider’s model, agreement '
                 'with human experts, and future papers. The full-pool order remains uncertain. See '
                 '<a href="https://arxiv.org/abs/1309.4029">Bardenet and Maillard, '
                 'Concentration inequalities for sampling without replacement</a>.</p>')
    if uncertainty.get("method"):
        parts.append(f'<p class="small">{_text(uncertainty["method"])}</p>')
    if uncertainty.get("note"):
        parts.append(f'<p class="small">{_text(uncertainty["note"])}</p>')
    parts.append(f'<pre>{_text(json.dumps(uncertainty, ensure_ascii=False, indent=2, sort_keys=True))}</pre>'
                 '</details></details>')
    return "".join(parts)


def _concepts():
    definitions = {
        "new": "How clearly the judge can connect the paper’s least familiar contribution to earlier research. A weaker connection can suggest novelty; the judge’s memory cannot verify it.",
        "useful": "Whether the paper explains how its approach works and provides evidence for its claimed benefit.",
        "surprising": "How far the paper’s central approach departs from the obvious approach to its question.",
    }
    parts = ['<div id="concepts" aria-labelledby="concepts-heading">',
             '<h3 id="concepts-heading">New, Useful, and Surprising</h3>',
             '<p class="small">These concepts are considered jointly in one overall creativity '
             'judgment. They are not scored separately; the judge explains the relevant tradeoffs.</p>'
             '<dl class="concept-definitions">']
    for concept, definition in definitions.items():
        parts.append(f'<div><dt>{concept.title()}</dt><dd>{_text(definition)}</dd></div>')
    parts.append('</dl><p class="small">Conceptual foundations: '
                 '<a href="https://doi.org/10.1080/10400419.2012.650092">Runco and Jaeger (2012), '
                 '<cite>The Standard Definition of Creativity</cite></a>, discusses originality and '
                 'effectiveness. <a href="https://doi.org/10.1080/10400419.2017.1302776">'
                 'Acar, Burnett, and Cabra (2017), <cite>Ingredients of Creativity: Originality '
                 'and More</cite></a>, examines surprise alongside originality and value. '
                 'These support the broad concepts. They do not validate CREST’s specific '
                 'definitions or its model judging method. '
                 '<a href="overall-creativity-judgment.html">Why one joint judgment?</a></p></div>')
    return "".join(parts)


def _matchups(report, ready):
    order = _agent_order(report)
    comparisons = {}
    for row in report.get("comparisons", []):
        pair = row.get("agents", [])
        if len(pair) == 2:
            comparisons[tuple(pair)] = row
    parts = ['<section id="matchups" aria-labelledby="matchups-heading">'
             '<h2 id="matchups-heading">Head to head</h2>',
             '<p class="small">Read across a row: each cell shows how often the judges chose the row '
             'scientist’s papers over the column scientist’s papers, using completed paper pairs. '
             'Diagonal cells compare no papers.</p>']
    selection = report.get("selection", {})
    per_matchup = selection.get("pairs_per_matchup")
    if isinstance(per_matchup, int) and per_matchup > 0:
        parts.append(f'<p class="small">The plan samples up to {_count(per_matchup)} distinct paper pairs '
                     'per scientist matchup. Each completed pair contributes four overall votes: '
                     'two judges, each seeing both paper orders. The pair counts below are not '
                     'counts of independent papers.</p>')
    parts.append('<div class="heatmap-legend" aria-label="Heatmap color scale">'
                 '<span><i class="lower-key" aria-hidden="true"></i>Lower row preference</span>'
                 '<span>50% = even split</span>'
                 '<span><i class="higher-key" aria-hidden="true"></i>Higher row preference</span></div>')
    if not ready:
        parts.append('<p class="small">Incomplete run: available cells describe completed paper pairs only; '
                     'they do not establish an overall rank.</p>')
    parts.append(f'<div class="table-scroll" style="--heatmap-min-width:{max(650, 135 * (len(order) + 1))}px" '
                 'role="region" aria-label="Pairwise win percentage matrix" tabindex="0">'
                 '<table class="heatmap"><thead><tr><th scope="col">Row vs. column</th>')
    for agent in order:
        parts.append(f'<th scope="col">{_text(_label(report, agent))}</th>')
    parts.append('</tr></thead><tbody>')
    for agent in order:
        parts.append(f'<tr data-agent="{_text(agent)}"><th scope="row">{_text(_label(report, agent))}</th>')
        for opponent in order:
            if agent == opponent:
                parts.append('<td class="diagonal" aria-label="Same scientist">—</td>')
                continue
            row = comparisons.get((agent, opponent))
            reverse = False
            if row is None:
                row = comparisons.get((opponent, agent), {})
                reverse = True
            score = row.get("overall_pct_a")
            if _percentage(score) and reverse:
                score = 100 - score
            if not _percentage(score):
                parts.append('<td class="no-cell">Unavailable</td>')
                continue
            # Fixed diverging domain, with a printed number so color is supplementary.
            hue = "11,89,103" if score >= 50 else "180,101,43"
            alpha = 0.06 + abs(score - 50) / 50 * 0.22
            pairs = _count(row.get("complete_pairs"))
            count, population = row.get("complete_pairs"), row.get("population_pairs")
            census = " · all possible pairs" if _number(count) and count > 0 and count == population else ""
            parts.append(f'<td style="background:rgba({hue},{alpha:.3f})">'
                         f'<strong>{_pct(score)}</strong><small>{pairs} pairs{census}</small></td>')
        parts.append('</tr>')
    parts.append('</tbody></table></div></section>')
    return "".join(parts)


def _small_pool_note(report):
    notes = []
    per_agent = report.get("coverage", {}).get("per_agent", {})
    for agent in _agent_order(report):
        eligible = per_agent.get(agent, {}).get("eligible")
        if isinstance(eligible, int) and 0 < eligible <= 3:
            noun = "paper" if eligible == 1 else "papers"
            notes.append(f'{_text(_label(report, agent))} has {_count(eligible)} eligible {noun}')
    if not notes:
        return ""
    label = "Small released pool" if len(notes) == 1 else "Small released pools"
    return (f'<p class="notice compact"><strong>{label}:</strong> ' + "; ".join(notes) + '. '
            'Repeated comparisons of these papers do not add independent papers.</p>')


def _coverage(report):
    coverage = report.get("coverage", {})
    papers = {paper["id"]: paper for paper in report.get("papers", [])}
    judged = defaultdict(set)
    for judgment in report.get("judgments", []):
        for paper_id in judgment.get("order", []):
            paper = papers.get(paper_id)
            if paper:
                judged[paper.get("agent")].add(paper_id)
    per_agent = coverage.get("per_agent", {})
    parts = ['<section id="coverage" aria-labelledby="coverage-heading"><h2 id="coverage-heading">'
             'Paper coverage</h2>',
             f'<p class="small">{_count(coverage.get("selected_papers"))} selected papers from '
             f'{_count(coverage.get("eligible_papers"))} eligible papers; '
             f'{_count(coverage.get("downloaded_papers"))} downloaded in the archive. '
             'The sample share below is selected papers divided by eligible papers. '
             'A paper can appear in several sampled pairs.</p>',
             '<div class="table-scroll" role="region" aria-label="Paper coverage by scientist" tabindex="0">'
             '<table class="coverage-table"><thead><tr><th scope="col">Scientist</th>'
             '<th scope="col">Downloaded</th>'
             '<th scope="col">Eligible</th><th scope="col">Selected</th>'
             '<th scope="col">Sample share</th>'
             '<th scope="col">With a judgment</th></tr></thead><tbody>']
    for agent in _agent_order(report):
        row = per_agent.get(agent, {})
        count = len(judged[agent])
        down, eligible, selected = row.get("downloaded"), row.get("eligible"), row.get("selected")
        share = 100 * selected / eligible if _number(selected) and _number(eligible) and eligible > 0 else None
        excluded = down - eligible if _number(down) and _number(eligible) and down >= eligible else None
        excluded_note = f'<small>{_count(excluded)} excluded</small>' if excluded else ""
        parts.append(f'<tr data-downloaded="{_text(down)}" data-selected="{_text(selected)}" '
                     f'data-judged="{count}"><th scope="row">{_text(_label(report, agent))}</th>'
                     f'<td>{_count(down)}</td><td>{_count(eligible)}{excluded_note}</td>'
                     f'<td>{_count(selected)}</td><td>{_pct(share)}</td><td>{count}</td></tr>')
    parts.append('</tbody></table></div>')
    if any(paper.get("eligible_primary") is False
           and str(paper.get("title", "")).startswith("Diffusing Blame")
           for paper in report.get("catalog", [])):
        parts.append('<p class="small">Diffusing Blame is retained in the archive but excluded '
                     'from the primary ranking because '
                     '<a href="https://pub.sakana.ai/agentic-scientist/">Sakana describes</a> '
                     'substantial human guidance and manuscript revision.</p>')
    parts.append('<p class="small">Each opponent has equal weight in the score. '
                 'Differences in topics, release dates, underlying AI models, and human involvement '
                 'still limit the comparison.</p>')
    parts.append('</section>')
    return "".join(parts)


def _per_judge(report):
    summaries = report.get("diagnostics", {}).get("per_judge", {})
    if not summaries:
        return ""
    judges = list(summaries)
    parts = ['<p class="small">Each judge’s overall win percentages use paper pairs with all four '
             'judgments and give each opponent equal weight. Scores are unavailable if an opponent '
             'has no completed pairs.</p>'
             '<div class="table-scroll" role="region" aria-label="Win percentages by judge and scientist" tabindex="0">'
             '<table class="judge-comparison"><thead><tr><th scope="col">Scientist</th>']
    for judge in judges:
        settings = report.get("judges", {}).get(judge, {})
        model = settings.get("model") if isinstance(settings, dict) else None
        parts.append(f'<th scope="col">{_text(judge)}<small class="model-id">{_text(model)}</small></th>')
    parts.append('</tr></thead><tbody>')
    for agent in _agent_order(report):
        parts.append(f'<tr data-agent="{_text(agent)}"><th scope="row">{_text(_label(report, agent))}</th>')
        for judge in judges:
            summary = summaries[judge].get(agent, {})
            parts.append(
                         f'<td><strong>{_pct(summary.get("overall_pct"))}</strong></td>')
        parts.append('</tr>')
    parts.append('</tbody></table></div>')
    return "".join(parts)


def _judges(report):
    diagnostics = report.get("diagnostics", {})
    denominators = diagnostics.get("denominators") or {}
    checks = (
        ("judge_disagreement_pct", "Judge disagreement", "judge_disagreement", "matched judge comparisons"),
        ("swapped_inconsistency_pct", "Changed choice after order swap", "swapped_inconsistency", "matched order comparisons"),
        ("position_a_pct", "Position A chosen", "position_a", "overall judgments"),
    )
    parts = ['<section id="judges" aria-labelledby="judges-heading"><h2 id="judges-heading">'
             'Do the judges agree?</h2>', _per_judge(report), '<dl class="diagnostics">']
    for key, label, denominator_key, unit in checks:
        parts.append(f'<div><dt>{label}</dt><dd>{_pct(diagnostics.get(key))}</dd>'
                     f'<small>Across {_count(denominators.get(denominator_key))} {unit}</small></div>')
    parts.append('</dl><p class="small">Agreement does not establish correctness. These checks '
                 'describe the sampled papers, these judges, and the recorded paper orders; '
                 'they do not validate the creativity rubric or the papers’ claims.</p></section>')
    return "".join(parts)


def _progress(report):
    coverage, costs = report.get("coverage", {}), report.get("costs", {})
    known = costs.get("known_usd")
    prior_known = costs.get("prior_excluded_known_usd")
    money = f"${known:.2f}" if _number(known) and known >= 0 else "Unavailable"
    parts = ['<section id="progress" aria-labelledby="progress-heading"><h2 id="progress-heading">'
             'Run progress and cost</h2>'
             '<div class="run-stats">',
             f'<div><strong>{_count(coverage.get("completed_jobs"))} / {_count(coverage.get("expected_jobs"))}</strong>'
             '<span>saved judgments / planned</span></div>',
             f'<div><strong>{_count(coverage.get("complete_pairs"))} / {_count(coverage.get("expected_pairs"))}</strong>'
             '<span>fully judged paper pairs / planned</span></div>',
             f'<div><strong>{money}</strong><span>estimated judging cost (USD)</span></div></div>',
             '<p class="small">Cost is estimated from recorded usage at published rates.</p>']
    if costs.get("unknown_jobs"):
        parts.append(f'<p class="small">Cost estimates are pending for {_count(costs["unknown_jobs"])} requests.</p>')
    if "prior_excluded_jobs" in costs or "prior_excluded_known_usd" in costs:
        prior_money = f"${prior_known:.2f}" if _number(prior_known) and prior_known >= 0 else "Unavailable"
        parts.append(f'<p class="small">Estimated total includes {_count(costs.get("prior_excluded_jobs"))} '
                     f'prior discarded requests: {prior_money} in recorded estimated cost. '
                     'Those requests do not contribute to the comparison.</p>')
    parts.append('<details id="run-audit"><summary>Judging details</summary>'
                 f'<p class="small">Usable judgments: {_count(coverage.get("usable_jobs"))}. '
                 f'Decisions used: {_count(coverage.get("used_decisions"))} / {_count(coverage.get("expected_decisions"))} planned.</p>'
                 '<ul class="model-list">')
    for judge, settings in report.get("judges", {}).items():
        parts.append(f'<li><strong>{_text(judge)}</strong><pre>{_text(json.dumps(settings, ensure_ascii=False, indent=2, sort_keys=True))}</pre></li>')
    parts.append('</ul></details></section>')
    return "".join(parts)


def _papers(report, data_root, destination):
    agents = report.get("agents", {})
    groups = defaultdict(list)
    for paper in report.get("papers", []):
        groups[paper.get("agent")].append(paper)
    parts = ['<section id="papers" aria-labelledby="papers-heading"><h2 id="papers-heading">'
             'Read the selected papers</h2><p class="small">Full PDFs and original release sources. '
             'This is the selected sample, not the complete downloaded archive.</p>']
    if not groups:
        parts.append('<p>No papers selected.</p>')
    order = _agent_order(report) + [agent for agent in groups if agent not in agents]
    for agent in order:
        group = groups.get(agent)
        if not group:
            continue
        parts.append(f'<details class="paper-group" data-agent="{_text(agent)}"><summary>{_text(_label(report, agent))} '
                     f'<span class="muted">· {len(group)} selected papers</span></summary>'
                     '<div class="table-scroll" role="region" aria-label="Selected papers" tabindex="0">'
                     '<table class="papers-table"><thead><tr><th scope="col">Paper</th>'
                     '<th scope="col">Topic / pages</th><th scope="col">Read</th></tr></thead><tbody>')
        for paper in group:
            title = paper.get("title", paper.get("id"))
            parts.append(f'<tr><th scope="row">{_text(title)}'
                         '<details class="paper-record"><summary>Paper record and extraction notes</summary>'
                         f'<pre>{_text(json.dumps(paper, ensure_ascii=False, indent=2, sort_keys=True))}</pre>'
                         '</details></th>'
                         f'<td>{_text(paper.get("topic"))}<small>{_count(paper.get("pages"))} pages</small></td><td class="paper-links">')
            pdf = _pdf_link(paper, data_root, destination)
            if pdf:
                parts.append(f'<a href="{_text(pdf)}">Full PDF<span class="sr-only">: {_text(title)}</span></a>')
            source = _web_link(paper.get("source_url"))
            if source:
                parts.append(f'<a href="{_text(source)}">Original source<span class="sr-only">: {_text(title)}</span></a>')
            if not pdf and not source:
                parts.append('Unavailable')
            parts.append('</td></tr>')
        parts.append('</tbody></table></div></details>')
    parts.append('</section>')
    return "".join(parts)


def _judgment_reasons(report, group, papers):
    parts = []
    for judgment in group:
        order = judgment.get("order", [])
        model = judgment.get("model")
        if not model:
            settings = report.get("judges", {}).get(judgment.get("judge"), {})
            model = settings.get("model") if isinstance(settings, dict) else None
        parts.append(f'<article class="judgment"><h3>{_text(judgment.get("judge"))} '
                     f'<span class="model-id">{_text(model)}</span></h3>')
        for label, paper_id in zip(("A", "B"), order):
            paper = papers.get(paper_id, {})
            parts.append(f'<p class="answer-map"><strong>{label}: {_text(paper.get("title", paper_id))}</strong>'
                         f' <span class="muted">({_text(_label(report, paper.get("agent")))})</span></p>')
        verdict = judgment["verdict"]
        index = {"A": 0, "B": 1}[verdict["winner"]]
        winning_id = order[index] if len(order) > index else None
        preferred = papers.get(winning_id, {}).get("title", winning_id)
        parts.append(f'<div class="overall-reason"><p><strong>Preferred: {_text(preferred)}</strong></p>'
                     f'<p>{_text(verdict["reason"])}</p></div>'
                     '<details class="judgment-record"><summary>Record identifiers</summary>'
                     f'<p class="small">Pair: {_text(judgment.get("pair_id"))}<br>'
                     f'Judgment: {_text(judgment.get("key"))}</p></details></article>')
    return "".join(parts)


def _judgments(report, data_root, destination):
    papers = {paper["id"]: paper for paper in report.get("papers", [])}
    groups = defaultdict(list)
    for judgment in report.get("judgments", []):
        groups[judgment.get("pair_id", judgment.get("key"))].append(judgment)
    parts = ['<section id="reasons" aria-labelledby="reasons-heading"><h2 id="reasons-heading">'
             'Inspect the judgments</h2><p class="small">Each paper pair has four votes: two judges, '
             'each seeing both paper orders. Individual judgments choose A or B; the four votes '
             'can still produce a 2–2 tie. Incomplete pairs have no final result.</p>'
             '<p class="small">The row winner is the majority of four recorded votes. The overall '
             'score uses all votes, so a 3–1 pair contributes 75%, not 100%. These are model '
             'preferences, not verified paper quality.</p>']
    if not groups:
        parts.append('<p>No judgments yet. No reasons or preferences are available.</p>')
        return "".join(parts) + '</section>'

    agent_positions = {agent: index for index, agent in enumerate(_agent_order(report))}
    rows = []
    for pair_id, group in groups.items():
        paper_ids = list(dict.fromkeys(group[0].get("order", [])))[:2]
        paper_ids.sort(key=lambda identity: (agent_positions.get(papers.get(identity, {}).get("agent"), math.inf),
                                             str(identity)))
        if len(paper_ids) != 2:
            raise ValueError("Judgment pair must identify two distinct papers")
        votes = dict.fromkeys(paper_ids, 0)
        cells, keys = set(), set()
        valid_orders = {tuple(paper_ids), tuple(paper_ids[::-1])}
        for judgment in group:
            order = judgment.get("order", [])
            if tuple(order) not in valid_orders:
                continue
            winning_id = order[0 if judgment["verdict"]["winner"] == "A" else 1]
            votes[winning_id] += 1
            cells.add((judgment.get("judge"), tuple(order)))
            keys.add(judgment.get("key"))
        expected_cells = {(judge, order) for judge in report.get("judges", {}) for order in valid_orders}
        complete = len(group) == len(keys) == 4 and len(expected_cells) == 4 and cells == expected_cells
        winner = None
        outcome = "partial"
        if complete:
            left, right = (votes[identity] for identity in paper_ids)
            outcome = "tie" if left == right else "winner"
            winner = paper_ids[0] if left > right else paper_ids[1] if right > left else None
        matchup = tuple(papers.get(identity, {}).get("agent") for identity in paper_ids)
        rows.append({"id": pair_id, "papers": paper_ids, "group": group, "matchup": matchup,
                     "votes": votes, "winner": winner, "outcome": outcome})
    rows.sort(key=lambda row: tuple(agent_positions.get(agent, math.inf) for agent in row["matchup"]))
    matchups = list(dict.fromkeys(row["matchup"] for row in rows))
    matchup_ids = {matchup: f"matchup-{index}" for index, matchup in enumerate(matchups)}
    completed = sum(row["outcome"] != "partial" for row in rows)
    ties = sum(row["outcome"] == "tie" for row in rows)
    column_note = ("The higher-ranked scientist is shown as Paper 1. " if _ready(report) else "")
    column_note += "These columns are not the judge’s A/B labels."
    parts.append('<div class="judgment-tools"><label for="judgment-matchup">Scientist matchup</label>'
                 '<select id="judgment-matchup" aria-controls="judgment-pair-table" disabled>'
                 f'<option value="all">All matchups · {len(rows)} paper pairs</option>')
    for matchup in matchups:
        label = " vs. ".join(str(_label(report, agent)) for agent in matchup)
        count = sum(row["matchup"] == matchup for row in rows)
        parts.append(f'<option value="{matchup_ids[matchup]}">{_text(label)} · {count} pairs</option>')
    parts.append('</select>'
                 f'<span id="judgment-count" role="status" aria-live="polite">{len(rows)} paper pairs · '
                 f'{completed} complete · {ties} tied</span></div>'
                 '<div class="table-scroll judgment-table-scroll" role="region" '
                 'aria-label="Paper-pair outcomes and expandable judgments" tabindex="0">'
                 '<table class="judgment-pairs" id="judgment-pair-table">'
                 f'<caption>{_text(column_note)} Vote splits follow Paper 1–Paper 2 order. '
                 'Expand a row to read every saved reason.</caption>'
                 '<thead><tr><th scope="col">Paper 1</th><th scope="col">Paper 2</th>'
                 '<th scope="col">Recorded outcome</th></tr></thead>')
    for index, row in enumerate(rows, start=1):
        left_id, right_id = row["papers"]
        votes = row["votes"]
        winner_attr = f' data-winner="{_text(row["winner"])}"' if row["winner"] is not None else ""
        parts.append(f'<tbody class="judgment-pair" data-pair-id="{_text(row["id"])}" '
                     f'data-matchup="{matchup_ids[row["matchup"]]}" data-outcome="{row["outcome"]}" '
                     f'data-votes-left="{votes[left_id]}" data-votes-right="{votes[right_id]}"{winner_attr}><tr>')
        for position, paper_id in enumerate(row["papers"], start=1):
            paper = papers.get(paper_id, {})
            tag = 'th scope="row"' if position == 1 else "td"
            close_tag = "th" if position == 1 else "td"
            parts.append(f'<{tag} class="pair-paper">')
            title = paper.get("title", paper_id)
            pdf = _pdf_link(paper, data_root, destination)
            if pdf:
                parts.append(f'<a class="pair-title" href="{_text(pdf)}" '
                             f'aria-label="Read full PDF: {_text(title)}">{_text(title)}</a>')
            else:
                parts.append(f'<span class="pair-title">{_text(title)}</span>')
            parts.append(f'<small>{_text(_label(report, paper.get("agent")))}'
                         f'{ " · PDF" if pdf else ""}</small></{close_tag}>')
        split = f'{votes[left_id]}–{votes[right_id]} votes'
        parts.append('<td class="pair-outcome">')
        if row["outcome"] == "partial":
            parts.append(f'<strong>Partial: {len(row["group"])} / 4 judgments</strong>'
                         f'<span>Recorded split: {split}</span><small>No final pair result</small>')
        elif row["outcome"] == "tie":
            parts.append(f'<strong>Tie</strong><span>{split}</span>')
        else:
            slot = 1 if row["winner"] == left_id else 2
            preferred = _label(report, papers[row["winner"]].get("agent"))
            parts.append(f'<strong>{_text(preferred)} preferred</strong><span>{split}</span>'
                         f'<small>Paper {slot}</small>')
        parts.append('</td></tr><tr><td colspan="3" class="pair-reason-cell">'
                     f'<details class="pair-reasons" id="pair-reasons-{index}">'
                     f'<summary>Read {len(row["group"])} saved judgments'
                     f'<span class="sr-only"> for pair {index}</span></summary>')
        parts.append(_judgment_reasons(report, row["group"], papers))
        parts.append('</details></td></tr></tbody>')
    parts.append('</table></div></section>')
    return "".join(parts)


def _method(report):
    parts = ['<section id="method" aria-labelledby="method-heading"><h2 id="method-heading">'
             'How the comparison works</h2><p>The lists of eligible released papers are saved '
             'before sampling. The separately labeled human–AI co-discovery paper is excluded. '
             'Distinct paper pairs are sampled uniformly within each scientist '
             'matchup. Each judge chooses one overall creativity winner, considering New, Useful, '
             'and Surprising jointly, in both paper orders. Each complete paper pair contributes '
             'four overall votes. Votes are averaged within the paper pair, then paper pairs '
             'within a matchup. Each opponent matchup receives equal weight.</p>', _concepts(),
             '<h3>What this comparison leaves uncertain</h3><ul class="key-limits">'
             '<li>Topics, release dates, underlying AI models, computing resources, and which papers '
             'each team chose to release differ '
             'across the paper collections.</li><li>Judges read extracted PDF text; visual plots '
             'and experimental claims were not independently verified.</li>'
             '<li>The results concern these released papers and these judges. Small collections '
             'sharply limit what can be inferred about future papers.</li></ul>'
             '<p class="small"><a href="ai-scientist-method.html">Paper comparison method</a></p>'
             '<details><summary>Frozen sampling plan and full limitations</summary>']
    selection = report.get("selection")
    if selection:
        parts.append(f'<pre>{_text(json.dumps(selection, ensure_ascii=False, indent=2, sort_keys=True))}</pre>')
    limits = list(report.get("limitations", []))
    defaults = [
        "This compares a fixed public-paper collection; it is not a controlled benchmark of future system performance.",
        "PDF text extraction does not inspect visual plots or independently verify experimental claims.",
        "Sampling uncertainty is conditional on the released pool and judge instrument; it does not establish generalization to other papers or systems.",
    ]
    parts.append('<ul>')
    for limitation in limits or defaults:
        parts.append(f'<li>{_text(limitation)}</li>')
    parts.append('</ul></details></section>')
    return "".join(parts)


CSS = """
:root{--ink:#172c3e;--muted:#526574;--accent:#0b5967;--line:#d7e1e6;--wash:#f5f8f9;--paper:#fff}
*{box-sizing:border-box}html{scroll-padding-top:1.2rem}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
a{color:var(--accent);text-underline-offset:3px;overflow-wrap:anywhere}a:hover{text-decoration-thickness:2px}:focus-visible{outline:3px solid #b45a13;outline-offset:4px}
.skip-link{position:fixed;top:-100px;left:1rem;padding:.6rem 1rem;background:var(--ink);color:#fff;z-index:10}.skip-link:focus{top:1rem}
main{max-width:1160px;margin:auto;padding:2.8rem clamp(1.1rem,4vw,3rem) 4rem}.brand{font-weight:800;letter-spacing:.15em;font-size:.85rem;color:var(--accent)}
header{border-bottom:2px solid var(--ink);padding-bottom:1.7rem}h1{font-size:clamp(2rem,5vw,3.65rem);line-height:1.08;letter-spacing:-.045em;max-width:21ch;margin:.8rem 0 1rem;font-weight:750}.subtitle{max-width:70ch;color:var(--muted);font-size:1.06rem;margin:0}
.meta{display:flex;flex-wrap:wrap;gap:.4rem 1.3rem;font-size:.8rem;color:var(--muted);margin-top:1.3rem}.status{font-weight:700;color:var(--accent)}nav{display:flex;flex-wrap:wrap;gap:.35rem 1.25rem;padding:1rem 0;font-size:.82rem}nav a{text-decoration:none}
section{margin:2.2rem 0 0;padding-top:1.5rem;border-top:1px solid var(--line)}#overall{border-top:0;margin-top:1rem}h2{font-size:1.55rem;line-height:1.25;letter-spacing:-.025em;margin:0 0 1rem}h3{font-size:1rem;margin:.6rem 0}p{margin:.7rem 0 1rem}.section-heading{display:flex;align-items:baseline;justify-content:space-between;gap:1rem;flex-wrap:wrap}.unit,.small,.chart-note{color:var(--muted);font-size:.83rem}.chart-note{max-width:90ch;margin-top:1.1rem}.unit{font-size:.75rem}.notice{border-left:3px solid #997024;background:#fbf6e9;padding:.85rem 1rem;margin:1rem 0;font-size:.9rem}.notice p{margin:.25rem 0 0}.notice.compact{font-size:.85rem}
.overall-chart{margin-top:1.4rem}.overall-row{display:grid;grid-template-columns:minmax(170px,1.3fr) minmax(100px,2.1fr) minmax(105px,.65fr);gap:1.3rem;align-items:center;padding:.75rem 0}.agent-label{display:flex;align-items:center;gap:.8rem;font-size:.95rem;line-height:1.4}.rank{font-size:.85rem;font-weight:600;color:var(--muted);min-width:1ch}.bar{display:block;width:100%;height:34px}.interval-line{stroke:#172c3e;stroke-width:1.6;fill:none}.score{text-align:right;line-height:1.35}.score>strong{font-size:1.4rem;font-variant-numeric:tabular-nums;letter-spacing:-.03em}.score small{display:block;font-size:.7rem;color:var(--muted);margin-top:.25rem}.score.unavailable-score>strong{font-size:.85rem;font-weight:500;color:var(--muted)}.chart-axis{display:flex;justify-content:space-between;margin:0 calc((100% - 2.6rem)*.65/4.05 + 1.3rem) 0 calc((100% - 2.6rem)*1.3/4.05 + 1.3rem);font-size:.7rem;color:var(--muted)}.unavailable{color:var(--muted);font-size:.8rem}
.concept-definitions{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1.5rem;margin:1rem 0}.concept-definitions dt{font-size:1rem;font-weight:650;color:var(--accent)}.concept-definitions dd{font-size:.83rem;line-height:1.6;color:var(--muted);margin:.4rem 0 0}
.table-scroll{overflow:auto;max-width:100%;margin:1rem 0}table{border-collapse:collapse;width:100%;text-align:left;font-size:.82rem;line-height:1.5}th,td{padding:.7rem .8rem;border-bottom:1px solid var(--line);vertical-align:middle}thead th{background:var(--wash);font-weight:650;color:#183d49}tbody th{font-weight:550}td small,th small{display:block;color:var(--muted);font-size:.72rem;margin-top:.3rem}.heatmap{table-layout:fixed;min-width:650px}.heatmap th{font-size:.75rem}.heatmap td{text-align:center}.heatmap td strong{font-size:1.18rem;font-variant-numeric:tabular-nums;font-weight:650}.heatmap .diagonal{background:#f5f8f9;color:#8b9aa3}.no-cell{font-size:.73rem;color:var(--muted)}.coverage-table{min-width:760px}.coverage-table th:first-child{width:24%}.coverage-table th:nth-child(2){width:24%}.coverage-bar{width:100%;min-width:110px;height:44px;display:block}.coverage-table td:nth-child(n+3){font-variant-numeric:tabular-nums;text-align:right}.coverage-table th:nth-child(n+3){text-align:right}.legend{display:flex;flex-wrap:wrap;gap:.5rem 1.2rem;font-size:.75rem;color:var(--muted)}.legend span{display:flex;gap:.4rem;align-items:center}.legend i{display:inline-block;width:.8rem;height:.55rem}.downloaded-key{background:#b8cbd1}.selected-key{background:var(--accent)}.judged-key{background:var(--ink)}
.run-stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1.5rem;padding:.65rem 0}.run-stats strong{display:block;color:var(--accent);font-size:1.7rem;letter-spacing:-.025em;font-variant-numeric:tabular-nums}.run-stats span{display:block;color:var(--muted);font-size:.75rem}.diagnostics{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem;font-size:.8rem}.diagnostics dt{color:var(--muted)}.diagnostics dd{margin:.4rem 0;font-size:1.2rem;font-weight:600}
.judge-comparison{min-width:520px}.judge-comparison th[scope="rowgroup"]{width:27%;vertical-align:top}.judge-comparison th[scope="row"]{width:27%}.judge-comparison td{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}.judge-comparison thead th:nth-child(n+3){text-align:right}
details{border-top:1px solid var(--line);border-bottom:1px solid var(--line);margin:.7rem 0}details+details{border-top:0;margin-top:-.7rem}summary{cursor:pointer;color:var(--accent);font-size:.88rem;font-weight:600;line-height:1.5;padding:.9rem .1rem}details[open]>summary{margin-bottom:.5rem}.muted{color:var(--muted);font-weight:400}pre,code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:.75rem;overflow-wrap:anywhere}pre{white-space:pre-wrap;background:var(--wash);padding:1rem;max-height:20rem;overflow:auto}.model-list{padding-left:1.2rem}.model-list>li{font-size:.85rem}.papers-table{min-width:560px}.papers-table th:first-child{width:60%}.papers-table td{vertical-align:top}.paper-id{font-size:.67rem;font-weight:400;overflow-wrap:anywhere}.paper-links a{display:block;margin-bottom:.25rem}.paper-links{min-width:120px}.judgment{padding:.6rem .4rem 1rem;border-top:1px solid var(--line)}.judgment h3{font-size:.86rem}.model-id{display:block;font-size:.73rem;font-weight:400;color:var(--muted);overflow-wrap:anywhere}.answer-map{font-size:.8rem;line-height:1.5;margin:.5rem 0}.overall-reason{font-size:.85rem;overflow-wrap:anywhere}.overall-reason p{margin:.5rem 0}.judgment-pair>summary{overflow-wrap:anywhere}.judgment-pair .muted{font-size:.75rem}li{margin:.55rem 0}#method>p,#method li{font-size:.9rem;max-width:95ch}footer{border-top:1px solid var(--line);padding-top:1rem;margin-top:2.5rem;font-size:.75rem;color:var(--muted)}.sr-only{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(max-width:760px){main{padding-top:1.7rem}.overall-row{grid-template-columns:minmax(130px,1fr) minmax(90px,1fr);gap:.4rem 1rem;padding:.8rem 0}.overall-row .bar,.overall-row>.unavailable{grid-column:1/-1;grid-row:2}.score{grid-column:2;grid-row:1}.score>strong{font-size:1.25rem}.score small{font-size:.65rem}.agent-label{font-size:.88rem}.chart-axis{margin:0 .25rem}.section-heading{gap:.1rem}.run-stats{gap:.8rem}.run-stats strong{font-size:1.3rem}.diagnostics{grid-template-columns:1fr}h2{font-size:1.35rem}.unit{margin-bottom:.7rem}.coverage-table{min-width:720px}}
@media(max-width:430px){.run-stats{grid-template-columns:1fr;gap:1rem}.run-stats>div{display:flex;align-items:baseline;gap:.8rem}.run-stats strong{min-width:115px;font-size:1.25rem}h1{font-size:2.3rem}.overall-row{grid-template-columns:1fr 110px}.meta{font-size:.72rem}}
@media(max-width:760px){.concept-definitions{grid-template-columns:1fr;gap:.9rem}}
@media print{main{max-width:none;padding:0}body{font-size:10pt}nav,.skip-link{display:none}h1{font-size:30pt}section{break-inside:avoid}.table-scroll{overflow:visible}.heatmap,.coverage-table,.papers-table{min-width:0}table{font-size:8pt}th,td{padding:.4rem}details{border:0}details::details-content{content-visibility:visible}details>*:not(summary){display:block!important}pre{max-height:none}a{color:inherit}}

#overall{--ranking-columns:minmax(175px,1.1fr) minmax(150px,2.3fr) 90px;--ranking-gap:1rem}
.overall-row,.chart-axis{display:grid;grid-template-columns:var(--ranking-columns);gap:var(--ranking-gap)}
.chart-axis{margin:0;font-size:.72rem}.axis-ticks{grid-column:2;display:flex;justify-content:space-between;padding:0 1%}
.chart-legend{font-size:.78rem;color:var(--muted);display:flex;align-items:center;gap:.5rem;margin:.8rem 0}.dot-key{width:.5rem;height:.5rem;border-radius:50%;background:var(--ink);display:inline-block;flex-shrink:0}
.heatmap-legend{display:flex;gap:.5rem 1.2rem;flex-wrap:wrap;color:var(--muted);font-size:.75rem}.heatmap-legend>span{display:inline-flex;align-items:center;gap:.4rem}.heatmap-legend i{display:inline-block;width:.8rem;height:.65rem}.lower-key{background:rgba(180,101,43,.28)}.higher-key{background:rgba(11,89,103,.28)}
.coverage-table{min-width:650px}.coverage-table th:first-child{width:28%}.coverage-table th:nth-child(2){width:auto}.coverage-table th:nth-child(n+2),.coverage-table td{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.judge-comparison{table-layout:fixed;min-width:460px}.judge-comparison thead th:first-child,.judge-comparison th[scope="row"]{width:38%}.judge-comparison thead th:nth-child(n+2){text-align:right}.judge-comparison .model-id{font-size:.75rem}.diagnostics small{display:block;font-size:.75rem;color:var(--muted)}
.canonical-names{font-size:.8rem}.canonical-names>div{margin:.7rem 0}.canonical-names dt{font-weight:650}.canonical-names dd{margin:.15rem 0;color:var(--muted)}
.paper-record summary{font-size:.72rem;font-weight:400}.paper-record pre{font-weight:400}.key-limits{font-size:.86rem}
@media(max-width:760px){.overall-row{grid-template-columns:minmax(0,1fr) 110px;gap:.3rem 1rem}.chart-axis{grid-template-columns:minmax(0,1fr);gap:0}.axis-ticks{grid-column:1}.coverage-table{min-width:630px}.score>strong{font-size:1.25rem}.agent-label{min-width:0;overflow-wrap:anywhere}.unit{max-width:42ch}}
#main-content>section~section{border-top:1px solid var(--line);padding-top:2rem}
#method>p{max-width:none}
.heatmap{min-width:var(--heatmap-min-width,650px)}
#main-content>nav[aria-label="Report contents"]{border-bottom:1px solid var(--line);padding-bottom:1rem;margin-bottom:1.5rem}
#reasons .judgment-tools{display:flex;align-items:center;flex-wrap:wrap;gap:.6rem .9rem;margin:1.2rem 0;font-size:.8rem}
#reasons .judgment-tools label{font-weight:650}#reasons select{max-width:100%;padding:.45rem .6rem;border:1px solid #a6bac3;border-radius:3px;background:white;color:var(--ink);font:inherit}
#judgment-count{color:var(--muted);font-size:.77rem}#reasons .judgment-table-scroll{position:relative;max-height:48rem;overflow:auto;overscroll-behavior:contain;scrollbar-gutter:stable}
#reasons .judgment-pairs{table-layout:fixed;min-width:740px;font-size:.84rem}#reasons .judgment-pairs caption{text-align:left;font-size:.76rem;color:var(--muted);padding:.6rem .8rem}
#reasons .judgment-pairs thead th{position:sticky;top:0;z-index:2;background:#eaf1f3}#reasons .judgment-pairs thead th:nth-child(1),#reasons .judgment-pairs thead th:nth-child(2){width:39%}
#reasons .judgment-pair:nth-of-type(even){background:#f8fafb}#reasons .judgment-pair[hidden]{display:none}
#reasons .pair-paper{vertical-align:top;font-weight:500}#reasons .pair-title{display:block;font-weight:600;line-height:1.5;overflow-wrap:anywhere}#reasons .pair-paper small{font-size:.74rem;margin-top:.6rem;font-weight:400}
#reasons .pair-outcome{vertical-align:top}#reasons .pair-outcome strong,#reasons .pair-outcome>span{display:block}#reasons .pair-outcome strong{font-size:.9rem;color:var(--ink)}#reasons .pair-outcome>span{margin-top:.35rem;font-variant-numeric:tabular-nums}
#reasons .pair-reason-cell{padding-top:0}#reasons .pair-reasons{padding:0;margin:0;border:0}#reasons .pair-reasons>summary{font-size:.78rem;padding:.5rem 0 .9rem}
#reasons .judgment{padding:1rem 0 1.4rem;border:0}#reasons .overall-reason{font-size:.9rem;line-height:1.75}#reasons .overall-reason p{white-space:pre-wrap}
#reasons .judgment-record{margin-top:.5rem}#reasons .judgment-record>summary{font-size:.73rem;font-weight:400;padding:.3rem 0}#reasons .judgment-record p{overflow-wrap:anywhere}
@media(max-width:760px){#reasons .pair-reasons .judgment{max-width:calc(100vw - 5rem)}}
@media print{#reasons .judgment-tools{display:none}#reasons .judgment-table-scroll{max-height:none;overflow:visible}#reasons .judgment-pairs{min-width:0}#reasons .judgment-pairs thead th{position:static}}

"""


JUDGMENT_SCRIPT = """
(() => {
  const filter = document.getElementById('judgment-matchup');
  const table = document.getElementById('judgment-pair-table');
  const count = document.getElementById('judgment-count');
  if (!filter || !table || !count) return;
  const groups = Array.from(table.querySelectorAll('tbody[data-matchup]'));
  filter.disabled = false;
  filter.addEventListener('change', () => {
    let shown = 0;
    for (const group of groups) {
      group.hidden = filter.value !== 'all' && group.dataset.matchup !== filter.value;
      if (!group.hidden) shown += 1;
    }
    count.textContent = `Showing ${shown} of ${groups.length} paper pairs`;
    table.parentElement.scrollTop = 0;
  });
})();
"""


def write_report(report: dict, destination: Path, *, data_root: Path) -> None:
    """Write a self-contained report; links are relative to its final location."""
    for judgment in report.get("judgments", []):
        validate_verdict(judgment.get("verdict"))
    destination, data_root = Path(destination), Path(data_root)
    coverage = report.get("coverage", {})
    ready = _ready(report)
    colors = {agent: COLORS[index % len(COLORS)] for index, agent in enumerate(report.get("agents", {}))}
    completed = coverage.get("completed_jobs")
    sample = (f'{_count(coverage.get("selected_papers"))} papers selected from '
              f'{_count(coverage.get("eligible_papers"))} eligible papers in a '
              f'{_count(coverage.get("downloaded_papers"))}-paper archive.')
    introduction = (f'This completed comparison uses {sample}' if ready else
                    f'This comparison has not been judged yet. The plan uses {sample}' if completed == 0 else
                    f'This comparison is in progress and uses {sample}')
    parts = ['<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width, initial-scale=1">',
             '<meta name="color-scheme" content="light"><title>AI scientist comparison · CREST</title>',
             '<meta name="description" content="A reproducible pairwise comparison of released AI scientist papers, with coverage, judgments, and uncertainty.">',
             f'<style>{CSS}\n{NAVIGATION_CSS}</style></head><body>',
             site_header(data_root.resolve().parent, destination),
             '<a class="skip-link" href="#main-content">Skip to report</a><main id="main-content" tabindex="-1">',
             '<header><div class="brand">PUBLIC-PAPER COMPARISON</div>',
             '<h1>AI scientist comparison</h1>',
             f'<p class="subtitle">{introduction} AI judges assess overall creative quality '
             'by considering New, Useful, and Surprising together.</p></header>',
             '<nav aria-label="Report contents"><a href="#progress">Run summary</a>'
             '<a href="#overall">Overall</a>'
             '<a href="#matchups">Head to head</a><a href="#judges">Judges</a>'
             '<a href="#coverage">Coverage</a><a href="#method">Method</a>'
             '<a href="#concepts">Joint judgment</a><a href="#papers">Papers</a>'
             '<a href="#reasons">Judgments</a></nav>',
             _progress(report), _small_pool_note(report), _overall(report, ready, colors), _matchups(report, ready),
             _judges(report), _coverage(report), _method(report), _papers(report, data_root, destination),
             _judgments(report, data_root, destination),
             f'<footer>CREST · {_text(report.get("version"))} · Offline report. '
             'All displayed scores, ranks, intervals, and reasons come from the saved analysis.</footer>',
             f'</main><script>{JUDGMENT_SCRIPT}</script></body></html>\n']
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("".join(parts), encoding="utf-8")

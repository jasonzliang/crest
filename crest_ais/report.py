"""Render the analyzed public-paper comparison as an offline HTML document.

Analysis owns the estimand, ranks, intervals, and counts. This module formats
those values; it never estimates a missing score or supplies a verdict.
"""

from collections import defaultdict
from html import escape
import math
import os
from pathlib import Path
from urllib.parse import quote, urlsplit

from crest.rubrics import AUT_KIND, NUS_KIND, protocol_rubric_kind

from .analysis import number_word
from .navigation import CSS as NAVIGATION_CSS, site_favicon, site_header
from .protocol import LEGACY_PROTOCOL_VERSION, validate_verdict


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
# Reader-facing judge names; model ids appear only in the one-line judge settings.
JUDGE_NAMES = {"anthropic": "Claude Fable 5.1", "gemini": "Gemini 4 Argon", "openai": "GPT-6 Astra"}
# Each provider's reasoning setting, labelled as the settings line shows it.
JUDGE_EFFORT_KEYS = (("effort", "effort"), ("thinking_level", "thinking level"), ("reasoning_effort", "reasoning effort"))


def _text(value):
    return escape(str(value), quote=True) if value is not None else "Unavailable"


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _percentage(value):
    return _number(value) and 0 <= value <= 100


def _one_decimal(value):
    """Round half up, as readers do; float formatting rounds 96.25 down to 96.2."""
    from decimal import Decimal, ROUND_HALF_UP
    # Snap float noise first so an exact half such as 51.2499999999 rounds like 51.25.
    return str(Decimal(repr(round(float(value), 9))).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _pct(value):
    return f"{_one_decimal(value)}%" if _percentage(value) else "Unavailable"


def _count(value):
    return f"{value:,}" if isinstance(value, int) and value >= 0 else "Unavailable"


def plural(count, word, plural_word=None):
    """A count with a noun that agrees with it: '1 pair', '2 pairs'."""
    noun = word if count == 1 else (plural_word or word + "s")
    return f"{_count(count)} {noun}"


def _and_list(items):
    """'A', 'A and B', 'A, B and C'."""
    items = list(items)
    return " and ".join(items) if len(items) <= 2 else ", ".join(items[:-1]) + " and " + items[-1]


def _judge_label(judge):
    """A judge's display name; an unknown judge keeps its id."""
    return JUDGE_NAMES.get(judge, str(judge))


def _scroll_box(label, table, *, style="", extra_class=""):
    """A focusable horizontal scroller. Script reveals the hint only when the table overflows."""
    style_attr = f' style="{style}"' if style else ""
    classes = "table-scroll" + (f" {extra_class}" if extra_class else "")
    return ('<p class="scroll-hint" aria-hidden="true" hidden>Scroll sideways to see every column.</p>'
            f'<div class="{classes}"{style_attr} role="region" aria-label="{_text(label)}" tabindex="0">'
            f'{table}</div>')


def _ready(report):
    coverage = report.get("coverage", {})
    expected = coverage.get("expected_jobs")
    declined = coverage.get("declined_jobs") or 0
    return (report.get("status") == "complete" and isinstance(expected, int) and expected > 0
            and coverage.get("completed_jobs") == expected - declined
            and coverage.get("usable_jobs") == expected - declined)


def _declined_pairs(report):
    """Pair id -> judges that declined both orders of that pair."""
    pairs = defaultdict(set)
    for row in report.get("declined") or []:
        pairs[row.get("pair_id")].add(row.get("judge"))
    return pairs


def _refusal_statement(report):
    """The page's one full account of refused pairs: who refused, how those pairs are scored, and the cost."""
    rows = report.get("declined") or []
    if not rows:
        return ""
    by_judge = defaultdict(set)
    for row in rows:
        by_judge[row.get("judge")].add(row.get("pair_id"))
    sentences = [f"{_text(_judge_label(judge))} refused, on safety grounds, to judge {plural(len(pairs), 'paper pair')}."
                 for judge, pairs in sorted(by_judge.items(), key=lambda item: str(item[0]))]
    pairs = _declined_pairs(report)
    subject = "That pair is" if len(pairs) == 1 else f"Those {_count(len(pairs))} pairs are"
    if {len(absent) for absent in pairs.values()} == {1}:
        others = _judge_count(report) - 1
        whose = "the other judge’s" if others == 1 else f"the other {number_word(others)} judges’"
        sentences.append(f"{subject} scored on {whose} {plural(2 * others, 'vote')}, "
                         "and nothing is filled in for the missing votes.")
    else:
        sentences.append(f"{subject} scored on the remaining judges’ votes, and nothing is filled in for the missing votes.")
    costs = [(row.get("reason") or {}).get("cost_usd") if isinstance(row.get("reason"), dict) else None for row in rows]
    # A refused judgment can be billed more than once (a retry is a new request), so count judgments, not requests.
    refused = plural(len(rows), "refused judgment")
    if all(_number(cost) and cost >= 0 for cost in costs):
        sentences.append(f"Every request for the {refused} was billed: ${math.fsum(costs):.2f}, included in the total.")
    else:
        sentences.append(f"Requests for the {refused} are included in the total where their cost was recorded.")
    return " ".join(sentences)


def _vote_count(report):
    """'6 votes per pair', plus the smaller count for pairs a judge refused."""
    judges = _judge_count(report)
    groups = defaultdict(int)
    for absent in _declined_pairs(report).values():
        groups[tuple(sorted(absent, key=str))] += 1
    exceptions = []
    for absent, count in sorted(groups.items(), key=lambda item: [str(judge) for judge in item[0]]):
        names = _and_list(_text(_judge_label(judge)) for judge in absent)
        which = "the pair" if count == 1 else f"the {_count(count)} pairs"
        exceptions.append(f"{2 * (judges - len(absent))} for {which} {names} refused")
    return f"{plural(2 * judges, 'vote')} per pair" + (f" ({'; '.join(exceptions)})" if exceptions else "")


def _agent_order(report):
    order = list(report.get("agents", {}))
    if _ready(report):
        rows = {row["agent"]: row for row in report.get("rankings", [])}
        order.sort(key=lambda agent: (rows.get(agent, {}).get("rank") is None,
                                      rows.get(agent, {}).get("rank") or math.inf))
    return order


def _label(report, agent):
    return SHORT_NAMES.get(agent, report.get("agents", {}).get(agent) or agent)


def _judge_count(report):
    """Analysis requires at least two judges; reports without judge settings keep the original two."""
    judges = report.get("judges")
    return len(judges) if isinstance(judges, dict) and len(judges) >= 2 else 2


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


def _rank_tied(report):
    ranks = [row.get("rank") for row in report.get("rankings", []) if row.get("rank") is not None]
    return len(ranks) != len(set(ranks))


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
             '<div class="section-heading"><h2 id="overall-heading">Overall ranking</h2>',
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
    pair_counts = {row.get("sampled_pairs", row.get("complete_pairs")) for row in report.get("comparisons", [])}
    pair_counts = {count for count in pair_counts if _number(count)}
    note = (f'A scientist’s score is its average win rate against the other {plural(opponents, "scientist")}. '
            'Each opponent counts equally' + (', even where fewer pairs were possible.' if len(pair_counts) > 1 else '.'))
    if ready and _rank_tied(report):
        note += ' Equal scores share a rank.'
    parts.append(f'<p class="chart-note">{note}</p>')
    if report.get('rubric_kind') == AUT_KIND:
        parts.append('<p class="small">Scores are preferences under this rubric, '
                     'not standardized AUT scores or latent creativity estimates.</p>')
    parts.append(_small_pool_note(report))
    parts.append(_sampling_uncertainty(report, ready))
    parts.append('</section>')
    return "".join(parts)


def _sampling_history(report):
    """One sentence on how the sample grew after earlier results, oldest step first.

    Walks the extension chain and skips judge additions: adding a judge leaves
    the sampled pairs unchanged, so it is not part of the sampling history.
    """
    steps, node, depth = [], report.get("extension"), 0
    while isinstance(node, dict) and depth < 50:
        if node.get("kind") != "judge_addition" and node.get("stage") == "post_initial_results":
            steps.append(node)
        node, depth = node.get("parent_extension"), depth + 1
    phrases = []
    for step in reversed(steps):
        if step.get("kind") == "cohort_addition":
            before, after = step.get("previous_agent_count"), step.get("current_agent_count")
            phrases.append(f"from {before} to {after} scientists"
                           if isinstance(before, int) and isinstance(after, int) else "to more scientists")
            continue
        target = step.get("target_pairs_per_matchup")
        strata = [stratum for stratum in step.get("strata") or [] if isinstance(stratum, dict)]
        starts = {stratum.get("original_pairs") for stratum in strata}
        start = starts.pop() if len(starts) == 1 else None
        if not isinstance(start, int):
            total = step.get("original_pairs")
            start = total // len(strata) if isinstance(total, int) and strata and total % len(strata) == 0 else None
        if not isinstance(target, int):
            phrases.append("to more pairs per matchup")
        else:
            phrases.append(f"from {start} to {target} pairs per matchup" if isinstance(start, int)
                           else f"to {target} pairs per matchup")
    if not phrases:
        return ""
    growth = phrases[0] if len(phrases) == 1 else "first " + ", then ".join(phrases)
    return f"We grew this comparison after seeing earlier results: {growth}. Earlier votes were kept unchanged."


def _sampling_uncertainty(report, ready):
    uncertainty = report.get("uncertainty", {})
    confidence = _confidence_label(report)
    exploratory = uncertainty.get("inference_scope") == "exploratory_fixed_size_reference"
    label = ("Sampling range" if exploratory else
             f"{confidence} sampling range" if confidence else "Sampling range (confidence unavailable)")
    history = _sampling_history(report) or ("We grew this comparison after seeing earlier results." if exploratory else "")
    note = uncertainty.get("note") or ("Treat these ranges as rough guides, not confidence intervals." if exploratory else "")
    caveat = " ".join(_text(text) for text in (history, note) if text)
    parts = ['<details id="sampling-uncertainty"><summary>How much the scores could change with other pairs</summary>',
             '<p class="small">' + ('' if exploratory else 'Only a sample of paper pairs was judged. ')
             + 'These ranges show how much each score could move if different pairs had been drawn. '
             'Overlapping ranges mean the order between those scientists is uncertain.</p>']
    if caveat:
        parts.append(f'<p class="small">{caveat}</p>')
    table = [f'<table class="range-table"><thead><tr><th scope="col">Scientist</th><th scope="col">{_text(label)}</th>'
             '</tr></thead><tbody>']
    rows = {row["agent"]: row for row in report.get("rankings", [])}
    for agent in _agent_order(report):
        interval = _interval((rows.get(agent, {}).get("intervals") or {}).get("overall")) if ready else None
        value = f"{_one_decimal(interval[0])}–{_one_decimal(interval[1])}%" if interval else "Unavailable"
        table.append(f'<tr><th scope="row">{_text(_label(report, agent))}</th><td>{value}</td></tr>')
    table.append('</tbody></table>')
    parts.append(_scroll_box("Sampling ranges", "".join(table)))
    references = [ref for ref in uncertainty.get("references") or [] if isinstance(ref, dict)]
    location = references[0].get("location") if references else None
    parts.append('<details><summary>Statistical method</summary>'
                 '<p class="small">The calculation treats each judge’s answer to every possible paper pair '
                 'as fixed and varies only which pairs were drawn.'
                 + (f' {_text(uncertainty["method"])}' if uncertainty.get("method") else '')
                 + ' Source: <a href="https://arxiv.org/abs/1309.4029">Bardenet and Maillard, '
                 'Concentration inequalities for sampling without replacement</a>'
                 + (f', {_text(location)}' if location else '') + '.</p></details></details>')
    return "".join(parts)


def _concepts(report):
    if report.get('rubric_kind') == AUT_KIND:
        definitions = {
            'Fluency': 'Expressed coverage when the same task explicitly requests multiple ideas under comparable requirements. Raw idea counts are not comparable across paper topics and do not reveal generative fluency.',
            'Flexibility': 'Meaningfully different conceptual directions and relationships that contribute to the research task; focused work need not offer unrequested alternatives.',
            'Originality': 'The central contribution and substantive relationships relative to identifiable precedents in the work’s field. Unfamiliarity alone does not establish novelty.',
        }
        parts = ['<div id="concepts" aria-labelledby="concepts-heading">'
                 '<h3 id="concepts-heading">AUT-inspired: Fluency, Flexibility, and Originality</h3>'
                 '<p class="small">This is a qualitative adaptation for existing research outputs. '
                 'The considerations guide one joint judgment and are not scored separately. '
                 'Elaboration matters when it supports the contribution, not as word count.</p>'
                 '<dl class="concept-definitions">']
        for concept, definition in definitions.items():
            parts.append(f'<div><dt>{concept}</dt><dd>{_text(definition)}</dd></div>')
        parts.append('</dl><p class="small">Conceptual foundations: '
                     '<a href="https://digitalcommons.unomaha.edu/psychfacpub/259/">'
                     'Reiter-Palmon, Forthmann, and Barbot (2019)</a>, divergent-thinking scoring choices; '
                     '<a href="https://pmc.ncbi.nlm.nih.gov/articles/PMC4001084/">'
                     'Benedek et al. (2013)</a>, subjective top-scoring and fluency–originality confounds. '
                     'These studies do not validate this adaptation for scientific papers or its judgments '
                     'against domain experts. <a href="aut-inspired-rubric.html">'
                     'AUT-inspired rubric and limits</a></p></div>')
        return ''.join(parts)
    # Current report metadata does not distinguish the selected NUS prompt text.
    historical = report.get('version') == LEGACY_PROTOCOL_VERSION
    definitions = {
        "new": (
            # The frozen v1 rubric asks how specifically the judge can place the least placeable
            # building block, and assigns new combinations of familiar blocks to Surprising.
            "How hard it is to place the paper’s least familiar building block (a claim, mechanism or "
            "mapping) in earlier work. Combining familiar blocks counts toward Surprising, not New. "
            if historical else
            "What appears original in the paper’s substantive contribution relative to identifiable earlier research. "
        ) + "The judge checks this from memory, which can miss prior work.",
        "useful": "Whether the paper explains how its approach works and provides evidence for its claimed benefit.",
        "surprising": "How far the paper’s central idea departs from the obvious way to tackle its question.",
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
                 'These works motivate the three ideas; they do not test CREST’s rubric. More detail: '
                 + ('<a href="judging-method.html">the current NUS rubric (v2, not used here)</a>'
                    if historical else '<a href="judging-method.html">the NUS rubric</a>')
                 + ' and <a href="overall-creativity-judgment.html">why we ask for one overall judgment</a>.</p></div>')
    return "".join(parts)


def _profile_items(report, themes, reasons):
    """One theme per list item; counts and quotes come only from this run's saved judgments."""
    parts = []
    for theme in themes:
        rows = [reasons[key] for key in dict.fromkeys(theme.get("keys") or []) if key in reasons]
        if not rows:
            continue
        pairs = {row["pair_id"] for row in rows}
        by_judge = defaultdict(int)
        for row in rows:
            by_judge[row["judge"]] += 1
        who = ", ".join(f'<span class="judge-name">{_count(count)} from {_text(_judge_label(judge))}</span>'
                        for judge, count in sorted(by_judge.items()))
        quote = next(((q, reasons[q["key"]]) for q in theme.get("quotes") or []
                      if q.get("key") in reasons and q.get("text") and q["text"] in reasons[q["key"]]["verdict"]["reason"]), None)
        criterion = theme.get("criterion")
        tag = f'<span class="criterion">{_text(criterion)}</span> ' if criterion in {"New", "Useful", "Surprising"} else ""
        parts.append(f'<li><p>{tag}<strong>{_text(theme.get("theme"))}</strong></p><p>{_text(theme.get("explanation"))}</p>'
                     f'<p class="profile-evidence">Cited in {plural(len(rows), "judgment")} on '
                     f'{plural(len(pairs), "paper pair")}: {who}.</p>')
        if quote:
            q, row = quote
            parts.append(f'<blockquote class="profile-quote"><p>“{_text(q["text"])}”</p>'
                         f'<footer>{_text(_judge_label(row["judge"]))}</footer></blockquote>')
        parts.append('</li>')
    return "".join(parts)


def _profiles(report):
    """Strengths and weaknesses the judges' saved reasons attribute to each scientist's papers."""
    profiles = report.get("creativity_profiles")
    if not isinstance(profiles, dict) or not profiles.get("profiles"):
        return ""
    reasons = {row["key"]: row for row in report.get("judgments", []) if row.get("key")}
    totals = defaultdict(lambda: [0, 0])
    papers = {paper["id"]: paper.get("agent") for paper in report.get("papers", [])}
    for row in reasons.values():
        order = row.get("order") or []
        if len(order) != 2:
            continue
        winner = order[0 if row["verdict"]["winner"] == "A" else 1]
        for identity in order:
            agent = papers.get(identity)
            totals[agent][1] += 1
            totals[agent][0] += int(identity == winner)
    parts = ['<section id="profiles" aria-labelledby="profiles-heading"><h2 id="profiles-heading">'
             'Strengths and weaknesses in the judges’ reasons</h2>',
             f'<p class="small">{_text(profiles.get("method", ""))}</p>']
    for agent in _agent_order(report):
        profile = profiles["profiles"].get(agent)
        if not isinstance(profile, dict):
            continue
        won, total = totals.get(agent, [0, 0])
        sides = {side: [theme for theme in profile.get(side) or []
                        if any(key in reasons for key in theme.get("keys") or [])]
                 for side in ("strengths", "weaknesses")}
        titles = "".join(f'<p class="profile-titles"><strong>{label}:</strong> '
                         f'{_text("; ".join(theme.get("theme", "") for theme in sides[side]))}.</p>'
                         for side, label in (("strengths", "Strengths"), ("weaknesses", "Weaknesses")) if sides[side])
        # The overview stays visible; only the evidence is behind a short, plainly named toggle.
        parts.append(f'<article class="profile" data-agent="{_text(agent)}">'
                     f'<h3>{_text(_label(report, agent))}</h3>'
                     f'<p class="profile-record">Preferred in {_count(won)} of {plural(total, "judgment")}.</p>'
                     f'<p class="profile-overall">{_text(profile.get("overall", ""))}</p>{titles}'
                     '<details class="profile-evidence-toggle"><summary>Evidence and quotes'
                     f'<span class="sr-only"> for {_text(_label(report, agent))}</span></summary><div class="profile-columns">'
                     '<div><h4>Strengths</h4><ul class="profile-list">'
                     + _profile_items(report, sides["strengths"], reasons) +
                     '</ul></div><div><h4>Weaknesses</h4><ul class="profile-list">'
                     + _profile_items(report, sides["weaknesses"], reasons) +
                     '</ul></div></div></details></article>')
    parts.append('</section>')
    return "".join(parts)


def _matchups(report, ready):
    order = _agent_order(report)
    comparisons = {}
    for row in report.get("comparisons", []):
        pair = row.get("agents", [])
        if len(pair) == 2:
            comparisons[tuple(pair)] = row
    parts = ['<section id="matchups" aria-labelledby="matchups-heading">'
             '<h2 id="matchups-heading">Head-to-head results</h2>',
             '<p class="small">Read across a row. Each cell is the row scientist’s average pair score against '
             'the column scientist. A pair’s score is the share of its votes that went to the row scientist’s '
             'paper, so each pair counts once however many votes it has.</p>']
    parts.append('<div class="heatmap-legend" aria-label="Heatmap color scale">'
                 '<span><i class="lower-key" aria-hidden="true"></i>Lower row preference</span>'
                 '<span>50% = even split</span>'
                 '<span><i class="higher-key" aria-hidden="true"></i>Higher row preference</span></div>')
    if not ready:
        parts.append('<p class="small">Incomplete run: available cells describe completed paper pairs only; '
                     'they do not establish an overall rank.</p>')
    table = ['<table class="heatmap"><thead><tr><th scope="col">Row vs. column</th>']
    for agent in order:
        table.append(f'<th scope="col">{_text(_label(report, agent))}</th>')
    table.append('</tr></thead><tbody>')
    for agent in order:
        table.append(f'<tr data-agent="{_text(agent)}"><th scope="row">{_text(_label(report, agent))}</th>')
        for opponent in order:
            if agent == opponent:
                table.append('<td class="diagonal" aria-label="Same scientist">—</td>')
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
                table.append('<td class="no-cell">Unavailable</td>')
                continue
            # Fixed diverging domain, with a printed number so color is supplementary.
            hue = "11,89,103" if score >= 50 else "180,101,43"
            alpha = 0.06 + abs(score - 50) / 50 * 0.22
            count, population = row.get("complete_pairs"), row.get("population_pairs")
            census = " (all possible)" if _number(count) and count > 0 and count == population else ""
            table.append(f'<td style="background:rgba({hue},{alpha:.3f})">'
                         f'<strong>{_pct(score)}</strong><small>{plural(count, "pair")}{census}</small></td>')
        table.append('</tr>')
    table.append('</tbody></table>')
    parts.append(_scroll_box("Pairwise win percentage matrix", "".join(table),
                             style=f"--heatmap-min-width:{max(650, 135 * (len(order) + 1))}px"))
    parts.append('</section>')
    return "".join(parts)


def _small_pool_note(report):
    notes, sizes = [], []
    per_agent = report.get("coverage", {}).get("per_agent", {})
    for agent in _agent_order(report):
        eligible = per_agent.get(agent, {}).get("eligible")
        if isinstance(eligible, int) and 0 < eligible <= 3:
            notes.append(f'{_text(_label(report, agent))} has {plural(eligible, "eligible paper")}')
            sizes.append(eligible)
    if not notes:
        return ""
    label = "Small released pool" if len(notes) == 1 else "Small released pools"
    reuse = ("Its score rests on this one paper." if sizes == [1] else
             "Its score rests on these few papers, each reused in many pairs." if len(sizes) == 1 else
             "Their scores rest on these few papers, each reused in many pairs.")
    return f'<p class="notice compact"><strong>{label}:</strong> ' + "; ".join(notes) + f'. {reuse}</p>'


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
    blame = next((paper for paper in report.get("catalog", [])
                  if paper.get("eligible_primary") is False
                  and str(paper.get("title", "")).startswith("Diffusing Blame")), None)
    downloaded, eligible_total = coverage.get("downloaded_papers"), coverage.get("eligible_papers")
    selected_total = _count(coverage.get("selected_papers"))
    excluded_total = (downloaded - eligible_total if isinstance(downloaded, int) and isinstance(eligible_total, int)
                      and downloaded >= eligible_total else None)
    if excluded_total:
        lead = (f'We downloaded {plural(downloaded, "released paper")}. We excluded {_count(excluded_total)}'
                f'{" (see below)" if blame else ""}, which leaves {plural(eligible_total, "eligible paper")}, '
                f'and the sampled pairs use {selected_total} of them.')
    elif excluded_total == 0:
        lead = (f'We downloaded {plural(downloaded, "released paper")}, all eligible, '
                f'and the sampled pairs use {selected_total} of them.')
    else:
        lead = f'The sampled pairs use {selected_total} of {plural(eligible_total, "eligible paper")}.'
    rows = []
    for agent in _agent_order(report):
        row = per_agent.get(agent, {})
        down, eligible, selected = row.get("downloaded"), row.get("eligible"), row.get("selected")
        rows.append((agent, down, eligible, selected, len(judged[agent])))
    # The judged-paper column is shown only when it says something the Selected column does not.
    show_judged = any(judged_count != selected for _, _, _, selected, judged_count in rows)
    table = ['<table class="coverage-table"><thead><tr><th scope="col">Scientist</th>'
             '<th scope="col">Downloaded</th>'
             '<th scope="col">Eligible</th><th scope="col">Selected</th>'
             '<th scope="col">Sample share</th>'
             + ('<th scope="col">With a judgment</th>' if show_judged else '') + '</tr></thead><tbody>']
    for agent, down, eligible, selected, count in rows:
        share = 100 * selected / eligible if _number(selected) and _number(eligible) and eligible > 0 else None
        excluded = down - eligible if _number(down) and _number(eligible) and down >= eligible else None
        excluded_note = f'<small>({_count(excluded)} excluded)</small>' if excluded else ""
        table.append(f'<tr data-downloaded="{_text(down)}" data-selected="{_text(selected)}" '
                     f'data-judged="{count}"><th scope="row">{_text(_label(report, agent))}</th>'
                     f'<td>{_count(down)}</td><td>{_count(eligible)}{excluded_note}</td>'
                     f'<td>{_count(selected)}</td><td>{_pct(share)}</td>'
                     + (f'<td>{count}</td>' if show_judged else '') + '</tr>')
    table.append('</tbody></table>')
    parts = ['<section id="coverage" aria-labelledby="coverage-heading"><h2 id="coverage-heading">'
             'Paper coverage</h2>',
             f'<p class="small">{lead} Sample share is selected papers divided by eligible papers.</p>',
             _scroll_box("Paper coverage by scientist", "".join(table))]
    if blame:
        owner = _label(report, blame.get("agent")) if blame.get("agent") else None
        parts.append(f'<p class="small">We excluded one {_text(owner) + " " if owner else ""}paper, Diffusing Blame, '
                     'because <a href="https://pub.sakana.ai/agentic-scientist/">Sakana says</a> '
                     'humans substantially guided and revised it.</p>')
    parts.append('</section>')
    return "".join(parts)


def _per_judge(report):
    summaries = report.get("diagnostics", {}).get("per_judge", {})
    if not summaries:
        return ""
    judges = list(summaries)
    table = ['<table class="judge-comparison"><thead><tr><th scope="col">Scientist</th>']
    for judge in judges:
        table.append(f'<th scope="col">{_text(_judge_label(judge))}</th>')
    table.append('</tr></thead><tbody>')
    for agent in _agent_order(report):
        table.append(f'<tr data-agent="{_text(agent)}"><th scope="row">{_text(_label(report, agent))}</th>')
        for judge in judges:
            summary = summaries[judge].get(agent, {})
            table.append(f'<td><strong>{_pct(summary.get("overall_pct"))}</strong></td>')
        table.append('</tr>')
    table.append('</tbody></table>')
    return ('<h3>Ranking by each judge</h3>'
            '<p class="small">This table repeats the ranking using one judge’s votes at a time.</p>'
            + _scroll_box("Win percentages by judge and scientist", "".join(table),
                          style=f"--judge-min-width:{max(460, 180 + 130 * len(judges))}px"))


def _judge_pairs(report):
    """With more than two judges, show which judge pairs agree."""
    pairs = report.get("diagnostics", {}).get("judge_pair_disagreement")
    if _judge_count(report) <= 2 or not isinstance(pairs, dict) or not pairs:
        return ""
    overall = report.get("diagnostics", {}).get("judge_disagreement_pct")
    pooled = f"The {_pct(overall)} above" if _percentage(overall) else "The disagreement rate above"
    table = ['<table class="judge-pairs"><thead><tr><th scope="col">Judge pair</th>'
             '<th scope="col">Disagreement</th><th scope="col">Matched comparisons</th></tr></thead><tbody>']
    for key, row in pairs.items():
        names = row.get("judges") if isinstance(row.get("judges"), list) else str(key).split("|")
        # Each name stays on one line, so a narrow cell wraps only at "vs.".
        label = " vs. ".join('<span class="judge-name">' + _text(_judge_label(name)) + '</span>' for name in names)
        table.append(f'<tr data-judges="{_text(key)}"><th scope="row">{label}</th>'
                     f'<td><strong>{_pct(row.get("disagreement_pct"))}</strong></td>'
                     f'<td>{_count(row.get("denominator"))}</td></tr>')
    table.append('</tbody></table>')
    return ('<h3>Disagreement by judge pair</h3>'
            f'<p class="small">{pooled} combines all {number_word(len(pairs))} pairs of judges. '
            'This table splits it by pair.</p>'
            + _scroll_box("Disagreement by judge pair", "".join(table)))


def _judges(report):
    diagnostics = report.get("diagnostics", {})
    denominators = diagnostics.get("denominators") or {}
    checks = (
        ("judge_disagreement_pct", "Two judges disagree", "judge_disagreement",
         "same-pair, same-order comparisons", ""),
        ("swapped_inconsistency_pct", "Same judge flips when the order is swapped", "swapped_inconsistency",
         "cases where a judge read a pair in both orders", ""),
        ("position_a_pct", "First-shown paper chosen", "position_a", "votes", " 50% means no position bias."),
    )
    parts = ['<section id="judges" aria-labelledby="judges-heading"><h2 id="judges-heading">'
             'Do the judges agree?</h2>', _per_judge(report),
             '<h3>Consistency checks</h3><dl class="diagnostics">']
    for key, label, denominator_key, unit, gloss in checks:
        parts.append(f'<div><dt>{label}</dt><dd>{_pct(diagnostics.get(key))}</dd>'
                     f'<small>Across {_count(denominators.get(denominator_key))} {unit}.{gloss}</small></div>')
    parts.append('</dl>')
    parts.append(_judge_pairs(report))
    parts.append('<p class="small">Agreement among judges does not show that they are right.</p></section>')
    return "".join(parts)


def _judge_settings(report):
    """One line naming each judge with its model id and reasoning setting; no operational limits."""
    items = []
    for judge, settings in (report.get("judges") or {}).items():
        settings = settings if isinstance(settings, dict) else {}
        details = [f'<code>{_text(settings["model"])}</code>'] if settings.get("model") else []
        details += [f'{label} {_text(settings[key])}' for key, label in JUDGE_EFFORT_KEYS
                    if settings.get(key) not in (None, "")]
        items.append(_text(_judge_label(judge)) + (f' ({", ".join(details)})' if details else ''))
    if not items:
        return ""
    return f'Judges: {_and_list(items)}. See <a href="judge-models.html">judge models</a>.'


def _progress(report):
    coverage, costs = report.get("coverage", {}), report.get("costs", {})
    known = costs.get("known_usd")
    prior_known = costs.get("prior_excluded_known_usd")
    money = f"${known:.2f}" if _number(known) and known >= 0 else "Unavailable"
    parts = ['<section id="progress" aria-labelledby="progress-heading"><h2 id="progress-heading">'
             'Run summary and cost</h2>'
             '<div class="run-stats">',
             f'<div><strong>{_count(coverage.get("completed_jobs"))} / {_count(coverage.get("expected_jobs"))}</strong>'
             '<span>judgments saved / planned</span></div>',
             f'<div><strong>{_count(coverage.get("complete_pairs"))} / {_count(coverage.get("expected_pairs"))}</strong>'
             '<span>completed paper pairs / planned</span></div>',
             f'<div><strong>{money}</strong><span>estimated judging cost</span></div></div>',
             '<p class="small">Cost is estimated from recorded usage at published rates.</p>']
    refusal = _refusal_statement(report)
    if refusal:
        parts.append(f'<p class="small">{refusal}</p>')
    if costs.get("unknown_jobs"):
        parts.append(f'<p class="small">Cost estimates are pending for {plural(costs["unknown_jobs"], "request")}.</p>')
    if "prior_excluded_jobs" in costs or "prior_excluded_known_usd" in costs:
        prior_money = f"${prior_known:.2f}" if _number(prior_known) and prior_known >= 0 else "an unknown amount"
        parts.append(f'<p class="small">The total also includes {prior_money} for '
                     f'{plural(costs.get("prior_excluded_jobs"), "discarded request")} from earlier runs. '
                     'They add no votes.</p>')
    settings = _judge_settings(report)
    if settings:
        parts.append(f'<p class="small judge-settings" id="run-audit">{settings}</p>')
    parts.append('</section>')
    return "".join(parts)


def _paper_notes(paper):
    """Short reader notes, rendered only when the paper record carries the field."""
    notes = []
    placeholders = [issue for issue in paper.get("observed_artifact_issues") or []
                    if isinstance(issue, dict) and issue.get("type") == "released_manuscript_template_placeholder"]
    if placeholders:
        example = placeholders[0].get("text")
        notes.append("The released PDF contains unfilled template text"
                     + (f", such as “{example}”." if isinstance(example, str) and example.strip() else "."))
    setup = paper.get("human_setup_notes")
    if isinstance(setup, str) and setup.strip():
        setup = setup.strip()
        notes.append(f"Human setup: {setup}" + ("" if setup.endswith(".") else "."))
    return notes


def _papers(report, data_root, destination):
    agents = report.get("agents", {})
    groups = defaultdict(list)
    for paper in report.get("papers", []):
        groups[paper.get("agent")].append(paper)
    total = sum(len(group) for group in groups.values())
    parts = ['<section id="papers" aria-labelledby="papers-heading"><h2 id="papers-heading">'
             f'Read the selected papers</h2><p class="small">These are the {plural(total, "sampled paper")}, '
             'with links to each full PDF and to its original release.</p>']
    if not groups:
        parts.append('<p>No papers selected.</p>')
    order = _agent_order(report) + [agent for agent in groups if agent not in agents]
    for agent in order:
        group = groups.get(agent)
        if not group:
            continue
        name = _label(report, agent)
        table = ['<table class="papers-table"><thead><tr><th scope="col">Paper</th>'
                 '<th scope="col">Topic / pages</th><th scope="col">Read</th></tr></thead><tbody>']
        for paper in group:
            title = paper.get("title", paper.get("id"))
            notes = "".join(f'<small class="paper-note">{_text(note)}</small>' for note in _paper_notes(paper))
            seed = paper.get("seed")
            run = f" · run {_text(seed)}" if seed is not None and seed != "" else ""
            pages = paper.get("pages")
            page_text = plural(pages, "page") if isinstance(pages, int) and pages >= 0 else "Page count unavailable"
            table.append(f'<tr><th scope="row">{_text(title)}{notes}</th>'
                         f'<td>{_text(paper.get("topic"))}{run}<small>{page_text}</small></td><td class="paper-links">')
            pdf = _pdf_link(paper, data_root, destination)
            if pdf:
                table.append(f'<a href="{_text(pdf)}">Full PDF<span class="sr-only">: {_text(title)}</span></a>')
            source = _web_link(paper.get("source_url"))
            if source:
                table.append(f'<a href="{_text(source)}">Original source<span class="sr-only">: {_text(title)}</span></a>')
            if not pdf and not source:
                table.append('Unavailable')
            table.append('</td></tr>')
        table.append('</tbody></table>')
        parts.append(f'<details class="paper-group" data-agent="{_text(agent)}"><summary>{_text(name)} '
                     f'<span class="muted">· {plural(len(group), "selected paper")}</span></summary>'
                     + _scroll_box(f"Selected papers: {name}", "".join(table)) + '</details>')
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
        # Identifiers stay in attributes for auditing; readers see the judge's name.
        model_attr = f' data-model="{_text(model)}"' if model else ""
        parts.append(f'<article class="judgment" data-key="{_text(judgment.get("key"))}" '
                     f'data-judge="{_text(judgment.get("judge"))}"{model_attr}>'
                     f'<h3>{_text(_judge_label(judgment.get("judge")))}</h3>')
        for label, paper_id in zip(("A", "B"), order):
            paper = papers.get(paper_id, {})
            parts.append(f'<p class="answer-map"><strong>{label}: {_text(paper.get("title", paper_id))}</strong>'
                         f' <span class="muted">· {_text(_label(report, paper.get("agent")))}</span></p>')
        verdict = judgment["verdict"]
        index = {"A": 0, "B": 1}[verdict["winner"]]
        winning_id = order[index] if len(order) > index else None
        preferred = papers.get(winning_id, {}).get("title", winning_id)
        parts.append(f'<div class="overall-reason"><p><strong>Preferred: {_text(preferred)}</strong></p>'
                     f'<p>{_text(verdict["reason"])}</p></div></article>')
    return "".join(parts)


def _judgments(report, data_root, destination):
    papers = {paper["id"]: paper for paper in report.get("papers", [])}
    groups = defaultdict(list)
    for judgment in report.get("judgments", []):
        groups[judgment.get("pair_id", judgment.get("key"))].append(judgment)
    judge_count = _judge_count(report)
    votes_per_pair = 2 * judge_count
    half = votes_per_pair // 2
    declined = _declined_pairs(report)
    parts = ['<section id="reasons" aria-labelledby="reasons-heading"><h2 id="reasons-heading">'
             'Inspect the judgments</h2><p class="small">Each row is one paper pair. The outcome is the majority '
             f'pick and the vote split; a {half}–{half} split is a tie. Scores use the split itself, so a '
             f'{votes_per_pair - 1}–1 pair counts as {100 * (votes_per_pair - 1) / votes_per_pair:.0f}% for the winner. '
             'Expand a row to read each judge’s reason.</p>']
    refusers = sorted({judge for absent in declined.values() for judge in absent}, key=str)
    if len(refusers) == 1 and all(len(absent) == 1 for absent in declined.values()):
        parts.append(f'<p class="small">Rows marked “{_text(_judge_label(refusers[0]))} refused” have '
                     f'{2 * (judge_count - 1)} votes instead of {votes_per_pair}.</p>')
    elif refusers:
        parts.append(f'<p class="small">Rows that name a refusing judge have fewer than {votes_per_pair} votes.</p>')
    if not groups:
        parts.append('<p>No judgments yet. No reasons or preferences are available.</p>')
        return "".join(parts) + '</section>'

    agent_positions = {agent: index for index, agent in enumerate(_agent_order(report))}
    rows = []
    for pair_id, group in groups.items():
        group.sort(key=lambda judgment: (str(judgment.get("judge")),
                                         judgment.get("order") != judgment.get("papers")))
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
        absent = declined.get(pair_id, set())
        expected_cells = {(judge, order) for judge in report.get("judges", {}) if judge not in absent
                          for order in valid_orders}
        expected_votes = len(expected_cells)
        complete = len(group) == len(keys) == expected_votes and cells == expected_cells
        winner = None
        outcome = "partial"
        if complete:
            left, right = (votes[identity] for identity in paper_ids)
            outcome = "tie" if left == right else "winner"
            winner = paper_ids[0] if left > right else paper_ids[1] if right > left else None
        matchup = tuple(papers.get(identity, {}).get("agent") for identity in paper_ids)
        rows.append({"id": pair_id, "papers": paper_ids, "group": group, "matchup": matchup,
                     "votes": votes, "winner": winner, "outcome": outcome,
                     "declined": sorted(absent), "expected_votes": expected_votes})
    rows.sort(key=lambda row: tuple(agent_positions.get(agent, math.inf) for agent in row["matchup"]))
    matchups = list(dict.fromkeys(row["matchup"] for row in rows))
    matchup_ids = {matchup: f"matchup-{index}" for index, matchup in enumerate(matchups)}
    completed = sum(row["outcome"] != "partial" for row in rows)
    ties = sum(row["outcome"] == "tie" for row in rows)
    column_note = ("Paper 1 is from the higher-ranked scientist, and vote splits read Paper 1–Paper 2. "
                   if _ready(report) else "Vote splits read Paper 1–Paper 2. ")
    column_note += ("In each reason, A and B mean the order that judge saw, "
                    "which may differ from Paper 1 and Paper 2.")
    parts.append(f'<p class="small" id="judgment-columns">{column_note}</p>'
                 '<div class="judgment-tools"><label for="judgment-matchup">Scientist matchup</label>'
                 '<select id="judgment-matchup" aria-controls="judgment-pair-table" disabled>'
                 f'<option value="all">All matchups · {len(rows)} paper pairs</option>')
    for matchup in matchups:
        label = " vs. ".join(str(_label(report, agent)) for agent in matchup)
        count = sum(row["matchup"] == matchup for row in rows)
        parts.append(f'<option value="{matchup_ids[matchup]}">{_text(label)} · {plural(count, "pair")}</option>')
    parts.append('</select>'
                 f'<span id="judgment-count" role="status" aria-live="polite">{len(rows)} paper pairs · '
                 f'{completed} complete · {ties} tied</span></div>')
    table = ['<table class="judgment-pairs" id="judgment-pair-table" aria-describedby="judgment-columns">'
             '<thead><tr><th scope="col">Paper 1</th><th scope="col">Paper 2</th>'
             '<th scope="col">Recorded outcome</th></tr></thead>']
    for index, row in enumerate(rows, start=1):
        left_id, right_id = row["papers"]
        votes = row["votes"]
        winner_attr = f' data-winner="{_text(row["winner"])}"' if row["winner"] is not None else ""
        table.append(f'<tbody class="judgment-pair" data-pair-id="{_text(row["id"])}" '
                     f'data-matchup="{matchup_ids[row["matchup"]]}" data-outcome="{row["outcome"]}" '
                     f'data-votes-left="{votes[left_id]}" data-votes-right="{votes[right_id]}"{winner_attr}'
                     f'{" data-declined=" + chr(34) + _text(" ".join(row["declined"])) + chr(34) if row["declined"] else ""}><tr>')
        for position, paper_id in enumerate(row["papers"], start=1):
            paper = papers.get(paper_id, {})
            tag = 'th scope="row"' if position == 1 else "td"
            close_tag = "th" if position == 1 else "td"
            table.append(f'<{tag} class="pair-paper">')
            title = paper.get("title", paper_id)
            pdf = _pdf_link(paper, data_root, destination)
            if pdf:
                table.append(f'<a class="pair-title" href="{_text(pdf)}" '
                             f'aria-label="Read full PDF: {_text(title)}">{_text(title)}</a>')
            else:
                table.append(f'<span class="pair-title">{_text(title)}</span>')
            table.append(f'<small>{_text(_label(report, paper.get("agent")))}'
                         f'{ " · PDF" if pdf else ""}</small></{close_tag}>')
        split = f'{votes[left_id]}–{votes[right_id]} votes'
        table.append('<td class="pair-outcome">')
        if row["outcome"] == "partial":
            table.append(f'<strong>Partial: {len(row["group"])} / {plural(row["expected_votes"], "judgment")}</strong>'
                         f'<span>Recorded split: {split}</span><small>No final pair result</small>')
        elif row["outcome"] == "tie":
            table.append(f'<strong>Tie</strong><span>{split}</span>')
        else:
            slot = 1 if row["winner"] == left_id else 2
            preferred = _label(report, papers[row["winner"]].get("agent"))
            table.append(f'<strong>{_text(preferred)} preferred</strong><span>{split}</span>'
                         f'<small>Paper {slot}</small>')
        if row["declined"]:
            names = _and_list(_text(_judge_label(judge)) for judge in row["declined"])
            table.append(f'<small class="declined-note">{names} refused this pair</small>')
        table.append('</td></tr><tr><td colspan="3" class="pair-reason-cell">'
                     f'<details class="pair-reasons" id="pair-reasons-{index}">'
                     f'<summary>Read {plural(len(row["group"]), "saved judgment")}'
                     f'<span class="sr-only"> for pair {index}</span></summary>')
        table.append(_judgment_reasons(report, row["group"], papers))
        table.append('</details></td></tr></tbody>')
    table.append('</table>')
    parts.append(_scroll_box("Paper-pair outcomes and expandable judgments", "".join(table),
                             extra_class="judgment-table-scroll"))
    parts.append('</section>')
    return "".join(parts)


def _sampling_plan(report):
    """The frozen sampling plan in one line: seed, pairs per matchup, all-pairs matchups, total."""
    selection = report.get("selection") or {}
    seed, per = selection.get("seed"), selection.get("pairs_per_matchup")
    total = selection.get("sampled_pairs", report.get("coverage", {}).get("expected_pairs"))
    positions = {agent: index for index, agent in enumerate(_agent_order(report))}
    census = []
    for row in report.get("comparisons", []):
        population, pair = row.get("population_pairs"), row.get("agents") or []
        if isinstance(per, int) and isinstance(population, int) and 0 < population < per and len(pair) == 2:
            names = " vs. ".join(_text(_label(report, agent))
                                 for agent in sorted(pair, key=lambda agent: positions.get(agent, math.inf)))
            census.append((population, names))
    pieces = [f"random seed {_text(seed)}"] if seed is not None else []
    if isinstance(per, int) and per > 0:
        text = f"{plural(per, 'pair')} per matchup"
        if len(census) == 1:
            text += f", or all {census[0][0]} possible pairs for {census[0][1]}"
        elif census:
            text += ", or all possible pairs for " + ", ".join(f"{names} ({population})" for population, names in census)
        pieces.append(text)
    if isinstance(total, int) and total >= 0:
        pieces.append(f"{plural(total, 'pair')} in all")
    return f'<p class="small">Sampling plan: {"; ".join(pieces)}.</p>' if pieces else ""


def _method(report):
    historical = (report.get('version') == LEGACY_PROTOCOL_VERSION
                  and report.get('rubric_kind', NUS_KIND) == NUS_KIND)
    saved_rubric = (
        '<p class="small">The judges used version 1 of the New, Useful, Surprising (NUS) rubric. '
        'CREST now defaults to version 2, which was not used here.</p>' if historical else ''
    )
    per_matchup = (report.get("selection") or {}).get("pairs_per_matchup")
    draw = (f'For every two scientists, we drew up to {_count(per_matchup)} pairs of their papers at random, '
            f'or all pairs when fewer than {_count(per_matchup)} exist.'
            if isinstance(per_matchup, int) and per_matchup > 0 else
            'For every two scientists, we drew pairs of their papers at random.')
    opponents = max(0, len(report.get("agents", {})) - 1)
    parts = ['<section id="method" aria-labelledby="method-heading"><h2 id="method-heading">'
             f'How the comparison works</h2><p>{draw} Each judge read every pair twice, once in each order, '
             f'and picked the more creative paper. That gives {_vote_count(report)}. For each scientist, a pair’s '
             'score is the share of votes its paper won. A matchup averages its pairs, and a scientist’s score '
             f'averages its {plural(opponents, "matchup")}.</p>',
             _sampling_plan(report), saved_rubric, _concepts(report),
             '<p class="small">Full method: <a href="ai-scientist-method.html">Paper comparison method</a>.</p>'
             '</section>']
    return "".join(parts)


LIMITATION_DEFAULTS = (
    "Judges read text extracted from each PDF. They did not see figure images, extraction can drop "
    "equations or tables, and nobody checked the experiments.",
    "The sampling ranges cover only which pairs were drawn. They do not cover judge error, rerun noise, "
    "model updates, or whether the rubric captures creativity.",
    "The results describe these released papers only. Future papers from the same systems could rank differently.",
)


def _limits(report):
    """Every caveat in one list, worded by the analysis; older reports fall back to the defaults."""
    limits = [line for line in report.get("limitations") or [] if isinstance(line, str) and line.strip()]
    items = "".join(f"<li>{_text(line)}</li>" for line in limits or LIMITATION_DEFAULTS)
    return ('<section id="limits" aria-labelledby="limits-heading"><h2 id="limits-heading">'
            f'What this comparison leaves uncertain</h2><ul class="key-limits">{items}</ul></section>')


CSS = """
:root{--ink:#172c3e;--muted:#526574;--accent:#0b5967;--line:#d7e1e6;--wash:#f5f8f9;--paper:#fff}
*{box-sizing:border-box}html{scroll-padding-top:1.2rem}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
a{color:var(--accent);text-underline-offset:3px;overflow-wrap:anywhere}a:hover{text-decoration-thickness:2px}:focus-visible{outline:3px solid #b45a13;outline-offset:4px}
main{max-width:1160px;margin:auto;padding:2.8rem clamp(1.1rem,4vw,3rem) 4rem}
h1{font-size:clamp(2rem,5vw,3.65rem);line-height:1.08;letter-spacing:-.045em;max-width:21ch;margin:.8rem 0 1rem;font-weight:750}
nav{display:flex;flex-wrap:wrap;gap:.35rem 1.25rem;padding:1rem 0;font-size:.82rem}nav a{text-decoration:none}
section{margin:2.2rem 0 0;padding-top:1.5rem;border-top:1px solid var(--line)}#overall{border-top:0;margin-top:1rem}h2{font-size:1.55rem;line-height:1.25;letter-spacing:-.025em;margin:0 0 1rem}h3{font-size:1rem;margin:.6rem 0}p{margin:.7rem 0 1rem}.section-heading{display:flex;align-items:baseline;justify-content:space-between;gap:1rem;flex-wrap:wrap}.unit,.small,.chart-note{color:var(--muted);font-size:.83rem}.chart-note{max-width:90ch;margin-top:1.1rem}.unit{font-size:.75rem}.notice{border-left:3px solid #997024;background:#fbf6e9;padding:.85rem 1rem;margin:1rem 0;font-size:.9rem}.notice p{margin:.25rem 0 0}.notice.compact{font-size:.85rem}
.overall-chart{margin-top:1.4rem}.overall-row{display:grid;grid-template-columns:minmax(170px,1.3fr) minmax(100px,2.1fr) minmax(105px,.65fr);gap:1.3rem;align-items:center;padding:.75rem 0}.agent-label{display:flex;align-items:center;gap:.8rem;font-size:.95rem;line-height:1.4}.rank{font-size:.85rem;font-weight:600;color:var(--muted);min-width:1ch}.bar{display:block;width:100%;height:34px}.score{text-align:right;line-height:1.35}.score>strong{font-size:1.4rem;font-variant-numeric:tabular-nums;letter-spacing:-.03em}.score small{display:block;font-size:.7rem;color:var(--muted);margin-top:.25rem}.score.unavailable-score>strong{font-size:.85rem;font-weight:500;color:var(--muted)}.chart-axis{display:flex;justify-content:space-between;margin:0 calc((100% - 2.6rem)*.65/4.05 + 1.3rem) 0 calc((100% - 2.6rem)*1.3/4.05 + 1.3rem);font-size:.7rem;color:var(--muted)}.unavailable{color:var(--muted);font-size:.8rem}
.profile{margin:1.2rem 0 0;padding:1.1rem 1.2rem;border:1px solid var(--line);border-radius:6px}.profile h3{color:var(--accent)}.profile-evidence-toggle{margin-top:.4rem}.profile-evidence-toggle>summary{padding:.5rem 0}.profile>summary::-webkit-details-marker{display:none}.profile h3{font-size:1.15rem;margin:0}.profile-record{color:var(--muted);font-size:.82rem;margin:.2rem 0 .5rem}.profile-overall{margin:0 0 .5rem}.profile-titles{font-size:.88rem;margin:.15rem 0}.profile .judge-name{white-space:nowrap}.profile-columns{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1.4rem}.profile h4{font-size:.85rem;text-transform:uppercase;letter-spacing:.06em;color:var(--accent);margin:.4rem 0}.profile-list{margin:0;padding-left:1.1rem}.profile-list li{margin:.6rem 0 1rem}.profile-list p{margin:.2rem 0}.profile-evidence{font-size:.78rem;color:var(--muted)}.criterion{display:inline-block;margin-left:.45rem;padding:0 .4rem;border:1px solid var(--line);border-radius:3px;font-size:.72rem;color:var(--muted);vertical-align:1px}.profile-quote{margin:.4rem 0 0;padding:.1rem 0 .1rem .8rem;border-left:3px solid var(--line);font-size:.82rem;color:#33495a;max-width:75ch}.profile-quote p{margin:0}.profile-quote footer{font-size:.75rem;color:var(--muted);margin-top:.15rem;padding-top:0}
@media(max-width:720px){.profile{padding:.9rem}.profile-columns{grid-template-columns:1fr;gap:.4rem}}
.concept-definitions{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1.5rem;margin:1rem 0}.concept-definitions dt{font-size:1rem;font-weight:650;color:var(--accent)}.concept-definitions dd{font-size:.83rem;line-height:1.6;color:var(--muted);margin:.4rem 0 0}
.table-scroll{position:relative;overflow:auto;max-width:100%;margin:1rem 0}table{border-collapse:collapse;width:100%;text-align:left;font-size:.82rem;line-height:1.5}th,td{padding:.7rem .8rem;border-bottom:1px solid var(--line);vertical-align:middle}thead th{background:var(--wash);font-weight:650;color:#183d49}tbody th{font-weight:550}td small,th small{display:block;color:var(--muted);font-size:.72rem;margin-top:.3rem}.heatmap{table-layout:fixed;min-width:650px}.heatmap th{font-size:.75rem}.heatmap td{text-align:center}.heatmap td strong{font-size:1.18rem;font-variant-numeric:tabular-nums;font-weight:650}.heatmap .diagonal{background:#f5f8f9;color:#8b9aa3}.no-cell{font-size:.73rem;color:var(--muted)}.coverage-table{min-width:760px}.coverage-table th:first-child{width:24%}.coverage-table th:nth-child(2){width:24%}.coverage-table td:nth-child(n+3){font-variant-numeric:tabular-nums;text-align:right}.coverage-table th:nth-child(n+3){text-align:right}
.run-stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1.5rem;padding:.65rem 0}.run-stats strong{display:block;color:var(--accent);font-size:1.7rem;letter-spacing:-.025em;font-variant-numeric:tabular-nums}.run-stats span{display:block;color:var(--muted);font-size:.75rem}.diagnostics{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem;font-size:.8rem}.diagnostics dt{color:var(--muted)}.diagnostics dd{margin:.4rem 0;font-size:1.2rem;font-weight:600}
.judge-comparison{min-width:520px}.judge-comparison th[scope="rowgroup"]{width:27%;vertical-align:top}.judge-comparison th[scope="row"]{width:27%}.judge-comparison td{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}.judge-comparison thead th:nth-child(n+3){text-align:right}
details{border-top:1px solid var(--line);border-bottom:1px solid var(--line);margin:.7rem 0}details+details{border-top:0;margin-top:-.7rem}summary{cursor:pointer;color:var(--accent);font-size:.88rem;font-weight:600;line-height:1.5;padding:.9rem .1rem}details[open]>summary{margin-bottom:.5rem}.muted{color:var(--muted);font-weight:400}pre,code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:.75rem;overflow-wrap:anywhere}pre{white-space:pre-wrap;background:var(--wash);padding:1rem;max-height:20rem;overflow:auto}.papers-table{min-width:560px}.papers-table th:first-child{width:60%}.papers-table td{vertical-align:top}.paper-links a{display:block;margin-bottom:.25rem}.paper-links{min-width:120px}.judgment{padding:.6rem .4rem 1rem;border-top:1px solid var(--line)}.judgment h3{font-size:.86rem}.answer-map{font-size:.8rem;line-height:1.5;margin:.5rem 0}.overall-reason{font-size:.85rem;overflow-wrap:anywhere}.overall-reason p{margin:.5rem 0}.judgment-pair .muted{font-size:.75rem}li{margin:.55rem 0}#method>p,#method li{font-size:.9rem;max-width:95ch}.sr-only{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(max-width:760px){main{padding-top:1.7rem}.overall-row{grid-template-columns:minmax(130px,1fr) minmax(90px,1fr);gap:.4rem 1rem;padding:.8rem 0}.overall-row .bar,.overall-row>.unavailable{grid-column:1/-1;grid-row:2}.score{grid-column:2;grid-row:1}.score>strong{font-size:1.25rem}.score small{font-size:.65rem}.agent-label{font-size:.88rem}.chart-axis{margin:0 .25rem}.section-heading{gap:.1rem}.run-stats{gap:.8rem}.run-stats strong{font-size:1.3rem}.diagnostics{grid-template-columns:1fr}h2{font-size:1.35rem}.unit{margin-bottom:.7rem}.coverage-table{min-width:720px}}
@media(max-width:430px){.run-stats{grid-template-columns:1fr;gap:1rem}.run-stats>div{display:flex;align-items:baseline;gap:.8rem}.run-stats strong{min-width:115px;font-size:1.25rem}h1{font-size:2.3rem}.overall-row{grid-template-columns:1fr 110px}.meta{font-size:.72rem}}
@media(max-width:760px){.concept-definitions{grid-template-columns:1fr;gap:.9rem}}
@media print{main{max-width:none;padding:0}body{font-size:10pt}nav,.skip-link{display:none}h1{font-size:30pt}section{break-inside:avoid}.table-scroll{overflow:visible}.heatmap,.coverage-table,.papers-table{min-width:0}table{font-size:8pt}th,td{padding:.4rem}details{border:0}details::details-content{content-visibility:visible}details>*:not(summary){display:block!important}pre{max-height:none}a{color:inherit}}

#overall{--ranking-columns:minmax(175px,1.1fr) minmax(150px,2.3fr) 90px;--ranking-gap:1rem}
.overall-row,.chart-axis{display:grid;grid-template-columns:var(--ranking-columns);gap:var(--ranking-gap)}
.chart-axis{margin:0;font-size:.72rem}.axis-ticks{grid-column:2;display:grid;grid-template-columns:1fr auto 1fr;padding:0 1%}.axis-ticks span:last-child{text-align:right}
.chart-legend{font-size:.78rem;color:var(--muted);display:flex;align-items:center;gap:.5rem;margin:.8rem 0}.dot-key{width:.5rem;height:.5rem;border-radius:50%;background:var(--ink);display:inline-block;flex-shrink:0}
.heatmap-legend{display:flex;gap:.5rem 1.2rem;flex-wrap:wrap;color:var(--muted);font-size:.75rem}.heatmap-legend>span{display:inline-flex;align-items:center;gap:.4rem}.heatmap-legend i{display:inline-block;width:.8rem;height:.65rem}.lower-key{background:rgba(180,101,43,.28)}.higher-key{background:rgba(11,89,103,.28)}
.coverage-table{min-width:650px}.coverage-table th:first-child{width:28%}.coverage-table th:nth-child(2){width:auto}.coverage-table th:nth-child(n+2),.coverage-table td{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.judge-comparison{table-layout:fixed;min-width:var(--judge-min-width,460px)}.judge-comparison thead th:first-child,.judge-comparison th[scope="row"]{width:38%}.judge-comparison thead th:nth-child(n+2){text-align:right}.diagnostics small{display:block;font-size:.75rem;color:var(--muted)}
.judge-pairs{table-layout:fixed;min-width:460px}.judge-pairs th[scope="row"],.judge-pairs thead th:first-child{width:38%}.judge-pairs td,.judge-pairs thead th:nth-child(n+2){text-align:right}.judge-pairs td{font-variant-numeric:tabular-nums;white-space:nowrap}
.key-limits{font-size:.86rem}
@media(max-width:760px){.overall-row{grid-template-columns:minmax(0,1fr) 110px;gap:.3rem 1rem}.chart-axis{grid-template-columns:minmax(0,1fr);gap:0}.axis-ticks{grid-column:1}.coverage-table{min-width:630px}.score>strong{font-size:1.25rem}.agent-label{min-width:0;overflow-wrap:anywhere}.unit{max-width:42ch}}
#method>p{max-width:none}
.heatmap{min-width:var(--heatmap-min-width,650px)}
#reasons .judgment-tools{display:flex;align-items:center;flex-wrap:wrap;gap:.6rem .9rem;margin:1.2rem 0;font-size:.8rem}
#reasons .judgment-tools label{font-weight:650}#reasons select{max-width:100%;padding:.45rem .6rem;border:1px solid #a6bac3;border-radius:3px;background:white;color:var(--ink);font:inherit}
#judgment-count{color:var(--muted);font-size:.77rem}#reasons .judgment-table-scroll{position:relative;max-height:min(48rem,70vh);overflow:auto;scrollbar-gutter:stable}
@media(hover:hover){#reasons .judgment-table-scroll{overscroll-behavior:contain}}
#reasons .judgment-pairs{table-layout:fixed;min-width:740px;font-size:.84rem}
#reasons .judgment-pairs thead th{position:sticky;top:0;z-index:2;background:#eaf1f3}#reasons .judgment-pairs thead th:nth-child(1),#reasons .judgment-pairs thead th:nth-child(2){width:39%}
#reasons .judgment-pair:nth-of-type(even){background:#f8fafb}#reasons .judgment-pair[hidden]{display:none}
#reasons .pair-paper{vertical-align:top;font-weight:500}#reasons .pair-title{display:block;font-weight:600;line-height:1.5;overflow-wrap:anywhere}#reasons .pair-paper small{font-size:.74rem;margin-top:.6rem;font-weight:400}
#reasons .pair-outcome{vertical-align:top}#reasons .pair-outcome strong,#reasons .pair-outcome>span{display:block}#reasons .pair-outcome strong{font-size:.9rem;color:var(--ink)}#reasons .pair-outcome>span{margin-top:.35rem;font-variant-numeric:tabular-nums}
#reasons .pair-reason-cell{padding-top:0}#reasons .pair-reasons{padding:0;margin:0;border:0}#reasons .pair-reasons>summary{font-size:.78rem;padding:.5rem 0 .9rem}
#reasons .judgment{padding:1rem 0 1.4rem;border:0}#reasons .overall-reason{font-size:.9rem;line-height:1.75}#reasons .overall-reason p{white-space:pre-wrap}
@media(max-width:760px){#reasons .pair-reasons .judgment{max-width:calc(100vw - 5rem)}}
@media print{#reasons .judgment-tools{display:none}#reasons .judgment-table-scroll{max-height:none;overflow:visible}#reasons .judgment-pairs{min-width:0}#reasons .judgment-pairs thead th{position:static}}
/* Row rules, aligned headers and readable line lengths; these selectors outrank the shared reset. */
main :is(.papers-table,.coverage-table,.judge-comparison,.judge-pairs,.range-table) tbody tr+tr>*{border-top:1px solid var(--line)}
main .heatmap td{border:2px solid #fff}main .heatmap thead th:not(:first-child){text-align:center}
.range-table{width:auto;min-width:min(100%,24rem)}main .range-table td{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.judge-name{white-space:nowrap}main .judge-settings code{white-space:nowrap;overflow-wrap:normal;background:none;padding:0}
main th small.paper-note{font-weight:400;margin-top:.35rem}
#reasons .overall-reason p,#reasons .answer-map{max-width:75ch}
main .paper-group{margin:.4rem 0}.diagnostics{margin:1rem 0 1.6rem}
.scroll-hint{margin:.8rem 0 -.6rem;font-size:.8rem;color:var(--muted)}
/* Phones: keep row labels in view while a wide table scrolls, and stack the tables that read as lists. */
@media(max-width:760px){main :is(.heatmap,.coverage-table,.judge-comparison) :is(tbody th[scope="row"],thead th:first-child){position:sticky;left:0;z-index:1;background:#fff}main :is(.heatmap,.coverage-table,.judge-comparison) thead th:first-child{background:#eaf1f3}main .coverage-table th[scope="row"]{min-width:8.5rem}}
@media(max-width:600px){main .judge-pairs{min-width:0}main .judge-pairs{table-layout:auto}main .judge-pairs th[scope="row"],main .judge-pairs thead th:first-child{width:auto}main .judge-pairs th,main .judge-pairs td{padding-left:.45rem;padding-right:.45rem}
/* Four short columns fit a phone, so the per-judge table drops its scroll width there. */
main .judge-comparison{min-width:0}main .judge-comparison th,main .judge-comparison td{padding-left:.45rem;padding-right:.45rem}
main .papers-table{min-width:0}main .papers-table thead{display:none}main .papers-table tr,main .papers-table th[scope="row"],main .papers-table td{display:block;width:auto}main .papers-table th[scope="row"]{padding-bottom:.25rem}main .papers-table td{padding-top:.2rem;padding-bottom:.2rem}main .papers-table tbody tr+tr>*{border-top:0}main .papers-table tbody tr+tr{border-top:1px solid var(--line)}main .paper-links a{display:inline-block;margin:0 1rem .25rem 0}
#reasons .judgment-table-scroll{max-height:none}#reasons .judgment-pairs thead{display:none}#reasons .judgment-pairs,#reasons .judgment-pairs tbody,#reasons .judgment-pairs tr,#reasons .judgment-pairs th,#reasons .judgment-pairs td{display:block;width:auto;min-width:0}#reasons th.pair-paper::before{content:"Paper 1";display:block;font-size:.75rem;font-weight:400;color:var(--muted)}#reasons td.pair-paper::before{content:"Paper 2";display:block;font-size:.75rem;color:var(--muted)}#reasons .pair-paper{padding-bottom:.3rem}#reasons .pair-outcome{padding-top:.3rem}#reasons .pair-reasons .judgment{max-width:none}}
"""


JUDGMENT_SCRIPT = """
(() => {
  const filter = document.getElementById('judgment-matchup');
  const table = document.getElementById('judgment-pair-table');
  const count = document.getElementById('judgment-count');
  if (!filter || !table || !count) return;
  const groups = Array.from(table.querySelectorAll('tbody[data-matchup]'));
  const summary = count.textContent;
  filter.disabled = false;
  filter.addEventListener('change', () => {
    let shown = 0;
    for (const group of groups) {
      group.hidden = filter.value !== 'all' && group.dataset.matchup !== filter.value;
      if (!group.hidden) shown += 1;
    }
    count.textContent = filter.value === 'all' ? summary : `Showing ${shown} of ${groups.length} paper pairs`;
    table.parentElement.scrollTop = 0;
  });
})();
(() => {
  // Show the sideways-scroll hint only above tables that overflow their box.
  const boxes = Array.from(document.querySelectorAll('.table-scroll'));
  const mark = () => {
    for (const box of boxes) {
      const hint = box.previousElementSibling;
      if (hint && hint.classList.contains('scroll-hint')) hint.hidden = box.scrollWidth <= box.clientWidth + 1;
    }
  };
  mark();
  addEventListener('resize', mark);
  document.addEventListener('toggle', mark, true);
})();
"""


def write_report(report: dict, destination: Path, *, data_root: Path) -> None:
    """Write a self-contained report; links are relative to its final location."""
    family = report.get('rubric_kind', NUS_KIND)
    if family not in (NUS_KIND, AUT_KIND):
        raise ValueError('Unsupported report rubric kind')
    for judgment in report.get("judgments", []):
        row_family = protocol_rubric_kind(judgment.get('judging_protocol', judgment.get('protocol_version')))
        if row_family != family or judgment.get('rubric_kind', row_family) != family:
            raise ValueError('Judgment rubric kind differs from the report')
        for field in ('judging_protocol', 'protocol_version'):
            if field in judgment and protocol_rubric_kind(judgment[field]) != family:
                raise ValueError('Judgment protocol differs from the report rubric')
        validate_verdict(judgment.get("verdict"), require_reason_quality=family == AUT_KIND)
    destination, data_root = Path(destination), Path(data_root)
    coverage = report.get("coverage", {})
    ready = _ready(report)
    colors = {agent: COLORS[index % len(COLORS)] for index, agent in enumerate(report.get("agents", {}))}
    completed = coverage.get("completed_jobs")
    judge_names = [_text(_judge_label(judge)) for judge in report.get("judges") or {}]
    judges = (f'{number_word(len(judge_names)).capitalize()} AI judge{"" if len(judge_names) == 1 else "s"} '
              f'({_and_list(judge_names)})' if judge_names else 'AI judges')
    systems = f'{number_word(len(report.get("agents", {})))} AI scientist systems'
    sample = (f'{_count(coverage.get("selected_papers"))} papers sampled from the '
              f'{_count(coverage.get("eligible_papers"))} eligible papers these systems released.')
    introduction = (
        f'{judges} read pairs of papers released by {systems} and picked the more creative paper in each pair. '
        f'The comparison uses {sample}' if ready else
        f'This comparison has not been judged yet. {judges} will read pairs of papers released by {systems} '
        f'and pick the more creative paper in each pair. The plan uses {sample}' if completed == 0 else
        f'This comparison is in progress. {judges} read pairs of papers released by {systems} '
        f'and pick the more creative paper in each pair. The plan uses {sample}')
    if family == AUT_KIND:
        introduction += (' Judgments use an AUT-inspired qualitative adaptation for expressed research '
                         'contributions, not a standardized AUT administration or a measure of author ability.')
    parts = ['<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width, initial-scale=1">',
             '<meta name="color-scheme" content="light"><title>AI scientist comparison · CREST</title>',
             site_favicon(data_root.resolve().parent, destination),
             '<meta name="description" content="An auditable pairwise comparison of released AI scientist papers, with frozen prompts, saved judgments, coverage, and uncertainty.">',
             f'<style>{CSS}\n{NAVIGATION_CSS}</style></head><body>',
             '<a class="skip-link" href="#main-content">Skip to report</a>',
             site_header(data_root.resolve().parent, destination),
             '<main id="main-content" tabindex="-1">',
             '<h1>AI scientist comparison</h1>',
             f'<p>{introduction}</p>',
             '<nav aria-label="Report contents"><a href="#overall">Ranking</a>'
             '<a href="#matchups">Head-to-head</a>'
             + ('<a href="#profiles">Strengths and weaknesses</a>' if report.get("creativity_profiles") else '') +
             '<a href="#method">Method</a>'
             '<a href="#judges">Judges</a><a href="#limits">Uncertainty</a>'
             '<a href="#coverage">Coverage</a><a href="#progress">Run summary</a>'
             '<a href="#papers">Papers</a><a href="#reasons">Judgments</a></nav>',
             _overall(report, ready, colors), _matchups(report, ready), _profiles(report), _method(report), _judges(report),
             _limits(report), _coverage(report), _progress(report), _papers(report, data_root, destination),
             _judgments(report, data_root, destination),
             f'</main><script>{JUDGMENT_SCRIPT}</script></body></html>\n']
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("".join(parts), encoding="utf-8")

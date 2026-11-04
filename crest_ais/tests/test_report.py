"""Observable report behavior: incomplete evidence, links, and untrusted text."""

from copy import deepcopy
from html.parser import HTMLParser
from itertools import combinations, product
import json
import re
import pytest

from crest_ais.tests.test_analysis import results_for, three_judge_plan, three_judge_winner


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.text = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, value):
        self.text.append(value)


@pytest.fixture
def report():
    return {
        "version": "crest-ais-v1", "generated_at": "2026-10-27T00:00:00Z",
        "status": "not_judged", "agents": {"one": "Scientist One", "v3": "Agentic Scientist v3"},
        "judges": {"judge-a": {"model": "vendor/actual-model-id", "temperature": 0}},
        "selection": {"seed": 2026, "pairs_per_matchup": 6},
        "coverage": {"expected_jobs": 4, "completed_jobs": 0, "usable_jobs": 0,
                     "expected_pairs": 1, "complete_pairs": 0,
                     "expected_decisions": 4, "used_decisions": 0,
                     "downloaded_papers": 35, "eligible_papers": 31, "selected_papers": 2,
                     "per_agent": {"one": {"downloaded": 32, "eligible": 29, "selected": 1},
                                   "v3": {"downloaded": 3, "eligible": 2, "selected": 1}}},
        "rankings": [{"agent": key, "rank": None, "overall_pct": None,
                      "intervals": {}, "paper_count": 1, "decision_count": 0}
                     for key in ("one", "v3")],
        "comparisons": [], "diagnostics": {"position_a_pct": None},
        "costs": {"known_usd": 0.0, "unknown_jobs": 0, "completed_jobs": 0},
        "papers": [{"id": "p1", "agent": "one", "title": "First paper",
                    "pdf_path": "data/one/first paper.pdf", "source_url": "https://example.org/first",
                    "topic": "Learning", "pages": 8, "eligible_primary": True},
                   {"id": "p2", "agent": "v3", "title": "Second paper",
                    "pdf_path": "data/v3/second.pdf", "source_url": "https://example.org/second",
                    "topic": "Optimization", "pages": 11, "eligible_primary": True}],
        "catalog": [], "judgments": [],
        "uncertainty": {"confidence_level": 0.95, "method": "paired cluster bootstrap", "note": "Conditional on these papers."},
        "limitations": ["PDF text does not include visual plot inspection."],
    }


def render(report, tmp_path):
    from crest_ais.report import write_report
    root = tmp_path / "crest_ais"
    destination = tmp_path / "docs" / "comparison.html"
    write_report(report, destination, data_root=root)
    return destination.read_text(encoding="utf-8")


def judgment():
    return {"key": "j1", "pair_id": "pair1", "order": ["p2", "p1"],
            "judge": "judge-a", "model": "vendor/returned-model", "cost_usd": None,
            "verdict": {"reason": "A’s unexpected mechanism offers the stronger overall proposal, despite B’s stronger experimental evidence.",
                        "winner": "A"}}


def complete(report):
    report["status"] = "complete"
    report["coverage"].update(completed_jobs=4, usable_jobs=4, complete_pairs=1, used_decisions=4)
    for row, score, rank in zip(report["rankings"], (62.5, 37.5), (1, 2)):
        row.update(rank=rank, overall_pct=score, decision_count=4,
                   intervals={"overall": {"low": 25, "high": 75}})
    report["comparisons"] = [{"agents": ["one", "v3"], "overall_pct_a": 62.5,
                              "complete_pairs": 1, "population_pairs": 58, "decision_count": 4}]
    return report


def test_aut_report_labels_criteria_and_limits_instead_of_nus(report, tmp_path):
    complete(report)
    report['rubric_kind'] = 'aut-inspired'
    row = judgment()
    row.update(judging_protocol='aut-inspired-overall-pairwise-v1', rubric_kind='aut-inspired')
    report['judgments'] = [row]
    html = render(report, tmp_path)
    assert 'AUT-inspired' in html
    assert all(f'<dt>{name}</dt>' in html for name in ('Fluency', 'Flexibility', 'Originality'))
    assert 'qualitative adaptation' in html
    assert 'not comparable across paper topics' in html
    assert 'preferences under this rubric' in html
    assert 'aut-inspired-rubric.html' in html
    assert 'New, Useful' not in html and 'Surprising jointly' not in html
    assert '<dt>Elaboration</dt>' not in html


def test_legacy_nus_report_rendering_matches_explicit_family(report, tmp_path):
    report['version'] = 'crest-ais-overall-v2'
    legacy = render(report, tmp_path)
    report['rubric_kind'] = 'nus'
    assert render(report, tmp_path) == legacy
    assert '<dt>Useful</dt>' in legacy and 'AUT-inspired' not in legacy
    assert 'The judges used version 1 of the New, Useful, Surprising (NUS) rubric.' in legacy
    assert 'CREST now defaults to version 2, which was not used here.' in legacy
    assert 'least familiar building block' in legacy and 'counts toward Surprising, not New' in legacy
    # The only rubric link describes v2, so it must say so on the v1 page.
    assert 'href="judging-method.html">the current NUS rubric (v2, not used here)</a>' in legacy
    report['version'] = 'crest-ais-overall-v3'
    current = render(report, tmp_path)
    assert 'version 1 of the' not in current and 'not used here' not in current
    assert 'substantive contribution' in current
    assert 'identifiable earlier research' in current
    assert 'least familiar building block' not in current


@pytest.mark.parametrize('kind', ['unknown', 'mislabeled', 'mixed', 'row_mislabeled', 'missing_protocol', 'unknown_protocol', 'conflicting_protocols', 'bad_reason'])
def test_report_rejects_inconsistent_rubric_metadata_before_overwriting(report, tmp_path, kind):
    report['rubric_kind'] = 'aut-inspired'
    row = judgment()
    row.update(judging_protocol='aut-inspired-overall-pairwise-v1', rubric_kind='aut-inspired')
    report['judgments'] = [row]
    if kind == 'unknown':
        report['rubric_kind'] = 'unrecognized'
    elif kind == 'mislabeled':
        report['rubric_kind'] = 'nus'
    elif kind == 'mixed':
        other = deepcopy(row)
        other.update(key='j2', judging_protocol='nus-overall-pairwise-v3', rubric_kind='nus')
        report['judgments'].append(other)
    elif kind == 'row_mislabeled':
        row['rubric_kind'] = 'nus'
    elif kind == 'missing_protocol':
        row.pop('judging_protocol')
    elif kind == 'unknown_protocol':
        row['judging_protocol'] = 'unsupported-overall-v1'
    elif kind == 'conflicting_protocols':
        row['protocol_version'] = 'nus-overall-pairwise-v3'
    else:
        row['verdict']['reason'] = 'Return JSON only.'
    destination = tmp_path / 'docs/comparison.html'
    destination.parent.mkdir()
    destination.write_text('previous report')
    with pytest.raises(ValueError):
        render(report, tmp_path)
    assert destination.read_text() == 'previous report'


def test_no_judgments_cannot_turn_missing_scores_into_ranked_zeroes(report, tmp_path):
    html = render(report, tmp_path)
    doc = Document(html)
    assert "No judgments yet" in html
    assert "Ranking withheld" in html
    assert not any(attrs.get("data-score") for _, attrs in doc.tags)
    assert not any(attrs.get("class") == "rank" for _, attrs in doc.tags)
    assert "Scientist One" in html and "Agentic Scientist v3" in html


def test_partial_run_with_stale_ranks_cannot_publish_primary_leaderboard(report, tmp_path):
    complete(report)
    report["status"] = "partial"
    report["coverage"].update(completed_jobs=1, usable_jobs=1, complete_pairs=0, used_decisions=0)
    html = render(report, tmp_path)
    doc = Document(html)
    assert "Ranking withheld" in html
    assert not any(attrs.get("class") == "rank" for _, attrs in doc.tags)
    assert not any(attrs.get("data-score") for _, attrs in doc.tags)


def test_complete_scores_and_uncertainty_are_visible_without_javascript(report, tmp_path):
    html = render(complete(report), tmp_path)
    doc = Document(html)
    scores = [attrs["data-score"] for _, attrs in doc.tags if "data-score" in attrs]
    assert "62.5" in scores and "37.5" in scores
    assert "62.5%" in html and "25.0–75.0%" in html
    assert "each opponent counts equally" in html.lower()
    assert any(tag == "svg" and attrs.get("role") == "img" for tag, attrs in doc.tags)


def test_pdfs_are_relative_to_output_and_sources_preserved(report, tmp_path):
    html = render(report, tmp_path)
    links = [attrs["href"] for tag, attrs in Document(html).tags if tag == "a"]
    assert "../crest_ais/data/one/first%20paper.pdf" in links
    assert "../crest_ais/data/v3/second.pdf" in links
    assert "https://example.org/first" in links
    assert not any(str(tmp_path) in link for link in links)


def test_counts_do_not_confuse_downloaded_selected_and_judged_papers(report, tmp_path):
    report["judgments"] = [judgment()]
    report["status"] = "partial"
    report["coverage"].update(completed_jobs=1, usable_jobs=1)
    html = render(report, tmp_path)
    doc = Document(html)
    rows = [attrs for _, attrs in doc.tags if "data-downloaded" in attrs]
    assert {(row["data-downloaded"], row["data-selected"], row["data-judged"]) for row in rows} == {
        ("32", "1", "1"), ("3", "1", "1")}
    assert "2 eligible papers" in html
    assert "vendor/actual-model-id" in html and "vendor/returned-model" in html


@pytest.mark.parametrize(("winner", "preferred"), [("A", "Second paper"), ("B", "First paper")])
def test_reasons_map_answer_labels_to_ordered_paper_ids(report, tmp_path, winner, preferred):
    report["judgments"] = [judgment()]
    report["judgments"][0]["verdict"]["winner"] = winner
    html = render(report, tmp_path)
    assert "A: Second paper" in html
    assert "B: First paper" in html
    assert f"Preferred: {preferred}" in html
    assert "A’s unexpected mechanism offers the stronger overall proposal, despite B’s stronger experimental evidence." in html


def test_untrusted_titles_reasons_and_urls_cannot_inject_html_or_scripts(report, tmp_path):
    payload = '</script><script>alert("owned")</script><img src=x onerror=alert(1)>'
    report["papers"][0]["title"] = payload
    report["papers"][0]["source_url"] = "javascript:alert(1)"
    report["judgments"] = [judgment()]
    report["judgments"][0]["verdict"]["reason"] = payload
    html = render(report, tmp_path)
    doc = Document(html)
    assert payload in "".join(doc.text)
    assert "<script>alert(" not in html
    assert not any(tag == "img" for tag, _ in doc.tags)
    assert not any(attrs.get("href", "").startswith("javascript:") for _, attrs in doc.tags)
    assert not any("src" in attrs for tag, attrs in doc.tags if tag == "script")


def test_null_and_invalid_intervals_do_not_fabricate_chart_geometry(report, tmp_path):
    complete(report)
    report["rankings"][0]["intervals"]["overall"] = {"low": None, "high": 75}
    report["rankings"][1]["intervals"]["overall"] = {"low": 90, "high": 20}
    html = render(report, tmp_path)
    assert "25.0–75.0%" not in html
    assert "90.0–20.0%" not in html
    assert "nan" not in html.lower()
    assert "Unavailable" in html


def test_report_is_an_offline_document_and_does_not_mutate_data(report, tmp_path):
    original = deepcopy(report)
    html = render(report, tmp_path)
    assert report == original
    assert html.startswith("<!DOCTYPE html>")
    doc = Document(html)
    assert not any(tag == "link" and attrs.get("rel") == "stylesheet" for tag, attrs in doc.tags)
    assert not any(tag == "script" and "src" in attrs for tag, attrs in doc.tags)
    assert any(tag == "meta" and attrs.get("name") == "viewport" for tag, attrs in doc.tags)


def test_complete_status_with_unusable_jobs_still_withholds_primary_ranks(report, tmp_path):
    complete(report)
    report["coverage"]["usable_jobs"] = 3
    html = render(report, tmp_path)
    assert "Ranking withheld" in html
    assert not any(attrs.get("class") == "rank" for _, attrs in Document(html).tags)


def test_broken_source_url_does_not_prevent_reading_remaining_papers(report, tmp_path):
    report["papers"][0]["source_url"] = "https://[malformed"
    html = render(report, tmp_path)
    assert "First paper" in html and "Second paper" in html
    assert not any(attrs.get("href") == "https://[malformed" for _, attrs in Document(html).tags)


def test_zero_is_a_real_score_and_reverse_heatmap_uses_complement(report, tmp_path):
    complete(report)
    report["rankings"][1]["overall_pct"] = 0
    html = render(report, tmp_path)
    doc = Document(html)
    assert any(attrs.get("data-score") == "0" for _, attrs in doc.tags)
    heatmap = html.split('<table class="heatmap">', 1)[1].split('</table>', 1)[0]
    assert "62.5%" in heatmap and "37.5%" in heatmap
    assert 'width="0.000"' in html


def test_overall_ties_and_rank_order_are_preserved_from_analysis(report, tmp_path):
    complete(report)
    report["agents"].update({"three": "Scientist Three", "four": "Scientist Four"})
    report["rankings"][0].update(overall_pct=37.5, rank=3)
    report["rankings"][1].update(overall_pct=62.5, rank=1)
    report["rankings"].extend([
        {"agent": "three", "rank": 1, "overall_pct": 62.5},
        {"agent": "four", "rank": None, "overall_pct": None},
    ])
    html = render(report, tmp_path)
    doc = Document(html)
    rows = [attrs for _, attrs in doc.tags if attrs.get("class") == "overall-row"]
    assert [(row["data-agent"], row.get("data-rank")) for row in rows] == [
        ("v3", "1"), ("three", "1"), ("one", "3"), ("four", None)]
    assert any(attrs.get("aria-label") == "Rank 3" for _, attrs in doc.tags)


def test_joint_concepts_do_not_display_legacy_criterion_scores_or_controls(report, tmp_path):
    complete(report)
    report["rankings"][0]["metrics"] = {"new": 84.321, "useful": 84.321, "surprising": 84.321}
    html = render(report, tmp_path)
    doc = Document(html)
    assert not any(tag == "select" for tag, _ in doc.tags)
    assert not any(attrs.get("class") == "criterion-row" for _, attrs in doc.tags)
    assert "84.3%" not in html
    assert "considered jointly" in html.lower()
    assert "scored separately" in html.lower()
    assert "criteria receive equal weight" not in html.lower()
    assert "three criteria" not in html.lower()


def test_per_judge_table_uses_overall_only_and_preserves_missing_values(report, tmp_path):
    report["diagnostics"]["per_judge"] = {
        "judge-a": {
            "one": {"overall_pct": 66.25, "complete_pairs_by_opponent": {"v3": 1}, "decision_count": 2},
            "v3": {"overall_pct": None,
                   "complete_pairs_by_opponent": {"one": 0}, "decision_count": 0},
        }}
    html = render(report, tmp_path)
    table = html.split('<table class="judge-comparison">', 1)[1].split('</table>', 1)[0]
    assert "66.3%" in table  # half up, as readers round
    assert ">New<" not in table and ">Useful<" not in table and ">Surprising<" not in table
    assert "Unavailable" in table
    # An unknown judge keeps its id as its name; model ids appear only in the judge settings line.
    assert '<th scope="col">judge-a</th>' in table and "vendor/actual-model-id" not in table
    assert "vendor/actual-model-id" in html.split('id="run-audit"', 1)[1].split("</p>", 1)[0]
    assert "Scientist One" in table and "Agentic Scientist v3" in table


def test_cost_is_identified_as_estimated_from_usage_and_method_is_linked(report, tmp_path):
    report["costs"].update(known_usd=1.2345, unknown_jobs=2)
    html = render(report, tmp_path)
    assert "$1.23" in html
    assert "estimated" in html.lower() and "recorded usage" in html.lower()
    links = [attrs["href"] for tag, attrs in Document(html).tags if tag == "a"]
    assert "ai-scientist-method.html" in links


def test_nested_legacy_verdict_is_rejected_before_writing_a_misleading_report(report, tmp_path):
    report["judgments"] = [judgment()]
    report["judgments"][0]["verdict"] = {
        criterion: {"reason": "Obsolete separate preference.", "winner": "A"}
        for criterion in ("new", "useful", "surprising")}
    with pytest.raises(ValueError, match="reason and winner"):
        render(report, tmp_path)
    assert not (tmp_path / "docs" / "comparison.html").exists()


def test_decision_coverage_is_reported_once_per_overall_vote(report, tmp_path):
    report["coverage"].update(expected_jobs=144, expected_decisions=144, used_decisions=4)
    html = render(report, tmp_path)
    assert "0 / 144" in html and "Decisions used" not in html
    assert "432" not in html


def test_total_cost_does_not_double_count_already_included_prior_requests(report, tmp_path):
    report["costs"].update(known_usd=13, current_run_known_usd=10,
                           prior_excluded_jobs=7, prior_excluded_known_usd=3)
    html = render(report, tmp_path)
    assert "$13.00" in html
    assert "The total also includes $3.00 for 7 discarded requests from earlier runs." in html
    assert "$16.00" not in html


def test_shared_site_navigation_and_current_document_titles_are_retained(report, tmp_path):
    html = render(report, tmp_path)
    doc = Document(html)
    assert any(tag == "header" and attrs.get("class") == "crest-site-header" for tag, attrs in doc.tags)
    assert "<h1>AI scientist comparison</h1>" in html
    assert any(tag == "link" and attrs.get("rel") == "icon" and attrs.get("href") == "favicon.svg"
               for tag, attrs in doc.tags)
    links = [attrs["href"] for tag, attrs in doc.tags if tag == "a"]
    assert links[:6] == ["#main-content", "https://github.com/jasonzliang/crest", "crest-guide.html",
                         "deep-research-creativity.html", "ai-scientist-creativity.html", "index.html"]


def test_main_reading_order_puts_results_and_method_before_caveats_and_audit(report, tmp_path):
    doc = Document(render(report, tmp_path))
    sections = [attrs["id"] for tag, attrs in doc.tags if tag == "section"]
    assert sections == ["overall", "matchups", "method", "judges", "limits", "coverage", "progress", "papers", "reasons"]
    nav = [attrs["href"] for tag, attrs in doc.tags if tag == "a" and attrs.get("href", "").startswith("#")][1:]
    assert nav == ["#" + section for section in sections]


def test_observed_zero_has_visible_marker_and_bounds_are_in_collapsed_disclosure(report, tmp_path):
    complete(report)
    report["rankings"][1]["overall_pct"] = 0
    html = render(report, tmp_path)
    doc = Document(html)
    assert any(tag == "circle" and attrs.get("class") == "mean-dot" and attrs.get("cx") == "4.000"
               for tag, attrs in doc.tags)
    bounds = [(tag, attrs) for tag, attrs in doc.tags if attrs.get("id") == "sampling-uncertainty"]
    assert len(bounds) == 1 and bounds[0][0] == "details" and "open" not in bounds[0][1]
    assert "95% sampling range" in html
    assert "Overlapping ranges mean the order between those scientists is uncertain." in html
    assert not any(attrs.get("class") == "interval-line" for _, attrs in doc.tags)


def test_missing_confidence_or_partial_run_does_not_invent_95_percent_ranges(report, tmp_path):
    complete(report)
    report["uncertainty"].pop("confidence_level")
    html = render(report, tmp_path)
    assert "95% sampling range" not in html
    report["status"] = "partial"
    report["uncertainty"]["confidence_level"] = 0.95
    html = render(report, tmp_path)
    assert "25.0–75.0%" not in html


def test_heatmap_and_judge_rows_follow_saved_rank_order_with_short_labels(report, tmp_path):
    complete(report)
    report["agents"] = {"scientisttwo": "ScientistTwo (Google Cloud AI Research)",
                        "sakana_agentic_scientist": "Sakana The Agentic Scientist (AI-Scientist-v3)"}
    report["rankings"] = [{"agent": "scientisttwo", "rank": 2, "overall_pct": 25, "intervals": {}},
                          {"agent": "sakana_agentic_scientist", "rank": 1, "overall_pct": 75, "intervals": {}}]
    report["diagnostics"]["per_judge"] = {"judge-a": {}}
    html = render(report, tmp_path)
    expected = ["sakana_agentic_scientist", "scientisttwo"]
    for classname in ("heatmap", "judge-comparison"):
        table = html.split(f'<table class="{classname}">', 1)[1].split('</table>', 1)[0]
        rows = [attrs["data-agent"] for tag, attrs in Document(table).tags if tag == "tr" and "data-agent" in attrs]
        assert rows == expected
        assert "Sakana Agentic Scientist (v3)" in table and "ScientistTwo" in table
        assert "Google Cloud AI Research" not in table
    assert "Sakana Agentic Scientist (v3)" in html


def test_judge_columns_and_readable_diagnostic_denominators(report, tmp_path):
    report["judges"]["judge-b"] = {"model": "vendor/second-model"}
    report["diagnostics"].update(
        position_a_pct=50, swapped_inconsistency_pct=12.5, judge_disagreement_pct=25,
        denominators={"position_a": 16, "swapped_inconsistency": 8, "judge_disagreement": 8},
        per_judge={"judge-a": {"one": {"overall_pct": 75}},
                   "judge-b": {"one": {"overall_pct": 25}}})
    html = render(report, tmp_path)
    table = html.split('<table class="judge-comparison">', 1)[1].split('</table>', 1)[0]
    assert '<th scope="col">judge-a</th>' in table and '<th scope="col">judge-b</th>' in table
    assert "vendor/actual-model-id" not in table and "vendor/second-model" not in table
    assert table.index("75.0%") < table.index("25.0%")
    assert "Across 8 same-pair, same-order comparisons." in html
    assert "Across 8 cases where a judge read a pair in both orders." in html
    assert "Across 16 votes. 50% means no position bias." in html
    assert "Agreement among judges does not show that they are right." in html


def test_coverage_uses_counts_and_selection_shares_instead_of_duplicate_bars(report, tmp_path):
    html = render(report, tmp_path)
    assert "3.4%" in html and "50.0%" in html
    assert "We downloaded 35 released papers. We excluded 4, which leaves 31 eligible papers" in html
    assert "1 excluded" in html
    assert not any(attrs.get("class") == "coverage-bar" for _, attrs in Document(html).tags)


@pytest.mark.parametrize(("catalog", "explanation_expected"), [
    ([{"title": "Diffusing Blame: Task-Dependent Credit Assignment", "eligible_primary": False}], True),
    ([{"title": "Diffusing Blame: Task-Dependent Credit Assignment", "eligible_primary": True}], False),
    ([{"title": "Another archived paper", "eligible_primary": False}], False),
    ([], False),
])
def test_coverage_explains_diffusing_blame_exclusion_only_when_catalog_records_it(
        report, tmp_path, catalog, explanation_expected):
    report["catalog"] = catalog
    html = render(report, tmp_path)
    coverage = html.split('<section id="coverage"', 1)[1].split('</section>', 1)[0]
    assert ("paper, Diffusing Blame, because" in coverage) is explanation_expected
    assert ("(see below)" in coverage) is explanation_expected
    if explanation_expected:
        assert 'href="https://pub.sakana.ai/agentic-scientist/"' in coverage
        assert "humans substantially guided and revised it" in coverage


def test_pair_outcomes_are_visible_and_full_reasons_remain_expandable(report, tmp_path):
    report["judgments"] = [judgment()]
    html = render(report, tmp_path)
    doc = Document(html)
    assert any(tag == "table" and attrs.get("id") == "judgment-pair-table" for tag, attrs in doc.tags)
    assert not any(attrs.get("id") == "judgment-browser" for _, attrs in doc.tags)
    assert any(tag == "details" and attrs.get("class") == "pair-reasons" for tag, attrs in doc.tags)
    assert "A’s unexpected mechanism offers the stronger overall proposal" in html


def test_concept_bookmark_and_primary_paper_links_remain_visible(report, tmp_path):
    html = render(report, tmp_path)
    doc = Document(html)
    assert any(attrs.get("id") == "concepts" for _, attrs in doc.tags)
    links = [attrs.get("href") for tag, attrs in doc.tags if tag == "a"]
    assert "https://doi.org/10.1080/10400419.2012.650092" in links
    assert "https://doi.org/10.1080/10400419.2017.1302776" in links
    assert "overall-creativity-judgment.html" in links
    assert 'href="judging-method.html">the NUS rubric</a>' in html
    assert 'href="overall-creativity-judgment.html">why we ask for one overall judgment</a>' in html
    method = html.split('<section id="method"', 1)[1].split('</section>', 1)[0]
    assert method.index('id="concepts"') < method.index('ai-scientist-method.html')


def test_extended_plan_displays_ten_pairs_and_240_votes_from_report_data(report, tmp_path):
    report["selection"]["pairs_per_matchup"] = 10
    report["coverage"].update(expected_pairs=60, complete_pairs=60, expected_jobs=240,
                              completed_jobs=240, usable_jobs=240, expected_decisions=240,
                              used_decisions=240)
    report["status"] = "complete"
    html = render(report, tmp_path)
    assert "we drew up to 10 pairs of their papers at random" in html
    assert "60 / 60" in html
    assert "240 / 240" in html


def test_post_result_extension_ranges_are_exploratory_without_false_confidence_claim(report, tmp_path):
    complete(report)
    report["uncertainty"] = {"confidence": None, "nominal_fixed_size_level": 0.95,
                             "inference_scope": "exploratory_fixed_size_reference",
                             "sequential_valid": False, "method": "Exploratory reference bounds"}
    html = render(report, tmp_path)
    assert ">Sampling range<" in html
    assert "95% sampling range" not in html
    assert "We grew this comparison after seeing earlier results." in html
    # Without an analysis note, the page still refuses to call the ranges confidence intervals.
    assert "rough guides, not confidence intervals" in html


def test_report_omits_complete_analysis_json_panel_and_embedded_payload(report, tmp_path):
    html = render(report, tmp_path)
    assert "Complete analysis data (JSON)" not in html
    assert not any(attrs.get("id") in {"analysis-record", "analysis-data", "analysis-json"}
                   for _, attrs in Document(html).tags)


def test_paper_groups_share_primary_order_and_partial_ignores_stale_ranks(report, tmp_path):
    complete(report)
    report["rankings"][0]["rank"], report["rankings"][1]["rank"] = 2, 1
    html = render(report, tmp_path)
    groups = [attrs["data-agent"] for tag, attrs in Document(html).tags
              if tag == "details" and attrs.get("class") == "paper-group"]
    assert groups == ["v3", "one"]
    report["status"] = "partial"
    html = render(report, tmp_path)
    groups = [attrs["data-agent"] for tag, attrs in Document(html).tags
              if tag == "details" and attrs.get("class") == "paper-group"]
    assert groups == ["one", "v3"]


def pair_judgments(winners, *, paper_ids=("p1", "p2"), pair_id="pair1", judges=("judge-a", "judge-b")):
    """Fixtures state physical winning papers independently of their A/B positions."""
    rows = []
    cells = [(judge, order) for judge in judges for order in (paper_ids, paper_ids[::-1])]
    for index, (winner, (judge, order)) in enumerate(zip(winners, cells)):
        rows.append({"key": f"{pair_id}-j{index}", "pair_id": pair_id,
                     "order": list(order), "judge": judge, "model": f"model/{judge}",
                     "verdict": {"winner": "A" if order[0] == winner else "B",
                                 "reason": f"Saved comparative reason {index}: paper {winner}."}})
    return rows


def pair_rows(html):
    return [attrs for tag, attrs in Document(html).tags
            if tag == "tbody" and attrs.get("class") == "judgment-pair"]


def test_pair_winner_counts_remap_each_actual_order_before_aggregation(report, tmp_path):
    report["judges"]["judge-b"] = {"model": "vendor/second-model"}
    # A wins three calls, but the physical Second paper wins three votes.
    report["judgments"] = pair_judgments(["p2", "p2", "p1", "p2"])
    html = render(report, tmp_path)
    row = pair_rows(html)[0]
    assert row["data-winner"] == "p2"
    assert (row["data-votes-left"], row["data-votes-right"]) == ("1", "3")
    assert "Agentic Scientist v3 preferred" in html and "1–3 votes" in html
    assert not any(attrs.get("class") == "paper-winner" for _, attrs in Document(html).tags)
    assert "In each reason, A and B mean the order that judge saw" in html
    table = html.split('id="judgment-pair-table"', 1)[1].split('</table>', 1)[0]
    links = [attrs["href"] for tag, attrs in Document(table).tags if tag == "a"]
    assert "../crest_ais/data/one/first%20paper.pdf" in links
    assert "../crest_ais/data/v3/second.pdf" in links
    assert "Each judge read every pair twice, once in each order" in html and "4 votes per pair" in html
    assert "3–1 pair counts as 75% for the winner" in html


def test_four_forced_a_choices_can_produce_an_aggregate_pair_tie(report, tmp_path):
    report["judges"]["judge-b"] = {"model": "vendor/second-model"}
    report["judgments"] = pair_judgments(["p1", "p2", "p1", "p2"])
    html = render(report, tmp_path)
    row = pair_rows(html)[0]
    assert row["data-outcome"] == "tie" and "data-winner" not in row
    assert (row["data-votes-left"], row["data-votes-right"]) == ("2", "2")
    assert "Tie" in html and "2–2 votes" in html


def test_incomplete_or_duplicate_cells_do_not_declare_a_pair_winner(report, tmp_path):
    report["judges"]["judge-b"] = {"model": "vendor/second-model"}
    report["judgments"] = pair_judgments(["p2", "p2", "p2"])
    html = render(report, tmp_path)
    assert pair_rows(html)[0]["data-outcome"] == "partial"
    assert "data-winner" not in pair_rows(html)[0]
    assert "Partial: 3 / 4 judgments" in html
    assert "Agentic Scientist v3 preferred" not in html
    duplicate = deepcopy(report["judgments"][0])
    duplicate["key"] = "duplicated-cell"
    report["judgments"].append(duplicate)
    html = render(report, tmp_path)
    assert pair_rows(html)[0]["data-outcome"] == "partial"


def test_matchup_filter_labels_and_pair_order_follow_primary_rank(report, tmp_path):
    complete(report)
    report["judges"]["judge-b"] = {"model": "vendor/second-model"}
    report["agents"]["third"] = "Third Scientist"
    report["rankings"].append({"agent": "third", "rank": 3, "overall_pct": 0, "intervals": {}})
    report["papers"].append({"id": "p3", "agent": "third", "title": "Third paper"})
    report["judgments"] = (pair_judgments(["p3"] * 4, paper_ids=("p2", "p3"), pair_id="late")
                           + pair_judgments(["p1"] * 4))
    html = render(report, tmp_path)
    assert [row["data-pair-id"] for row in pair_rows(html)] == ["pair1", "late"]
    doc = Document(html)
    assert any(tag == "label" and attrs.get("for") == "judgment-matchup" for tag, attrs in doc.tags)
    assert any(tag == "select" and attrs.get("aria-controls") == "judgment-pair-table" for tag, attrs in doc.tags)
    assert "All matchups" in html
    assert "Scientist One vs. Agentic Scientist v3" in html
    assert "Agentic Scientist v3 vs. Third Scientist" in html
    assert any(tag == "td" and attrs.get("colspan") == "3" for tag, attrs in doc.tags)
    assert "Saved comparative reason 3: paper p1." in html


def test_intro_combines_status_and_sample_counts_without_a_metadata_badge(report, tmp_path):
    complete(report)
    html = render(report, tmp_path)
    assert ("One AI judge (judge-a) read pairs of papers released by two AI scientist systems and picked "
            "the more creative paper in each pair. The comparison uses 2 papers sampled from the 31 eligible "
            "papers these systems released.") in html
    assert not any(attrs.get("class") in {"meta", "status"} for _, attrs in Document(html).tags)
    report["status"] = "partial"
    html = render(report, tmp_path)
    assert "This comparison is in progress." in html
    assert "The comparison uses" not in html and "The plan uses 2 papers" in html


@pytest.fixture
def five_report(report):
    agents = ["sakana_ai_scientist_v2", "sakana_agentic_scientist", "sakana_ai_scientist",
              "scientistone", "scientisttwo"]
    report["agents"] = {agent: agent for agent in agents}
    report["judges"]["judge-b"] = {"model": "vendor/second-model"}
    sizes = [3, 2, 5, 5, 5]
    pools = {agent: [f"{agent}-p{index}" for index in range(size)] for agent, size in zip(agents, sizes)}
    report["papers"] = [{"id": identity, "agent": agent, "title": f"Paper {identity}"}
                        for agent, identities in pools.items() for identity in identities]
    report["judgments"] = []
    report["comparisons"] = []
    for left, right in combinations(agents, 2):
        pairs = list(product(pools[left], pools[right]))[:10]
        special = left == "sakana_ai_scientist_v2" and right == "sakana_agentic_scientist"
        for index, (left_paper, right_paper) in enumerate(pairs):
            winners = ([left_paper] * 3 + [right_paper] if special else
                       [right_paper] * 4 if left == "sakana_ai_scientist_v2" else [left_paper] * 4)
            report["judgments"].extend(pair_judgments(
                winners, paper_ids=(left_paper, right_paper), pair_id=f"{left}-{right}-{index}"))
        score = 75 if special else 0 if left == "sakana_ai_scientist_v2" else 100
        report["comparisons"].append({"agents": [left, right], "overall_pct_a": score,
                                      "complete_pairs": len(pairs), "population_pairs": len(pools[left]) * len(pools[right])})
    # Hand-derived opponent means. V2's pooled raw win rate would be 12.5%.
    scores, ranks = [18.75, 81.25, 75, 50, 25], [5, 1, 2, 3, 4]
    report["rankings"] = [{"agent": agent, "rank": rank, "overall_pct": score, "intervals": {}}
                          for agent, rank, score in zip(agents, ranks, scores)]
    report["diagnostics"]["per_judge"] = {
        judge: {agent: {"overall_pct": score} for agent, score in zip(agents, scores)} for judge in report["judges"]}
    report["coverage"].update(expected_jobs=384, completed_jobs=384, usable_jobs=384,
                              expected_pairs=96, complete_pairs=96, expected_decisions=384,
                              used_decisions=384, selected_papers=20, eligible_papers=20, downloaded_papers=20,
                              per_agent={agent: {"downloaded": size, "eligible": size, "selected": size}
                                         for agent, size in zip(agents, sizes)})
    report["selection"]["pairs_per_matchup"] = 10
    report["status"] = "complete"
    return report


def test_five_agent_report_names_colors_and_opponent_count_are_dynamic(five_report, tmp_path):
    html = render(five_report, tmp_path)
    doc = Document(html)
    assert "Sakana AI Scientist (v2)" in html
    assert "the other 4 scientists" in html
    assert "three opponents" not in html
    links = [attrs.get("href") for tag, attrs in doc.tags if tag == "a"]
    assert "https://github.com/SakanaAI/AI-Scientist-v2" in links
    colors = {attrs["fill"] for tag, attrs in doc.tags if tag == "rect" and attrs.get("fill") != "#edf2f3"}
    assert len(colors) == 5
    assert "Sakana AI Scientist (v2) has 3 eligible papers" in html
    assert "Sakana Agentic Scientist (v3) has 2 eligible papers" in html


def test_five_agent_tables_and_filter_cover_ten_unequal_matchups(five_report, tmp_path):
    html = render(five_report, tmp_path)
    doc = Document(html)
    assert "96 / 96" in html and "384 / 384" in html
    assert len(pair_rows(html)) == 96
    assert len([attrs for tag, attrs in doc.tags if tag == "option"]) == 11
    counts = {}
    for row in pair_rows(html):
        counts[row["data-matchup"]] = counts.get(row["data-matchup"], 0) + 1
    assert sorted(counts.values()) == [6] + [10] * 9
    expected = ["sakana_agentic_scientist", "sakana_ai_scientist", "scientistone", "scientisttwo", "sakana_ai_scientist_v2"]
    for classname in ("heatmap", "judge-comparison"):
        table = html.split(f'<table class="{classname}">', 1)[1].split('</table>', 1)[0]
        assert [attrs["data-agent"] for tag, attrs in Document(table).tags if tag == "tr" and "data-agent" in attrs] == expected
    assert "6 pairs (all possible)" in html


def test_unequal_matchup_renderer_preserves_supplied_macro_score(five_report, tmp_path):
    original = deepcopy(five_report)
    html = render(five_report, tmp_path)
    row = next(attrs for tag, attrs in Document(html).tags
               if tag == "div" and attrs.get("class") == "overall-row" and attrs.get("data-agent") == "sakana_ai_scientist_v2")
    assert row["data-score"] == "18.75"
    overall = html.split('<section id="overall"', 1)[1].split('</section>', 1)[0]
    assert "18.8%" in overall and "12.5%" not in overall
    assert "even where fewer pairs were possible" in overall
    assert five_report == original


def test_v2_processing_details_are_omitted_from_report_method(five_report, tmp_path):
    note = "The v2 PDFs include human review comments in the margins; these were excluded from the text shown to judges."
    html = render(five_report, tmp_path)
    method = html.split('<section id="method"', 1)[1].split('</section>', 1)[0]
    assert note not in method


def test_four_agent_report_does_not_invent_v2_review_comment_note(report, tmp_path):
    assert "The v2 PDFs include human review comments" not in render(report, tmp_path)


def test_hidden_pair_label_is_positioned_inside_its_scroll_container(report, tmp_path):
    """Removing scroll containment must not send absolute labels to the viewport."""
    cssselect2 = pytest.importorskip("cssselect2")
    tinycss2 = pytest.importorskip("tinycss2")
    lxml_html = pytest.importorskip("lxml.html")
    report["judgments"] = [judgment()]
    root = lxml_html.fromstring(render(report, tmp_path))
    matcher = cssselect2.Matcher()
    # Resolve screen rules against the rendered DOM, including the final shared CSS.
    for stylesheet in root.iter("style"):
        for rule in tinycss2.parse_stylesheet(stylesheet.text, skip_whitespace=True, skip_comments=True):
            if rule.type != "qualified-rule":
                continue
            properties = {item.lower_name: tinycss2.serialize(item.value).strip()
                          for item in tinycss2.parse_declaration_list(rule.content)
                          if item.type == "declaration" and item.lower_name in {"position", "overflow"}}
            if not properties:
                continue
            for selector in cssselect2.compile_selector_list(tinycss2.serialize(rule.prelude)):
                matcher.add_selector(selector, properties)

    def computed(element):
        properties = {"position": "static", "overflow": "visible"}
        for _, _, _, declarations in matcher.match(element):
            properties.update(declarations)
        return properties

    wrappers = list(cssselect2.ElementWrapper.from_html_root(root).iter_subtree())
    label = next(element for element in wrappers
                 if "sr-only" in element.classes and element.parent.etree_element.tag == "summary")
    assert computed(label)["position"] == "absolute"
    assert "for pair 1" in label.etree_element.text
    containing_block = label.parent
    while containing_block is not None and computed(containing_block)["position"] == "static":
        containing_block = containing_block.parent
    assert containing_block is not None, "Hidden pair labels must not use the viewport as their containing block"
    assert "judgment-table-scroll" in containing_block.classes
    assert computed(containing_block)["overflow"] == "auto"


JUDGE_ADDITION = {"version": "crest-ais-judge-extension-v1", "kind": "judge_addition", "stage": "post_initial_results",
                  "added_judges": ["anthropic"], "previous_judges": ["gemini", "openai"],
                  "current_judges": ["anthropic", "gemini", "openai"], "original_pairs": 2, "additional_pairs": 0,
                  "imported_jobs": 8, "additional_jobs": 4, "target_pairs_per_matchup": 2, "parent_extension": None}


def test_three_judge_report_shows_every_judge_and_each_judge_pair(tmp_path):
    from crest_ais.analysis import analyze
    plan = three_judge_plan()
    plan["selection"]["pairs_per_matchup"] = 2
    plan["extension"] = deepcopy(JUDGE_ADDITION)
    html = render(analyze(plan, results_for(plan, three_judge_winner)), tmp_path)
    assert 'style="--judge-min-width:570px"' in html
    table = html.split('<table class="judge-comparison">', 1)[1].split('</table>', 1)[0]
    headers = [attrs for tag, attrs in Document(table).tags if tag == "th" and attrs.get("scope") == "col"]
    assert len(headers) == 4
    for name, model in (("Claude Fable 5.1", "claude-fable-5-1"), ("Gemini 4 Argon", "gemini-4-argon"),
                        ("GPT-6 Astra", "gpt-6-astra")):
        assert f'<th scope="col">{name}</th>' in table and model not in table
    rows = {agent: re.findall(r"<strong>([^<]+)</strong>", table.split(f'data-agent="{agent}"', 1)[1].split("</tr>", 1)[0])
            for agent in ("a", "b")}
    assert rows == {"a": ["75.0%", "50.0%", "0.0%"], "b": ["25.0%", "50.0%", "100.0%"]}
    pairs = html.split('<table class="judge-pairs">', 1)[1].split('</table>', 1)[0]
    pair_rows_html = [(key, re.sub(r"<[^>]+>", "", label), pct, count) for key, label, pct, count in re.findall(
        r'<tr data-judges="([^"]+)"><th scope="row">(.*?)</th><td><strong>([^<]+)</strong></td><td>([^<]+)</td>', pairs)]
    assert '<span class="judge-name">Claude Fable 5.1</span> vs. <span class="judge-name">Gemini 4 Argon</span>' in pairs
    assert pair_rows_html == [("anthropic|gemini", "Claude Fable 5.1 vs. Gemini 4 Argon", "25.0%", "4"),
                              ("anthropic|openai", "Claude Fable 5.1 vs. GPT-6 Astra", "75.0%", "4"),
                              ("gemini|openai", "Gemini 4 Argon vs. GPT-6 Astra", "50.0%", "4")]
    judges = html.split('<section id="judges"', 1)[1].split('</section>', 1)[0]
    assert "Across 12 same-pair, same-order comparisons." in judges
    assert "The 50.0% above combines all three pairs of judges." in judges
    assert "This table repeats the ranking using one judge’s votes at a time." in judges
    assert "Three AI judges (Claude Fable 5.1, Gemini 4 Argon and GPT-6 Astra) read pairs of papers" in html
    assert "Each judge read every pair twice, once in each order" in html and "That gives 6 votes per pair." in html
    assert "a 3–3 split is a tie" in html and "a 5–1 pair counts as 83% for the winner" in html
    assert "4 votes per pair" not in html and "two judges, each" not in html and "2–2" not in html
    assert [(row["data-outcome"], row["data-votes-left"], row["data-votes-right"]) for row in pair_rows(html)] == [
        ("winner", "2", "4"), ("winner", "5", "1")]
    method = html.split('<section id="method"', 1)[1].split('</section>', 1)[0]
    limits = html.split('<section id="limits"', 1)[1].split('</section>', 1)[0]
    assert "added after" not in limits and "added after" not in method
    assert "2 to 3 judges" not in html and "judge_addition" not in html
    assert "We added a judge" not in html
    # The heatmap diagonal placeholder predates this report text and is not prose.
    assert "\N{EM DASH}" not in html.replace('aria-label="Same scientist">\N{EM DASH}<', "")


def test_partial_three_judge_pair_needs_six_judgments(report, tmp_path):
    judges = ("anthropic", "judge-a", "judge-b")
    report["judges"] = {"anthropic": {"model": "claude-fable-5-1"}, "judge-a": {"model": "vendor/actual-model-id"},
                        "judge-b": {"model": "vendor/second-model"}}
    report["judgments"] = pair_judgments(["p1", "p1", "p1", "p2"], judges=judges[1:])
    html = render(report, tmp_path)
    assert pair_rows(html)[0]["data-outcome"] == "partial"
    assert "Partial: 4 / 6 judgments" in html
    report["judgments"] = pair_judgments(["p2", "p2", "p1", "p1", "p1", "p2"], judges=judges)
    html = render(report, tmp_path)
    row = pair_rows(html)[0]
    assert (row["data-outcome"], row["data-votes-left"], row["data-votes-right"]) == ("tie", "3", "3")
    assert "Tie" in html and "3–3 votes" in html
    assert "claude-fable-5-1" in html


SAMPLE_STEP = {"stage": "post_initial_results", "target_pairs_per_matchup": 10, "original_pairs": 36,
               "strata": [{"original_pairs": 6, "final_pairs": 10}] * 6, "parent_extension": None}
COHORT_STEP = {"stage": "post_initial_results", "kind": "cohort_addition", "previous_agent_count": 4,
               "current_agent_count": 5, "original_pairs": 60, "parent_extension": None}


@pytest.mark.parametrize(("parent", "explanation"), [
    (None, "We grew this comparison after seeing earlier results."),
    (COHORT_STEP, "We grew this comparison after seeing earlier results: from 4 to 5 scientists. "
                  "Earlier votes were kept unchanged."),
    ({**COHORT_STEP, "parent_extension": SAMPLE_STEP},
     "We grew this comparison after seeing earlier results: first from 6 to 10 pairs per matchup, "
     "then from 4 to 5 scientists. Earlier votes were kept unchanged."),
])
def test_judge_addition_explains_post_hoc_ranges_and_two_judge_runs_hide_pair_table(report, tmp_path, parent, explanation):
    complete(report)
    report["judges"]["judge-b"] = {"model": "vendor/second-model"}
    report["diagnostics"]["judge_pair_disagreement"] = {
        "judge-a|judge-b": {"judges": ["judge-a", "judge-b"], "disagreement_pct": 25.0, "count": 2, "denominator": 8}}
    html = render(report, tmp_path)
    assert 'class="judge-pairs"' not in html and "pairs of judges" not in html
    assert "That gives 4 votes per pair." in html
    report["uncertainty"] = {"confidence": None, "inference_scope": "exploratory_fixed_size_reference"}
    report["extension"] = {**JUDGE_ADDITION, "parent_extension": parent}
    report["judges"]["anthropic"] = {"model": "claude-fable-5-1"}
    html = render(report, tmp_path)
    assert explanation in html
    # The sampling history skips the judge-addition link: the page never says a judge joined later.
    assert "added after" not in html and "We added a judge" not in html and "judges." not in explanation
    assert "to 3 judges" not in html and "previous_judges" not in html


def test_plural_helper_and_singular_counts_on_the_page(report, tmp_path):
    from crest_ais.report import plural
    assert plural(1, "pair") == "1 pair" and plural(2, "pair") == "2 pairs" and plural(0, "pair") == "0 pairs"
    assert plural(1, "analysis", "analyses") == "1 analysis" and plural(3, "analysis", "analyses") == "3 analyses"
    assert plural(1200, "vote") == "1,200 votes"
    complete(report)
    report["judgments"] = [judgment()]
    html = render(report, tmp_path)
    assert "<small>1 pair</small>" in html and "1 pairs" not in html
    assert "· 1 selected paper<" in html and "1 selected papers" not in html
    assert "Read 1 saved judgment<" in html and "1 saved judgments" not in html
    assert "1 matchup." in html


def test_judges_use_display_names_and_model_ids_only_in_the_settings_line(tmp_path):
    from crest_ais.analysis import analyze
    from crest_ais.report import JUDGE_NAMES, _judge_label
    assert JUDGE_NAMES == {"anthropic": "Claude Fable 5.1", "gemini": "Gemini 4 Argon", "openai": "GPT-6 Astra"}
    assert _judge_label("mistral") == "mistral"
    plan = three_judge_plan()
    plan["judges"]["anthropic"].update(effort="high")
    html = render(analyze(plan, results_for(plan, three_judge_winner)), tmp_path)
    settings = html.split('id="run-audit">', 1)[1].split("</p>", 1)[0]
    assert settings.startswith("Judges: Claude Fable 5.1 (<code>claude-fable-5-1</code>, effort high), "
                               "Gemini 4 Argon (<code>gemini-4-argon</code>")
    assert "GPT-6 Astra (<code>gpt-6-astra</code>" in settings
    for hidden in ("concurrency", "timeout", "worker", "poll"):
        assert hidden not in settings
    # Outside that line, model ids live only in data attributes, never in visible text.
    visible = "".join(Document(html.replace(settings, "")).text)
    for model in ("claude-fable-5-1", "gemini-4-argon", "gpt-6-astra"):
        assert model not in visible
    assert "<h3>Claude Fable 5.1</h3>" in html and "<h3>anthropic" not in html
    assert ">anthropic<" not in html and "anthropic vs." not in html


def test_refusals_get_one_full_statement_and_short_references_elsewhere(tmp_path):
    from crest_ais.analysis import analyze
    plan = three_judge_plan()
    refused = [job["key"] for job in plan["jobs"]
               if job["judge"] == "anthropic" and job["pair_id"] == plan["jobs"][0]["pair_id"]]
    results = [row for row in results_for(plan, three_judge_winner) if row["key"] not in refused]
    declined = {key: {"kind": "refusal", "category": "bio", "cost_usd": 0.625} for key in refused}
    html = render(analyze(plan, results, declined=declined), tmp_path)
    progress = html.split('<section id="progress"', 1)[1].split("</section>", 1)[0]
    assert ("Claude Fable 5.1 refused, on safety grounds, to judge 1 paper pair. That pair is scored on the other "
            "two judges’ 4 votes, and nothing is filled in for the missing votes. Every request for the 2 refused "
            "judgments was billed: $1.25, included in the total.") in progress
    assert html.count("refused, on safety grounds") == 1 and html.count("nothing is filled in") == 1
    assert "That gives 6 votes per pair (4 for the pair Claude Fable 5.1 refused)." in html
    assert "Rows marked “Claude Fable 5.1 refused” have 4 votes instead of 6." in html
    assert html.count("Claude Fable 5.1 refused this pair") == 1
    visible = "".join(Document(html).text)
    assert "declin" not in visible and "anthropic" not in visible


def test_paper_records_and_judgment_identifiers_are_not_dumped(report, tmp_path):
    report["papers"][0].update(blinding_audit={"geometry": [[1, 2, 3, 4]]}, sha256="ab" * 32,
                               full_text_path="results/prepared/text/abc/full.txt")
    report["judgments"] = [judgment()]
    html = render(report, tmp_path)
    doc = Document(html)
    assert not any(tag in {"pre", "details"} and attrs.get("class") in {"paper-record", "judgment-record"}
                   for tag, attrs in doc.tags)
    assert "<pre" not in html and "Paper record" not in html and "Record identifiers" not in html
    assert "blinding_audit" not in html and "ab" * 32 not in html and "results/prepared" not in html
    # The judgment key stays available to auditors as an attribute, not as visible text.
    assert any(tag == "article" and attrs.get("data-key") == "j1" for tag, attrs in doc.tags)
    assert "Judgment: j1" not in html


def test_paper_notes_render_only_for_fields_the_record_carries(report, tmp_path):
    first, second = report["papers"]
    first.update(observed_artifact_issues=[{"type": "released_manuscript_template_placeholder", "text": "RESULTS HERE"}],
                 seed=2)
    second.update(human_setup_notes="Humans picked the workshop theme", seed=None,
                  observed_artifact_issues=[{"type": "other_issue", "text": "ignored"}])
    html = render(report, tmp_path)
    assert "The released PDF contains unfilled template text, such as “RESULTS HERE”." in html
    assert "Human setup: Humans picked the workshop theme." in html
    assert "Learning · run 2<small>" in html and "Optimization<small>" in html
    assert html.count('class="paper-note"') == 2 and "ignored" not in html


def test_wide_tables_have_a_scroll_cue_and_positioned_scroll_boxes(report, tmp_path):
    complete(report)
    html = render(report, tmp_path)
    assert html.count('class="scroll-hint"') == html.count('class="table-scroll')
    css = html.split("<style>", 1)[1].split("</style>", 1)[0]
    assert ".table-scroll{position:relative;" in css
    assert "position:sticky;left:0" in css
    assert "overscroll-behavior:contain" not in css.split("@media(hover:hover)")[0]

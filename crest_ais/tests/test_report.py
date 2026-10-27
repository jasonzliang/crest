"""Observable report behavior: incomplete evidence, links, and untrusted text."""

from copy import deepcopy
from html.parser import HTMLParser
from itertools import combinations, product
import json
import pytest


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
    assert "equal weight" in html.lower()
    assert "absolute" in html.lower()
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
    assert "66.2%" in table
    assert ">New<" not in table and ">Useful<" not in table and ">Surprising<" not in table
    assert "Unavailable" in table
    assert "vendor/actual-model-id" in table
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
    assert "Decisions used: 4 / 144 planned" in html
    assert "432" not in html


def test_total_cost_does_not_double_count_already_included_prior_requests(report, tmp_path):
    report["costs"].update(known_usd=13, current_run_known_usd=10,
                           prior_excluded_jobs=7, prior_excluded_known_usd=3)
    html = render(report, tmp_path)
    assert "$13.00" in html
    assert "$3.00" in html
    assert "7 prior discarded requests" in html
    assert "$16.00" not in html


def test_shared_site_navigation_and_current_document_titles_are_retained(report, tmp_path):
    html = render(report, tmp_path)
    doc = Document(html)
    assert any(tag == "header" and attrs.get("class") == "crest-site-header" for tag, attrs in doc.tags)
    assert "<h1>AI scientist comparison</h1>" in html
    links = [attrs["href"] for tag, attrs in doc.tags if tag == "a"]
    assert links[:5] == ["../README.html", "crest-guide.html", "deep-research-creativity.html",
                         "ai-scientist-creativity.html", "index.html"]


def test_main_reading_order_starts_with_progress_then_evidence_and_method(report, tmp_path):
    doc = Document(render(report, tmp_path))
    sections = [attrs["id"] for tag, attrs in doc.tags if tag == "section"]
    assert sections == ["progress", "overall", "matchups", "judges", "coverage", "method", "papers", "reasons"]


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
    assert "full-pool order remains uncertain" in html
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
    assert "vendor/actual-model-id" in table and "vendor/second-model" in table
    assert table.index("75.0%") < table.index("25.0%")
    assert "8 matched judge comparisons" in html
    assert "8 matched order comparisons" in html
    assert "16 overall judgments" in html
    assert "Agreement does not establish correctness" in html


def test_coverage_uses_counts_and_selection_shares_instead_of_duplicate_bars(report, tmp_path):
    html = render(report, tmp_path)
    assert "3.4%" in html and "50.0%" in html
    assert "31 eligible" in html and "35 downloaded" in html
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
    assert ("Diffusing Blame is retained in the archive" in coverage) is explanation_expected
    if explanation_expected:
        assert 'href="https://pub.sakana.ai/agentic-scientist/"' in coverage
        assert "substantial human guidance and manuscript revision" in coverage


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
    method = html.split('<section id="method"', 1)[1].split('</section>', 1)[0]
    assert method.index('id="concepts"') < method.index('<details>')


def test_extended_plan_displays_ten_pairs_and_240_votes_from_report_data(report, tmp_path):
    report["selection"]["pairs_per_matchup"] = 10
    report["coverage"].update(expected_pairs=60, complete_pairs=60, expected_jobs=240,
                              completed_jobs=240, usable_jobs=240, expected_decisions=240,
                              used_decisions=240)
    report["status"] = "complete"
    html = render(report, tmp_path)
    assert "up to 10 distinct paper pairs" in html
    assert "60 / 60" in html
    assert "240 / 240" in html


def test_post_result_extension_ranges_are_exploratory_without_false_confidence_claim(report, tmp_path):
    complete(report)
    report["uncertainty"] = {"confidence": None, "nominal_fixed_size_level": 0.95,
                             "inference_scope": "exploratory_fixed_size_reference",
                             "sequential_valid": False, "method": "Exploratory reference bounds"}
    html = render(report, tmp_path)
    assert "Exploratory reference range" in html
    assert "95% sampling range" not in html
    assert "after the initial results" in html
    assert "No confidence guarantee" in html


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


def pair_judgments(winners, *, paper_ids=("p1", "p2"), pair_id="pair1"):
    """Fixtures state physical winning papers independently of their A/B positions."""
    rows = []
    cells = [("judge-a", paper_ids), ("judge-a", paper_ids[::-1]),
             ("judge-b", paper_ids), ("judge-b", paper_ids[::-1])]
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
    assert "These columns are not the judge’s A/B labels." in html
    table = html.split('id="judgment-pair-table"', 1)[1].split('</table>', 1)[0]
    links = [attrs["href"] for tag, attrs in Document(table).tags if tag == "a"]
    assert "../crest_ais/data/one/first%20paper.pdf" in links
    assert "../crest_ais/data/v3/second.pdf" in links
    assert "two judges" in html and "both paper orders" in html
    assert "3–1 pair contributes 75%" in html


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
    assert "This completed comparison uses 2 papers selected from 31 eligible papers in a 35-paper archive." in html
    assert not any(attrs.get("class") in {"meta", "status"} for _, attrs in Document(html).tags)
    report["status"] = "partial"
    html = render(report, tmp_path)
    assert "This comparison is in progress" in html
    assert "This completed comparison uses" not in html


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
    assert "6 pairs · all possible pairs" in html


def test_unequal_matchup_renderer_preserves_supplied_macro_score(five_report, tmp_path):
    original = deepcopy(five_report)
    html = render(five_report, tmp_path)
    row = next(attrs for tag, attrs in Document(html).tags
               if tag == "div" and attrs.get("class") == "overall-row" and attrs.get("data-agent") == "sakana_ai_scientist_v2")
    assert row["data-score"] == "18.75"
    overall = html.split('<section id="overall"', 1)[1].split('</section>', 1)[0]
    assert "18.8%" in overall and "12.5%" not in overall
    assert "sampled pair counts differ" in overall
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

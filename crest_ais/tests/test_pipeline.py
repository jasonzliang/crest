"""Sampling, extraction, identities, and durable paid-work boundaries."""
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

from crest.cache import Cache
from crest_ais.catalog import prepare_catalog
from crest_ais.protocol import make_plan, plan_fingerprint, parse_verdict, SCHEMA
from crest_ais.pipeline import run_judging, save_plan


JUDGES = {"openai": {"model": "test-astra", "concurrency": 2},
          "gemini": {"model": "test-argon", "concurrency": 2}}
AGENTS = {name: name.upper() for name in "abcd"}
RUBRIC = "Choose one overall creativity winner considering New, Useful, and Surprising jointly."


def _catalog(tmp_path, counts=(3, 4, 2, 5)):
    papers = []
    for agent, count in zip(AGENTS, counts):
        for number in range(count):
            identity = f"{agent}:{number}"
            path = tmp_path / f"{agent}-{number}.txt"
            path.write_text(f"[Page 1]\nAbstract\nComplete manuscript {identity}.\n[Page 2]\nResults {identity}.")
            papers.append({"id": identity, "agent": agent, "title": "Repeated title",
                           "blind_text_path": path.name, "sha256": hashlib.sha256(identity.encode()).hexdigest(),
                           "eligible_primary": True, "pages": 2})
    return papers


def _plan(tmp_path, counts=(3, 4, 2, 5), **kwargs):
    kwargs.setdefault("pairs_per_matchup", 6)  # Explicit first-stage fixture, independent of current defaults.
    return make_plan(_catalog(tmp_path, counts), AGENTS, JUDGES, tmp_path, RUBRIC, **kwargs)


def _verdict():
    return {"reason": "A (page 1) has stronger overall creative quality than B (page 2), considering New, Useful, and Surprising jointly.", "winner": "A"}


def test_sampling_reproducible_independent_of_input_order_and_complete_design(tmp_path):
    catalog = _catalog(tmp_path)
    first = make_plan(catalog, AGENTS, JUDGES, tmp_path, RUBRIC, pairs_per_matchup=6)
    reverse = make_plan(list(reversed(catalog)), dict(reversed(list(AGENTS.items()))),
                        dict(reversed(list(JUDGES.items()))), tmp_path, RUBRIC, pairs_per_matchup=6)
    assert first["jobs"] == reverse["jobs"]
    assert first["strata"] == reverse["strata"]
    assert len(first["strata"]) == 6
    assert len(first["jobs"]) == 6 * 6 * 4
    assert len({job["key"] for job in first["jobs"]}) == len(first["jobs"])
    for pair_id in {job["pair_id"] for job in first["jobs"]}:
        jobs = [job for job in first["jobs"] if job["pair_id"] == pair_id]
        assert len(jobs) == 4
        assert {tuple(job["order"]) for job in jobs} == {tuple(jobs[0]["papers"]), tuple(reversed(jobs[0]["papers"]))}
        assert {job["judge"] for job in jobs} == set(JUDGES)
    assert all("page" in job["prompt"].lower() and "own" in job["prompt"].lower() for job in first["jobs"])


def test_pair_caps_do_not_downsample_large_pools(tmp_path):
    plan = _plan(tmp_path, counts=(1, 2, 3, 4), pairs_per_matchup=6)
    for stratum in plan["strata"]:
        a, b = stratum["agents"]
        expected = ("abcd".index(a) + 1) * ("abcd".index(b) + 1)
        assert stratum["population_pairs"] == expected
        assert stratum["sampled_pairs"] == min(6, expected)
    assert plan["selection"]["seed"] == 2026
    assert len(plan["jobs"]) == 4 * sum(s["sampled_pairs"] for s in plan["strata"])


def test_sampling_seed_changes_pairs_and_gives_all_pairs_positive_inclusion(tmp_path):
    catalog = _catalog(tmp_path, (2, 2, 2, 2))
    seen = set()
    selections = set()
    for seed in range(40):
        plan = make_plan(catalog, AGENTS, JUDGES, tmp_path, RUBRIC, pairs_per_matchup=1, seed=seed)
        pairs = {tuple(job["papers"]) for job in plan["jobs"]}
        seen.update(pairs)
        selections.add(tuple(sorted(pairs)))
    assert len(selections) > 1
    assert len(seen) == 6 * 4


def test_keys_change_for_content_rubric_or_settings(tmp_path):
    catalog = _catalog(tmp_path, (1, 1, 1, 1))
    base = make_plan(catalog, AGENTS, JUDGES, tmp_path, RUBRIC)
    changed_rubric = make_plan(catalog, AGENTS, JUDGES, tmp_path, RUBRIC + " Cite evidence.")
    assert {j["key"] for j in base["jobs"]}.isdisjoint(j["key"] for j in changed_rubric["jobs"])
    (tmp_path / "a-0.txt").write_text("[Page 1]\nAbstract\nDifferent complete manuscript")
    changed_text = make_plan(catalog, AGENTS, JUDGES, tmp_path, RUBRIC)
    assert [j["key"] for j in base["jobs"] if "a" not in j["agents"]] == [j["key"] for j in changed_text["jobs"] if "a" not in j["agents"]]
    assert all(a["key"] != b["key"] for a, b in zip(base["jobs"], changed_text["jobs"]) if "a" in a["agents"])
    settings = {**JUDGES, "openai": {**JUDGES["openai"], "max_output_tokens": 10}}
    changed_settings = make_plan(catalog, AGENTS, settings, tmp_path, RUBRIC)
    assert all(a["key"] != b["key"] for a, b in zip(changed_text["jobs"], changed_settings["jobs"]) if a["judge"] == "openai")


def _pdf(root, relative, pages):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(50, 50, 550, 780), text, fontsize=10)
    doc.save(path)
    doc.close()
    return {"id": path.stem, "title": "Secret Research Title", "pdf_path": relative,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "topic": "ML"}


def _manifest(root, papers):
    directory = root / "data" / "scientistone"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "manifest.json").write_text(json.dumps({"agent_id": "scientistone", "display_name": "ScientistOne", "papers": papers}))


def test_default_plan_ignores_additional_collections(tmp_path):
    from crest_ais.cli import _new_plan
    from crest_ais.catalog import DEFAULT_AGENTS

    def add_collection(agent, number):
        relative = f"data/{agent}/paper.pdf"
        if agent == "sakana_ai_scientist_v2":
            # This collection deliberately requires an audited release hash.
            source = Path(__file__).resolve().parents[1] / "data" / agent / "pdfs" / "label-noise.pdf"
            path = tmp_path / relative
            path.parent.mkdir(parents=True)
            path.write_bytes(source.read_bytes())
            paper = {"id": "paper", "pdf_path": relative,
                     "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        else:
            paper = _pdf(tmp_path, relative,
                         [f"Abstract\nComplete research mechanism {number} and substantive experimental evidence."])
        manifest = {"agent_id": agent, "display_name": agent, "papers": [paper]}
        (tmp_path / "data" / agent / "manifest.json").write_text(json.dumps(manifest))

    for number, agent in enumerate(DEFAULT_AGENTS):
        add_collection(agent, number)
    config = {"data_root": tmp_path, "judges": JUDGES,
              "rubric": Path(__file__).resolve().parents[1] / "prompts" / "rubric_v2.txt"}
    args = SimpleNamespace(pairs_per_matchup=None, seed=None)
    baseline = _new_plan(config, args)

    add_collection("additional_scientist", 5)
    plan = _new_plan(config, args)

    assert set(plan["agents"]) == {"scientistone", "scientisttwo", "sakana_ai_scientist",
                                   "sakana_ai_scientist_v2", "sakana_agentic_scientist"}
    assert len(plan["catalog"]) == 5
    assert plan["selection"] == baseline["selection"]
    assert plan["fingerprint"] == baseline["fingerprint"]


def test_pdf_validation_blinding_and_complete_page_text(tmp_path):
    paper = _pdf(tmp_path, "data/scientistone/paper.pdf", [
        "Secret Research Title\nScientistOne Team\nAbstract\nA unique mechanism.\n1 Introduction\nFull introduction.",
        "2 Results\nAll of these results must survive.\nReferences\nA reference."])
    _manifest(tmp_path, [paper])
    catalog = prepare_catalog(tmp_path)
    assert len(catalog) == 1
    row = catalog[0]
    assert row["id"] == "scientistone:paper"
    assert row["eligible_primary"] is True
    assert row["pages"] == 2
    full = (tmp_path / row["full_text_path"]).read_text()
    blinded = (tmp_path / row["blind_text_path"]).read_text()
    assert "Secret Research Title" in full
    assert "Secret Research Title" not in blinded
    assert "ScientistOne Team" not in blinded
    assert "[Page 1]" in blinded and "[Page 2]" in blinded
    assert "All of these results must survive." in blinded and "A reference." in blinded
    assert "Abstract" in blinded
    again = prepare_catalog(tmp_path)
    assert again[0]["blind_text_path"] == row["blind_text_path"]


def test_catalog_rejects_escaping_paths_and_hash_mismatch(tmp_path):
    paper = _pdf(tmp_path, "data/scientistone/paper.pdf", ["Abstract\nA complete scientific proposal with evidence and mechanism."])
    _manifest(tmp_path, [{**paper, "pdf_path": "../escape.pdf"}])
    with pytest.raises(ValueError, match="outside|escape"):
        prepare_catalog(tmp_path)
    _manifest(tmp_path, [{**paper, "sha256": "0" * 64}])
    with pytest.raises(ValueError, match="SHA|hash"):
        prepare_catalog(tmp_path)


def test_catalog_keeps_repeated_titles_and_excludes_human_collaboration(tmp_path):
    first = _pdf(tmp_path, "data/scientistone/one.pdf", ["Abstract\nFirst autonomous scientific paper and its substantive mechanism."])
    second = _pdf(tmp_path, "data/scientistone/two.pdf", ["Abstract\nSecond different scientific paper and novel experimental evidence."])
    human = _pdf(tmp_path, "data/scientistone/human.pdf", ["Abstract\nHuman and agent joint discovery with substantial human assistance."])
    human["human_assistance"] = "substantial"
    human["generation_mode"] = "human_agent_co_discovery"
    _manifest(tmp_path, [first, second, human])
    catalog = prepare_catalog(tmp_path)
    assert sum(p["eligible_primary"] for p in catalog) == 2
    assert next(p for p in catalog if p["id"].endswith(":human"))["eligible_primary"] is False


def test_plan_snapshot_is_immutable(tmp_path):
    plan = _plan(tmp_path, (1, 1, 1, 1))
    run_dir = tmp_path / "run"
    save_plan(plan, run_dir)
    save_plan(plan, run_dir)
    changed = json.loads(json.dumps(plan))
    changed["seed"] = 1
    with pytest.raises(ValueError, match="immutable|different"):
        save_plan(changed, run_dir)
    assert json.loads((run_dir / "plan.json").read_text()) == plan


def test_mocked_resume_caches_results_and_failed_paid_output(tmp_path):
    plan = _plan(tmp_path, (1, 1, 1, 1))
    calls = []
    async def judge(prompt, settings, job):
        calls.append(job.key)
        if len(calls) == 1:
            return {"text": "invalid JSON", "raw": {"paid": True}, "cost_usd": .02, "usage": {}, "model": "mock"}
        return {"text": json.dumps(_verdict()), "raw": {"paid": True}, "cost_usd": .01, "usage": {}, "model": "mock"}
    providers = {name: SimpleNamespace(judge=judge) for name in JUDGES}
    run_dir = tmp_path / "run"
    results = asyncio.run(run_judging(plan, run_dir, providers=providers, progress=False))
    assert len(results) == len(plan["jobs"]) - 1
    assert len(calls) == len(plan["jobs"])
    resumed = asyncio.run(run_judging(plan, run_dir, providers=providers, progress=False))
    assert resumed == results
    assert len(calls) == len(plan["jobs"])
    failure = json.loads((run_dir / "failures.json").read_text())[0]
    assert failure["cost_usd"] == .02
    assert failure["status"] == "invalid_verdict"
    state = Cache(run_dir / ".cache" / "judgments").job(failure["key"]).state
    assert state["result"]["raw"] == {"paid": True}
    assert state["result"]["text"] == "invalid JSON"


def test_unknown_submission_is_not_resubmitted(tmp_path):
    plan = _plan(tmp_path, (1, 1, 1, 1))
    cache = Cache(tmp_path / "run" / ".cache" / "judgments")
    key = plan["jobs"][0]["key"]
    cache.job(key).save(status="running", submission_unknown=True)
    calls = []
    async def judge(prompt, settings, job):
        calls.append(job.key)
        return {"text": json.dumps(_verdict()), "cost_usd": .01, "usage": {}, "model": "mock"}
    results = asyncio.run(run_judging(plan, tmp_path / "run", providers={name: SimpleNamespace(judge=judge) for name in JUDGES}, progress=False))
    assert key not in calls
    assert len(results) == len(plan["jobs"]) - 1
    assert cache.job(key).state["submission_unknown"] is True


def test_observed_spend_stops_dispatch_and_counts_invalid_paid_outputs(tmp_path):
    plan = _plan(tmp_path, (1, 1, 1, 1))
    for job in plan["jobs"]:
        job["settings"]["concurrency"] = 1
    plan["fingerprint"] = plan_fingerprint(plan)
    calls = []
    async def judge(prompt, settings, job):
        calls.append(job.key)
        return {"text": "paid but invalid", "cost_usd": .2, "usage": {}, "model": "mock"}
    asyncio.run(run_judging(plan, tmp_path / "run", providers={name: SimpleNamespace(judge=judge) for name in JUDGES}, progress=False, max_spend_usd=.1))
    assert len(calls) <= 2
    summary = json.loads((tmp_path / "run" / "judging.json").read_text())
    assert summary["known_usd"] >= .2
    assert summary["deferred_jobs"] > 0


def test_frozen_schema_and_parser_are_independent_of_root_judging():
    assert set(SCHEMA["properties"]) == {"reason", "winner"}
    assert parse_verdict(json.dumps(_verdict())) == _verdict()
    with pytest.raises(ValueError):
        parse_verdict(json.dumps({name: {"reason": "Legacy independent criterion", "winner": "A"} for name in ("new", "useful", "surprising")}))
    with pytest.raises(ValueError, match="duplicate"):
        parse_verdict('{"reason":"first","reason":"second","winner":"A"}')
    from crest_ais.providers.openai import _payload
    payload = _payload("prompt", {"model": "test"}, True)
    assert payload["text"]["format"]["schema"] == SCHEMA
    assert "tools" not in payload


def test_edited_frozen_plan_is_rejected_before_provider_calls(tmp_path):
    plan = _plan(tmp_path, (1, 1, 1, 1))
    plan["jobs"][0]["prompt"] += " modified"
    with pytest.raises(ValueError, match="fingerprint"):
        asyncio.run(run_judging(plan, tmp_path / "run", providers={}, progress=False))


def test_known_remote_retrieval_can_resume_after_transport_failure(tmp_path):
    plan = _plan(tmp_path, (1, 1, 1, 1))
    key = plan["jobs"][0]["key"]
    calls = []
    async def judge(prompt, settings, job):
        calls.append(job.key)
        if job.key == key and not job.state.get("remote_id"):
            job.save(remote_id="already-paid", remote_status="in_progress", submission_unknown=False)
            raise ConnectionError("poll interrupted")
        return {"text": json.dumps(_verdict()), "cost_usd": .01, "usage": {}, "model": "mock"}
    providers = {name: SimpleNamespace(judge=judge) for name in JUDGES}
    run_dir = tmp_path / "run"
    results = asyncio.run(run_judging(plan, run_dir, providers=providers, progress=False))
    assert len(results) == len(plan["jobs"]) - 1
    assert Cache(run_dir / ".cache" / "judgments").job(key).state["status"] == "pending_retrieval"
    resumed = asyncio.run(run_judging(plan, run_dir, providers=providers, progress=False))
    assert len(resumed) == len(plan["jobs"])
    assert calls.count(key) == 2
    assert all(calls.count(task["key"]) == 1 for task in plan["jobs"] if task["key"] != key)


def test_unlabeled_abstract_preserves_summary_after_recognized_author(tmp_path):
    paper = _pdf(tmp_path, "data/scientistone/anonymous.pdf", [
        "Secret Research Title\nThe Agentic Scientist System\nAn unlabeled abstract describing the full research mechanism and evidence.\nIntroduction\nEntire opening discussion."])
    _manifest(tmp_path, [paper])
    row = prepare_catalog(tmp_path)[0]
    text = (tmp_path / row["blind_text_path"]).read_text()
    assert "Secret Research Title" not in text
    assert "Agentic Scientist" not in text
    assert "An unlabeled abstract" in text and "Entire opening discussion." in text
    assert row["blinding_audit"]["preamble_removed"] is True


def test_gemini_judge_uses_frozen_schema_without_tools(monkeypatch):
    from crest_ais.providers import gemini
    seen = []
    async def capture(body, settings, job, client, *, research):
        seen.append((body, research))
        return {"text": json.dumps(_verdict())}
    monkeypatch.setattr(gemini, "_run", capture)
    asyncio.run(gemini.judge("paper comparison", {"model": "gemini-4-argon"}, None))
    body, research = seen[0]
    assert body["response_format"]["schema"] == SCHEMA
    assert research is False
    assert "tools" not in body


def test_report_costs_include_failed_paid_outputs(tmp_path):
    from crest_ais.cli import _report
    plan = _plan(tmp_path, (1, 1, 1, 1))
    calls = []
    async def judge(prompt, settings, job):
        calls.append(job.key)
        return {"text": "invalid" if len(calls) == 1 else json.dumps(_verdict()),
                "cost_usd": .25 if len(calls) == 1 else .01, "usage": {}, "model": "mock"}
    run_dir = tmp_path / "run"
    asyncio.run(run_judging(plan, run_dir, providers={name: SimpleNamespace(judge=judge) for name in JUDGES}, progress=False))
    report = _report(plan, run_dir, tmp_path, run_dir / "report.html")
    assert report["costs"]["known_usd"] == pytest.approx(.25 + .01 * (len(plan["jobs"]) - 1))
    assert report["costs"]["failed_known_usd"] == .25
    assert report["costs"]["successful_known_usd"] == pytest.approx(.01 * (len(plan["jobs"]) - 1))
    assert report["status"] == "partial"


def test_empty_pdf_and_duplicate_bytes_are_retained_but_ineligible(tmp_path):
    paper = _pdf(tmp_path, "data/scientistone/one.pdf", ["Abstract\nA substantive mechanism with complete experimental evidence and analysis."])
    duplicate = {**paper, "id": "two"}
    empty = _pdf(tmp_path, "data/scientistone/empty.pdf", [""])
    _manifest(tmp_path, [paper, duplicate, empty])
    catalog = prepare_catalog(tmp_path)
    assert len(catalog) == 3
    assert sum(p["eligible_primary"] for p in catalog) == 1
    assert next(p for p in catalog if p["source_id"] == "two")["duplicate_of"] == "scientistone:one"
    assert any("extractable" in reason for p in catalog if p["source_id"] == "empty" for reason in p["exclusion_reasons"])


@pytest.mark.parametrize("latest", [
    {"model": "gpt-6-astra", "status": "cancelled", "usage": None},
    {"model": "gpt-6-astra", "status": "cancelled", "usage": {
        "input_tokens": 100, "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
        "output_tokens": 10}},
])
def test_cancellation_accounting_preserves_maximum_known_cost_and_usage(latest):
    from crest_ais.pipeline import _account
    observed_usage = {"input_tokens": 100000, "output_tokens": 170000}
    account = _account({"observed_cost_usd": 9.5, "observed_usage": observed_usage,
                        "raw": latest}, "openai", {"model": "gpt-6-astra"})
    assert account["cost_usd"] == 9.5
    assert account["usage"] == observed_usage


def test_result_accounting_preserves_larger_prior_observation():
    from crest_ais.pipeline import _account
    observed_usage = {"input_tokens": 100000, "output_tokens": 170000}
    account = _account({"observed_cost_usd": 9.5, "observed_usage": observed_usage,
                        "result": {"cost_usd": .5, "usage": {"output_tokens": 100}, "model": "gpt-6-astra"}},
                       "openai", {"model": "gpt-6-astra"})
    assert account["cost_usd"] == 9.5
    assert account["usage"] == observed_usage


def test_cancellation_can_recover_known_cost_from_pre_cancel_raw():
    from crest_ais.pipeline import _account
    account = _account({"pre_cancel_raw": {"model": "gpt-6-astra", "usage": {
        "input_tokens": 100, "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
        "output_tokens": 10}}, "raw": {"model": "gpt-6-astra", "status": "cancelled", "usage": None}},
        "openai", {"model": "gpt-6-astra"})
    assert account["cost_usd"] == pytest.approx(.0015)
    assert account["usage"]["input_tokens"] == 100
    assert account["usage"]["output_tokens"] == 10


def test_cancelled_known_spend_still_guards_dispatch_and_reaches_report(tmp_path):
    from crest_ais.cli import _report
    plan = _plan(tmp_path, (1, 1, 1, 1))
    run_dir = tmp_path / "run"
    task = next(task for task in plan["jobs"] if task["judge"] == "openai")
    Cache(run_dir / ".cache" / "judgments").job(task["key"]).save(
        status="failed", observed_cost_usd=9.5,
        observed_usage={"input_tokens": 100000, "output_tokens": 170000},
        remote_id="paid-cancelled", raw={"model": "gpt-6-astra", "status": "cancelled", "usage": None})
    async def judge(prompt, settings, job):
        pytest.fail("Known observed spend already exceeds the dispatch target")
    results = asyncio.run(run_judging(plan, run_dir,
        providers={name: SimpleNamespace(judge=judge) for name in JUDGES},
        progress=False, max_spend_usd=9))
    assert results == []
    summary = json.loads((run_dir / "judging.json").read_text())
    assert summary["known_usd"] == 9.5
    assert summary["deferred_jobs"] == len(plan["jobs"]) - 1
    report = _report(plan, run_dir, tmp_path, run_dir / "report.html")
    assert report["costs"]["known_usd"] == 9.5
    assert report["costs"]["failed_known_usd"] == 9.5


def test_geometry_filter_removes_diagonal_provenance_without_losing_body_or_rotated_plot_text(tmp_path):
    from crest_ais.catalog import _clean_page
    path = tmp_path / "watermarked.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((80, 40), "AI-Scientist Generated Preprint", fontsize=10)
    page.insert_text((80, 100), "Abstract", fontsize=12)
    page.insert_text((80, 370), "A scientific mechanism improves validation accuracy by 17 percent.", fontsize=10)
    page.insert_text((80, 410), "METHOD HERE", fontsize=10)
    page.insert_text((80, 450), "The algorithm preserves gradient stability and reduces memory.", fontsize=10)
    page.insert_text((70, 700), "Validation loss axis", fontsize=10, rotate=90)
    for offset, text in enumerate(("CAUTION!!!", "THIS PAPER WAS", "AUTONOMOUSLY GENERATED", "BY THE AI SCIENTIST")):
        point = fitz.Point(150, 330 + offset * 50)
        page.insert_text(point, text, fontsize=32, morph=(point, fitz.Matrix(30)), color=(.8, .8, .8))
    document.save(path)
    document.close()
    with fitz.open(path) as document:
        page = document[0]
        raw = page.get_text("text", sort=True)
        cleaned, audit = _clean_page(page)
        assert "CAUTION" in raw
        assert "CAUTION" not in cleaned and "AUTONOMOUSLY" not in cleaned
        assert "Generated Preprint" not in cleaned
        assert "A scientific mechanism improves validation accuracy by 17 percent." in cleaned
        assert "The algorithm preserves gradient stability and reduces memory." in cleaned
        assert "METHOD HERE" in cleaned
        kept_words = cleaned.split()
        assert all(word in kept_words for word in ("Validation", "loss", "axis"))
        assert len(audit["removed_lines"]) == 5
        assert audit["raw_word_count"] == audit["kept_word_count"] + audit["removed_word_count"]
        assert all("direction" in entry and "bbox" in entry and "spans" in entry for entry in audit["removed_lines"])


def test_no_watermark_leaves_extraction_identical_and_does_not_remove_rotated_science(tmp_path):
    from crest_ais.catalog import _clean_page
    paper = _pdf(tmp_path, "plain.pdf", ["Abstract\nA scientific mechanism with a substantive claim and complete evidence."])
    with fitz.open(tmp_path / paper["pdf_path"]) as document:
        page = document[0]
        page.insert_text((70, 700), "AUTONOMOUSLY GENERATED samples", fontsize=10, rotate=90)
        original = page.get_text("text", sort=True)
        cleaned, audit = _clean_page(page)
        assert cleaned == original
        assert audit["removed_lines"] == []


def test_real_released_v1_watermarks_are_removed_and_source_placeholders_remain_eligible(tmp_path):
    from crest_ais.catalog import _clean_page, _blinded_pages
    root = Path(__file__).resolve().parents[1]
    manifest_path = root / "data" / "sakana_ai_scientist" / "manifest.json"
    if not manifest_path.exists():
        pytest.skip("Official released corpus not present")
    manifest = json.loads(manifest_path.read_text())
    source = next(paper for paper in manifest["papers"] if paper["id"] == "sakana_v1_drive_12_q1atZYv0XvZ5OePjhCI__mC3k2Sb7m")
    with fitz.open(root / source["pdf_path"]) as document:
        cleaned = []
        for page in document:
            text, audit = _clean_page(page)
            cleaned.append(text)
            watermark = [entry for entry in audit["removed_lines"] if entry["kind"] == "diagonal_generation_watermark"]
            assert len(watermark) == 4
        blind, _, _ = _blinded_pages(cleaned, source)
    text = "\n".join(blind)
    assert "CAUTION" not in text and "AUTONOMOUSLY" not in text
    assert "Generated Preprint" not in text
    assert "METHOD HERE" in text and "RESULTS HERE" in text
    # Reproduce actual released bytes in a minimal catalog: unfinished sections
    # are artifact defects to disclose, not grounds for post-score exclusion.
    target = tmp_path / "data" / "scientistone" / "paper.pdf"
    target.parent.mkdir(parents=True)
    target.write_bytes((root / source["pdf_path"]).read_bytes())
    _manifest(tmp_path, [{**source, "pdf_path": "data/scientistone/paper.pdf"}])
    row = prepare_catalog(tmp_path)[0]
    assert row["eligible_primary"] is True
    assert any("METHOD HERE" in str(issue) for issue in row["observed_artifact_issues"])
    assert row["cleaned_text_path"]
    assert "CAUTION" in (tmp_path / row["full_text_path"]).read_text()
    assert "CAUTION" not in (tmp_path / row["cleaned_text_path"]).read_text()


def test_superseded_run_refuses_all_dispatch_and_points_to_replacement(tmp_path):
    plan = _plan(tmp_path, (1, 1, 1, 1))
    run_dir = tmp_path / "old-run"
    save_plan(plan, run_dir)
    replacement = str(tmp_path / "corrected-run")
    (run_dir / "superseded.json").write_text(json.dumps({
        "reason": "PDF watermark contaminated scientific text", "replacement_run_dir": replacement}))
    async def judge(prompt, settings, job):
        pytest.fail("Superseded jobs must never dispatch")
    with pytest.raises(ValueError, match="superseded") as captured:
        asyncio.run(run_judging(plan, run_dir,
            providers={name: SimpleNamespace(judge=judge) for name in JUDGES}, progress=False))
    assert replacement in str(captured.value)


def test_superseded_marker_created_during_run_blocks_later_dispatch(tmp_path):
    plan = _plan(tmp_path, (1, 1, 1, 1))
    run_dir = tmp_path / "run"
    calls = []
    async def judge(prompt, settings, job):
        calls.append(job.key)
        (run_dir / "superseded.json").write_text(json.dumps({"reason": "Corrected inputs", "replacement_run": "corrected-run"}))
        return {"text": json.dumps(_verdict()), "cost_usd": .01, "usage": {}, "model": "mock"}
    with pytest.raises(ValueError, match="superseded"):
        asyncio.run(run_judging(plan, run_dir,
            providers={name: SimpleNamespace(judge=judge) for name in JUDGES}, progress=False))
    assert len(calls) == 1


@pytest.mark.parametrize("override,expected", [(None, 2), (1, 1), (2, 2), (4, 4), (16, 16)])
def test_worker_override_is_operational_bounded_and_preserves_resume(tmp_path, override, expected):
    plan = _plan(tmp_path, (2, 2, 2, 2) if override == 16 else (1, 1, 1, 1))
    before = json.dumps(plan, sort_keys=True)
    run_dir = tmp_path / "run"
    existing = plan["jobs"][0]
    Cache(run_dir / ".cache" / "judgments").job(existing["key"]).save(
        status="running", remote_id="already-submitted", remote_status="in_progress")
    active = {name: 0 for name in JUDGES}
    maximum = {name: 0 for name in JUDGES}
    calls = []
    def provider(name):
        async def judge(prompt, settings, job):
            calls.append(job.key)
            active[name] += 1
            maximum[name] = max(maximum[name], active[name])
            if job.key == existing["key"]:
                assert job.state["remote_id"] == "already-submitted"
            assert settings == plan["judges"][name]
            try:
                await asyncio.sleep(.001)
                return {"text": json.dumps(_verdict()), "cost_usd": .01, "usage": {}, "model": "mock"}
            finally:
                active[name] -= 1
        return SimpleNamespace(judge=judge)
    providers = {name: provider(name) for name in JUDGES}
    first = asyncio.run(run_judging(plan, run_dir, providers=providers, progress=False,
                                   workers_per_judge=override))
    assert maximum == {name: expected for name in JUDGES}
    assert len(first) == len(plan["jobs"]) == len(calls)
    summary = json.loads((run_dir / "judging.json").read_text())
    assert summary["effective_worker_counts"] == {name: expected for name in JUDGES}
    assert "operational" in summary["worker_note"].lower()
    frozen_bytes = (run_dir / "plan.json").read_bytes()
    resumed = asyncio.run(run_judging(plan, run_dir, providers=providers, progress=False, workers_per_judge=1))
    assert resumed == first
    assert len(calls) == len(plan["jobs"])
    assert before == json.dumps(plan, sort_keys=True)
    assert frozen_bytes == (run_dir / "plan.json").read_bytes()


@pytest.mark.parametrize("invalid", [0, -1, 17, True, 2.5, "4"])
def test_worker_override_rejects_values_outside_integer_one_to_sixteen(tmp_path, invalid):
    plan = _plan(tmp_path, (1, 1, 1, 1))
    with pytest.raises(ValueError, match="workers_per_judge"):
        asyncio.run(run_judging(plan, tmp_path / "run", providers={}, progress=False, workers_per_judge=invalid))


def test_report_includes_prior_excluded_spend_without_counting_prior_judgments(tmp_path):
    from crest_ais.cli import _report
    plan = _plan(tmp_path, (1, 1, 1, 1))
    run_dir = tmp_path / "run"
    async def judge(prompt, settings, job):
        return {"text": json.dumps(_verdict()), "cost_usd": .01, "usage": {}, "model": "mock"}
    asyncio.run(run_judging(plan, run_dir, providers={name: SimpleNamespace(judge=judge) for name in JUDGES}, progress=False))
    prior = {"source_run": "superseded-run", "known_usd": 2.383585, "unknown_jobs": 2,
             "job_count": 12, "reason": "Contaminated inputs excluded from rankings"}
    (run_dir / "prior_costs.json").write_text(json.dumps(prior))
    report = _report(plan, run_dir, tmp_path, run_dir / "report.html")
    assert report["costs"]["known_usd"] == pytest.approx(.01 * len(plan["jobs"]) + prior["known_usd"])
    assert report["costs"]["unknown_jobs"] == 2
    assert report["costs"]["prior_excluded_jobs"] == 12
    assert report["costs"]["prior_excluded_known_usd"] == prior["known_usd"]
    assert report["costs"]["current_run_known_usd"] == pytest.approx(.01 * len(plan["jobs"]))
    assert report["coverage"]["completed_jobs"] == len(plan["jobs"])
    assert report["costs"]["completed_jobs"] == len(plan["jobs"])
    assert len(report["judgments"]) == len(plan["jobs"])
    assert any("12" in note and "excluded" in note for note in report["limitations"])
    # Regenerating a report never adds the same prior ledger twice.
    repeated = _report(plan, run_dir, tmp_path, run_dir / "report.html")
    assert repeated["costs"] == report["costs"]


@pytest.mark.parametrize("option", [[], ["--workers-per-judge", "4"]])
def test_cli_forwards_operational_worker_override_without_changing_plan(tmp_path, monkeypatch, option):
    from crest_ais import cli
    plan = _plan(tmp_path, (1, 1, 1, 1))
    run_dir = tmp_path / "run"
    save_plan(plan, run_dir)
    frozen_bytes = (run_dir / "plan.json").read_bytes()
    monkeypatch.setattr(cli, "load_config", lambda path, *, data_root: {
        "data_root": tmp_path, "output_dir": tmp_path / "results", "max_spend_usd": 100})
    received = []
    async def judge(plan_arg, run_arg, **kwargs):
        assert plan_arg == plan
        received.append(kwargs["workers_per_judge"])
        return []
    monkeypatch.setattr(cli, "run_judging", judge)
    assert cli.main(["judge", "--run-dir", str(run_dir), "--quiet", *option]) == 0
    assert received == [4 if option else None]
    assert (run_dir / "plan.json").read_bytes() == frozen_bytes


def test_overall_protocol_freezes_current_crest_semantics_and_invalidates_all_old_jobs():
    from crest_ais.protocol import PROTOCOL_VERSION, JUDGING_VERSION, SAMPLING_VERSION, build_prompt
    from crest import judging as root_judging
    from crest.presentation import present_answer
    root = Path(__file__).resolve().parents[1]
    frozen = root / "results" / "20261027T022556.099871Z-aebd5e09" / "plan.json"
    if not frozen.exists():
        pytest.skip("Frozen corrected v1 plan not present")
    old = json.loads(frozen.read_text())
    rubric = (root / "prompts" / "rubric_v2.txt").read_text()
    assert rubric == (root.parent / "crest" / "prompts" / "nus_pairwise_v2.txt").read_text()
    assert PROTOCOL_VERSION == "crest-ais-overall-v3"
    assert JUDGING_VERSION == root_judging.PROTOCOL_VERSION == "nus-overall-pairwise-v3"
    assert SAMPLING_VERSION == "crest-ais-v1"
    assert SCHEMA == root_judging.SCHEMA
    assert build_prompt("question", "paper A", "paper B", "rubric") == root_judging.build_prompt("question", "paper A", "paper B", "rubric")
    new = make_plan(old["catalog"], old["agents"], old["judges"], root, rubric,
                    pairs_per_matchup=old["pairs_per_matchup"], seed=old["seed"])
    assert new["strata"] == old["strata"]
    assert new["selection"] == old["selection"]
    assert new["catalog"] == old["catalog"]
    assert new["papers"] == old["papers"]
    assert len(new["jobs"]) == len(old["jobs"]) == 144
    assert {job["key"] for job in new["jobs"]}.isdisjoint(job["key"] for job in old["jobs"])
    for previous, job in zip(old["jobs"], new["jobs"]):
        assert {key: previous[key] for key in ("pair_id", "agents", "papers", "order", "judge", "settings")} == {key: job[key] for key in ("pair_id", "agents", "papers", "order", "judge", "settings")}
        assert "Make one overall A or B choice" in job["prompt"]
        assert "Choose A or B independently" not in job["prompt"]
        encoded = job["prompt"].split("UNTRUSTED INPUT DATA (JSON):\n", 1)[1]
        data = json.loads(encoded)
        assert data["A"] == present_answer((root / next(paper["blind_text_path"] for paper in new["papers"] if paper["id"] == job["order"][0])).read_text())
        assert data["B"] == present_answer((root / next(paper["blind_text_path"] for paper in new["papers"] if paper["id"] == job["order"][1])).read_text())


@pytest.mark.parametrize("verdict", [{"reason":" ","winner":"A"}, {"reason":"reason","winner":"tie"},
    {"reason":"reason","winner":"A","new":"A"}, {"winner":"A"}])
def test_overall_parser_rejects_empty_partial_and_additional_fields(verdict):
    with pytest.raises(ValueError):
        parse_verdict(json.dumps(verdict))


def test_legacy_three_verdict_plan_cannot_dispatch_under_overall_protocol(tmp_path):
    plan = _plan(tmp_path, (1, 1, 1, 1))
    plan["version"] = "crest-ais-v1"
    plan["fingerprint"] = plan_fingerprint(plan)
    async def judge(prompt, settings, job):
        pytest.fail("Legacy nested-verdict prompts must be replanned before new judging")
    with pytest.raises(ValueError, match="protocol|version"):
        asyncio.run(run_judging(plan, tmp_path / "run", providers={name: SimpleNamespace(judge=judge) for name in JUDGES}, progress=False))


def test_extension_preserves_initial_draw_and_adds_only_unused_uniform_pairs(tmp_path):
    from crest_ais.protocol import extend_plan, validate_plan_fingerprint
    parent = _plan(tmp_path, (3, 3, 3, 3), pairs_per_matchup=1)
    extended = extend_plan(parent, tmp_path, pairs_per_matchup=3, extension_seed=2026, parent_run_dir="parent-run")
    validate_plan_fingerprint(extended)
    assert extended["jobs"][:len(parent["jobs"])] == parent["jobs"]
    assert extended["catalog"] == parent["catalog"] and extended["rubric"] == parent["rubric"]
    assert extended["judges"] == parent["judges"]
    assert len(extended["jobs"]) == 6 * 3 * 4
    assert len({job["key"] for job in extended["jobs"]}) == len(extended["jobs"])
    assert extended["extension"]["parent_fingerprint"] == parent["fingerprint"]
    assert extended["extension"]["original_pairs"] == 6
    assert extended["extension"]["additional_pairs"] == 12
    assert extended["extension"]["stage"] == "post_initial_results"
    repeated = extend_plan(parent, tmp_path, pairs_per_matchup=3, extension_seed=2026, parent_run_dir="parent-run")
    assert extended["fingerprint"] == repeated["fingerprint"]
    assert all(s["sampled_pairs"] == 3 for s in extended["strata"])
    initial = {tuple(job["papers"]) for job in parent["jobs"]}
    seen = set()
    for seed in range(60):
        draw = extend_plan(parent, tmp_path, pairs_per_matchup=3, extension_seed=seed)
        seen.update(tuple(job["papers"]) for job in draw["jobs"] if tuple(job["papers"]) not in initial)
    assert len(seen) == 6 * (9 - 1)


def test_extension_caps_small_populations_and_rejects_changed_frozen_text(tmp_path):
    from crest_ais.protocol import extend_plan
    parent = _plan(tmp_path, (1, 1, 2, 2), pairs_per_matchup=1)
    extended = extend_plan(parent, tmp_path, pairs_per_matchup=10)
    assert all(s["sampled_pairs"] == min(10, s["population_pairs"]) for s in extended["strata"])
    assert extended["extension"]["additional_pairs"] == sum(s["sampled_pairs"] for s in extended["strata"]) - 6
    with pytest.raises(ValueError, match="target|pairs_per_matchup"):
        extend_plan(parent, tmp_path, pairs_per_matchup=0)
    for paper in parent["catalog"]:
        paper["blind_text_sha256"] = hashlib.sha256((tmp_path / paper["blind_text_path"]).read_bytes()).hexdigest()
    parent["fingerprint"] = plan_fingerprint(parent)
    (tmp_path / "a-0.txt").write_text("Changed source content")
    with pytest.raises(ValueError, match="hash|SHA"):
        extend_plan(parent, tmp_path, pairs_per_matchup=10)


def test_create_extension_reuses_paid_results_and_carries_prior_cost_once(tmp_path):
    from crest_ais.pipeline import create_extension
    from crest_ais.cli import _report
    parent = _plan(tmp_path, (3, 3, 3, 3), pairs_per_matchup=1)
    source = tmp_path / "source"
    destination = tmp_path / "extended"
    calls = []
    async def judge(prompt, settings, job):
        calls.append(job.key)
        return {"text": json.dumps(_verdict()), "cost_usd": .01, "usage": {}, "model": "mock"}
    providers = {name: SimpleNamespace(judge=judge) for name in JUDGES}
    initial = asyncio.run(run_judging(parent, source, providers=providers, progress=False))
    prior = {"known_usd": 13.873186, "unknown_jobs": 0, "job_count": 60, "source_run": "excluded", "reason": "Excluded prior attempts"}
    (source / "prior_costs.json").write_text(json.dumps(prior))
    extended = create_extension(source, destination, tmp_path, pairs_per_matchup=3)
    assert json.loads((destination / "results.json").read_text()) == initial
    assert json.loads((destination / "prior_costs.json").read_text()) == prior
    assert create_extension(source, destination, tmp_path, pairs_per_matchup=3) == extended
    first = asyncio.run(run_judging(extended, destination, providers=providers, progress=False, workers_per_judge=16))
    assert len(calls) == len(extended["jobs"])
    assert len(first) == len(extended["jobs"])
    assert all(calls.count(job["key"]) == 1 for job in parent["jobs"])
    report = _report(extended, destination, tmp_path, destination / "report.html")
    assert report["costs"]["known_usd"] == pytest.approx(.01 * len(extended["jobs"]) + prior["known_usd"])
    summary = json.loads((destination / "judging.json").read_text())
    assert summary["imported_jobs"] == len(parent["jobs"])
    assert summary["newly_completed_jobs"] == len(extended["jobs"]) - len(parent["jobs"])
    resumed = asyncio.run(run_judging(extended, destination, providers=providers, progress=False, workers_per_judge=16))
    assert resumed == first and len(calls) == len(extended["jobs"])


def test_cli_extend_uses_frozen_parent_without_loading_current_judges(tmp_path, monkeypatch):
    from crest_ais import cli
    parent = _plan(tmp_path, (3, 3, 3, 3), pairs_per_matchup=1)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"data_root": ".", "output_dir": "results"}))
    source, destination = tmp_path / "source", tmp_path / "extension"
    captured = []
    def create(source_arg, run_arg, root_arg, **kwargs):
        captured.append((source_arg, run_arg, root_arg, kwargs))
        return {**parent, "extension": {"original_pairs": 6, "additional_pairs": 12}}
    monkeypatch.setattr(cli, "create_extension", create, raising=False)
    monkeypatch.setattr(cli, "load_config", lambda *a, **kw: pytest.fail("Extension must use frozen parent settings"))
    assert cli.main(["extend", "--config", str(config), "--source-run", str(source), "--run-dir", str(destination)]) == 0
    assert captured == [(source.resolve(), destination.resolve(), tmp_path.resolve(), {"pairs_per_matchup": 10, "extension_seed": 2026})]


def test_new_plan_default_is_ten_pairs_per_matchup(tmp_path):
    catalog = _catalog(tmp_path, (4, 4, 4, 4))
    plan = make_plan(catalog, AGENTS, JUDGES, tmp_path, RUBRIC)
    assert plan["pairs_per_matchup"] == 10
    assert all(stratum["sampled_pairs"] == 10 for stratum in plan["strata"])
    assert len(plan["jobs"]) == 240


def _completed_extension_parent(tmp_path):
    parent = _plan(tmp_path, (2, 2, 2, 2), pairs_per_matchup=1)
    source = tmp_path / "source"
    async def judge(prompt, settings, job):
        return {"text": json.dumps(_verdict()), "cost_usd": .01, "usage": {}, "model": "mock"}
    asyncio.run(run_judging(parent, source, providers={name: SimpleNamespace(judge=judge) for name in JUDGES}, progress=False))
    return parent, source


def test_extension_rejects_a_completed_superseded_source_before_publication(tmp_path):
    from crest_ais.pipeline import create_extension
    _, source = _completed_extension_parent(tmp_path)
    destination = tmp_path / "withdrawn-extension"
    (source / "superseded.json").write_text(json.dumps({"reason": "Invalid extraction", "replacement_run": "corrected"}))
    with pytest.raises(ValueError, match="superseded"):
        create_extension(source, destination, tmp_path, pairs_per_matchup=2)
    assert not (destination / "plan.json").exists()
    assert not (destination / "imported_results.json").exists()


@pytest.mark.parametrize("raw_output,cancel_output,expected", [(10, 1000, .012), (10, None, .0021), (10, 1, .0021), (None, 1000, .012)])
def test_gemini_cancellation_usage_is_a_conservative_cost_candidate(raw_output, cancel_output, expected):
    from crest_ais.pipeline import _account
    def raw(output):
        return {"model": "gemini-4-argon", "created": "2026-10-26T12:00:00Z", "status": "cancelled",
                "usage": None if output is None else {"total_input_tokens": 1000, "total_cached_tokens": 0,
                    "total_output_tokens": output, "total_thought_tokens": 0,
                    "total_tool_use_tokens": 0, "grounding_tool_count": []}}
    account = _account({"raw": raw(raw_output), "cancellation": raw(cancel_output)}, "gemini", {"model": "gemini-4-argon"})
    assert account["cost_usd"] == pytest.approx(expected)
    assert account["usage"]["output_tokens"] == (1000 if cancel_output == 1000 else 10)


def test_extension_preparation_blocks_judging_and_concurrent_preparation(tmp_path, monkeypatch):
    from crest_ais import pipeline
    from crest_ais.protocol import extend_plan
    parent, source = _completed_extension_parent(tmp_path)
    destination = tmp_path / "extension"
    planned = extend_plan(parent, tmp_path, pairs_per_matchup=2, parent_run_dir=str(source.resolve()))
    calls = []
    async def judge(prompt, settings, job):
        calls.append(job.key)
        return {"text": json.dumps(_verdict()), "cost_usd": .02, "usage": {}, "model": "mock"}
    providers = {name: SimpleNamespace(judge=judge) for name in JUDGES}
    original_write = pipeline.write_json
    attempted = []
    def interleave(path, value):
        if not attempted and Path(path).name == "state.json" and Path(path).is_relative_to(destination):
            attempted.append(True)
            with pytest.raises(ValueError, match="prepar|ready|busy"):
                asyncio.run(run_judging(planned, destination, providers=providers, progress=False))
            with pytest.raises(ValueError, match="prepar|busy|judg"):
                pipeline.create_extension(source, destination, tmp_path, pairs_per_matchup=2)
            assert not calls
        original_write(path, value)
    monkeypatch.setattr(pipeline, "write_json", interleave)
    extended = pipeline.create_extension(source, destination, tmp_path, pairs_per_matchup=2)
    assert attempted == [True]
    results = asyncio.run(run_judging(extended, destination, providers=providers, progress=False))
    assert len(results) == len(extended["jobs"])
    assert len(calls) == len(extended["jobs"]) - len(parent["jobs"])
    assert not set(calls) & {job["key"] for job in parent["jobs"]}


def test_interrupted_extension_remains_undispatchable_and_preparation_resumes(tmp_path, monkeypatch):
    from crest_ais import pipeline
    from crest_ais.protocol import extend_plan
    parent, source = _completed_extension_parent(tmp_path)
    destination = tmp_path / "extension"
    planned = extend_plan(parent, tmp_path, pairs_per_matchup=2, parent_run_dir=str(source.resolve()))
    original_write = pipeline.write_json
    def interrupt(path, value):
        original_write(path, value)
        if Path(path).name == "state.json" and Path(path).is_relative_to(destination):
            raise RuntimeError("Simulated interruption during import")
    monkeypatch.setattr(pipeline, "write_json", interrupt)
    with pytest.raises(RuntimeError, match="interruption"):
        pipeline.create_extension(source, destination, tmp_path, pairs_per_matchup=2)
    assert not (destination / "plan.json").exists()
    async def no_dispatch(prompt, settings, job):
        pytest.fail("An interrupted preparation cannot dispatch")
    providers = {name: SimpleNamespace(judge=no_dispatch) for name in JUDGES}
    with pytest.raises(ValueError, match="prepar|ready"):
        asyncio.run(run_judging(planned, destination, providers=providers, progress=False))
    monkeypatch.setattr(pipeline, "write_json", original_write)
    extended = pipeline.create_extension(source, destination, tmp_path, pairs_per_matchup=2)
    assert json.loads((destination / "extension_preparation.json").read_text())["status"] == "ready"
    assert json.loads((destination / "plan.json").read_text()) == extended
    assert len(json.loads((destination / "results.json").read_text())) == len(parent["jobs"])


def test_repeated_preparation_cannot_overwrite_active_judging(tmp_path):
    from crest_ais import pipeline
    parent, source = _completed_extension_parent(tmp_path)
    destination = tmp_path / "extension"
    extended = pipeline.create_extension(source, destination, tmp_path, pairs_per_matchup=2)
    attempted = []
    async def judge(prompt, settings, job):
        if not attempted:
            attempted.append(True)
            job.save(remote_id="active-paid-request", remote_status="in_progress")
            before = job.path.read_bytes()
            with pytest.raises(ValueError, match="busy|judg|prepar"):
                pipeline.create_extension(source, destination, tmp_path, pairs_per_matchup=2)
            assert job.path.read_bytes() == before
        return {"text": json.dumps(_verdict()), "cost_usd": .02, "usage": {}, "model": "mock"}
    results = asyncio.run(run_judging(extended, destination,
        providers={name: SimpleNamespace(judge=judge) for name in JUDGES}, progress=False))
    assert attempted and len(results) == len(extended["jobs"])


@pytest.mark.parametrize("missing", ["manifest", "manifest_row", "checkpoint", "prior_ledger"])
def test_pre_marker_extension_requires_complete_imports_before_dispatch(tmp_path, missing):
    from crest_ais import pipeline
    parent, source = _completed_extension_parent(tmp_path)
    (source / "prior_costs.json").write_text(json.dumps({"known_usd": .25, "unknown_jobs": 0, "job_count": 1}))
    destination = tmp_path / "legacy-extension"
    extended = pipeline.create_extension(source, destination, tmp_path, pairs_per_matchup=2)
    (destination / "extension_preparation.json").unlink()
    manifest = destination / "imported_results.json"
    if missing == "manifest":
        manifest.unlink()
    elif missing == "manifest_row":
        manifest.write_text(json.dumps(json.loads(manifest.read_text())[:-1]))
    elif missing == "checkpoint":
        Cache(destination / ".cache" / "judgments").job(parent["jobs"][0]["key"]).path.unlink()
    else:
        (destination / "prior_costs.json").unlink()
    async def no_dispatch(prompt, settings, job):
        pytest.fail("Incomplete legacy preparation cannot submit paid work")
    with pytest.raises(ValueError, match="prepar|ready|Imported"):
        asyncio.run(run_judging(extended, destination,
            providers={name: SimpleNamespace(judge=no_dispatch) for name in JUDGES}, progress=False))


def test_ready_pre_marker_extension_remains_resumable_without_repaying_imports(tmp_path):
    from crest_ais import pipeline
    parent, source = _completed_extension_parent(tmp_path)
    destination = tmp_path / "legacy-extension"
    extended = pipeline.create_extension(source, destination, tmp_path, pairs_per_matchup=2)
    (destination / "extension_preparation.json").unlink()
    calls = []
    async def judge(prompt, settings, job):
        calls.append(job.key)
        return {"text": json.dumps(_verdict()), "cost_usd": .02, "usage": {}, "model": "mock"}
    results = asyncio.run(run_judging(extended, destination,
        providers={name: SimpleNamespace(judge=judge) for name in JUDGES}, progress=False))
    assert len(results) == len(extended["jobs"])
    assert len(calls) == len(extended["jobs"]) - len(parent["jobs"])


def test_interruption_after_plan_publication_still_requires_readiness_commit(tmp_path, monkeypatch):
    from crest_ais import pipeline
    _, source = _completed_extension_parent(tmp_path)
    destination = tmp_path / "extension"
    original_write = pipeline.write_json
    def interrupt(path, value):
        if Path(path).name == "extension_preparation.json" and value["status"] == "ready":
            raise RuntimeError("Interrupted before ready commit")
        original_write(path, value)
    monkeypatch.setattr(pipeline, "write_json", interrupt)
    with pytest.raises(RuntimeError, match="ready commit"):
        pipeline.create_extension(source, destination, tmp_path, pairs_per_matchup=2)
    extended = json.loads((destination / "plan.json").read_text())
    assert json.loads((destination / "extension_preparation.json").read_text())["status"] == "preparing"
    async def no_dispatch(prompt, settings, job):
        pytest.fail("Published plan is still incomplete without ready commit")
    with pytest.raises(ValueError, match="prepar|ready"):
        asyncio.run(run_judging(extended, destination,
            providers={name: SimpleNamespace(judge=no_dispatch) for name in JUDGES}, progress=False))
    monkeypatch.setattr(pipeline, "write_json", original_write)
    resumed = pipeline.create_extension(source, destination, tmp_path, pairs_per_matchup=2)
    assert resumed == extended
    assert json.loads((destination / "extension_preparation.json").read_text())["status"] == "ready"


def test_existing_completed_240_run_passes_read_only_legacy_readiness_check():
    from crest_ais.pipeline import _check_extension_ready, _completed
    root = Path(__file__).resolve().parents[1]
    run = root / "results" / "20261027T031432.489760Z-1a7e86dc"
    if not (run / "plan.json").exists():
        pytest.skip("Completed frozen extension not present")
    names = ("plan.json", "results.json", "judging.json", "prior_costs.json", "imported_results.json")
    before = {name: (run / name).read_bytes() for name in names}
    marker_existed = (run / "extension_preparation.json").exists()
    plan = json.loads(before["plan.json"])
    _check_extension_ready(plan, run)
    cache = Cache(run / ".cache" / "judgments")
    results = [_completed(task, cache.job(task["key"]).state) for task in plan["jobs"]]
    assert len(results) == 240 and all(result is not None for result in results)
    assert {row["key"]: row for row in results} == {row["key"]: row for row in json.loads(before["results.json"])}
    assert before == {name: (run / name).read_bytes() for name in names}
    assert (run / "extension_preparation.json").exists() == marker_existed


def test_judging_lifecycle_lock_covers_outstanding_worker_cleanup(tmp_path):
    from crest_ais import pipeline
    _, source = _completed_extension_parent(tmp_path)
    destination = tmp_path / "extension"
    extended = pipeline.create_extension(source, destination, tmp_path, pairs_per_matchup=2)
    started = asyncio.Event()
    cleanup = []
    async def delayed_judge(prompt, settings, job):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            try:
                pipeline.create_extension(source, destination, tmp_path, pairs_per_matchup=2)
            except ValueError as error:
                cleanup.append(str(error))
            else:
                cleanup.append("Preparation overlapped outstanding provider cleanup")
    async def withdrawing_judge(prompt, settings, job):
        await started.wait()
        (destination / "superseded.json").write_text(json.dumps({"reason": "Stop new dispatch"}))
        return {"text": json.dumps(_verdict()), "cost_usd": .02, "usage": {}, "model": "mock"}
    providers = {"gemini": SimpleNamespace(judge=delayed_judge), "openai": SimpleNamespace(judge=withdrawing_judge)}
    with pytest.raises(ValueError, match="superseded"):
        asyncio.run(run_judging(extended, destination, providers=providers, progress=False))
    assert cleanup and all("busy" in result for result in cleanup)


def _new_agent_catalog(tmp_path, count=3, agent="e"):
    rows = []
    for index in range(count):
        identity = f"{agent}:{index}"
        path = tmp_path / f"{agent}-{index}.txt"
        text = f"[Page 1]\nAbstract\nDifferent new-system manuscript {identity} with complete scientific mechanism and evidence."
        path.write_text(text)
        rows.append({"id": identity, "agent": agent, "title": f"New release {index}",
                     "blind_text_path": path.name, "blind_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                     "sha256": hashlib.sha256(identity.encode()).hexdigest(), "pages": 1, "eligible_primary": True})
    return rows


def test_five_agent_plan_and_cohort_addition_handle_census_and_keep_old_jobs(tmp_path):
    from crest_ais.protocol import add_agent_plan, validate_plan_fingerprint
    catalog = _catalog(tmp_path, (2, 3, 2, 4))
    parent = make_plan(catalog, AGENTS, JUDGES, tmp_path, RUBRIC, pairs_per_matchup=10)
    new_catalog = _new_agent_catalog(tmp_path)
    all_agents = AGENTS | {"e": "Fifth system"}
    fresh = make_plan(catalog + new_catalog, all_agents, JUDGES, tmp_path, RUBRIC)
    assert len(fresh["strata"]) == 10
    assert all(s["sampled_pairs"] == min(10, s["population_pairs"]) for s in fresh["strata"])
    extended = add_agent_plan(parent, new_catalog, {"e": "Fifth system"}, tmp_path, parent_run_dir="parent")
    validate_plan_fingerprint(extended)
    assert extended["jobs"][:len(parent["jobs"])] == parent["jobs"]
    assert extended["rubric"] == parent["rubric"] and extended["judges"] == parent["judges"]
    assert [row for row in extended["catalog"] if row["agent"] in AGENTS] == parent["catalog"]
    old_strata = {tuple(s["agents"]): s for s in parent["strata"]}
    assert all(s == old_strata[tuple(s["agents"])] for s in extended["strata"] if "e" not in s["agents"])
    added = extended["jobs"][len(parent["jobs"]):]
    assert all("e" in job["agents"] for job in added)
    assert len(added) == 4 * (6 + 9 + 6 + 10)
    assert len({job["key"] for job in extended["jobs"]}) == len(extended["jobs"])
    assert extended["extension"]["kind"] == "cohort_addition"
    assert extended["extension"]["stage"] == "post_initial_results"
    assert extended["extension"]["previous_agent_count"] == 4
    assert extended["extension"]["current_agent_count"] == 5
    assert extended["extension"]["added_agents"] == ["e"]
    repeated = add_agent_plan(parent, new_catalog, {"e": "Fifth system"}, tmp_path, parent_run_dir="parent")
    assert repeated["fingerprint"] == extended["fingerprint"]
    with pytest.raises(ValueError, match="already|existing|disjoint"):
        add_agent_plan(parent, new_catalog, {"a": "Collision"}, tmp_path)


def test_single_collection_preparation_does_not_reextract_existing_agents(tmp_path):
    first = _pdf(tmp_path, "data/scientistone/one.pdf", ["Abstract\nExisting autonomous scientific mechanism and complete evidence."])
    _manifest(tmp_path, [first])
    # A changed old input must not be read while extracting only the new system.
    (tmp_path / first["pdf_path"]).write_bytes(b"Unavailable old PDF")
    new = _pdf(tmp_path, "data/new_system/new.pdf", ["Abstract\nNew system scientific method and experimental evidence."])
    directory = tmp_path / "data" / "new_system"
    (directory / "manifest.json").write_text(json.dumps({"agent_id": "new_system", "display_name": "V2", "papers": [new]}))
    rows = prepare_catalog(tmp_path, agents=["new_system"], output_dir=tmp_path / "new-prepared")
    assert len(rows) == 1 and rows[0]["agent"] == "new_system"
    assert rows[0]["eligible_primary"] is True


def test_cohort_extension_imports_all_240_paid_jobs_without_repaying_them(tmp_path):
    from crest_ais.pipeline import create_cohort_extension
    from crest_ais.cli import _report
    parent = make_plan(_catalog(tmp_path, (4, 4, 4, 4)), AGENTS, JUDGES, tmp_path, RUBRIC, pairs_per_matchup=10)
    assert len(parent["jobs"]) == 240
    source, destination = tmp_path / "source", tmp_path / "five-system-run"
    calls = []
    async def judge(prompt, settings, job):
        calls.append(job.key)
        return {"text": json.dumps(_verdict()), "cost_usd": .01, "usage": {}, "model": "mock"}
    providers = {name: SimpleNamespace(judge=judge) for name in JUDGES}
    initial = asyncio.run(run_judging(parent, source, providers=providers, progress=False, workers_per_judge=16))
    prior = {"known_usd": 13.873186, "unknown_jobs": 0, "job_count": 60, "reason": "Excluded attempts"}
    (source / "prior_costs.json").write_text(json.dumps(prior))
    new_catalog = _new_agent_catalog(tmp_path, count=1)
    extended = create_cohort_extension(source, destination, tmp_path, new_catalog=new_catalog, new_agents={"e": "Fifth system"})
    assert len(extended["jobs"]) == 304
    assert json.loads((destination / "results.json").read_text()) == initial
    assert json.loads((destination / "prior_costs.json").read_text()) == prior
    results = asyncio.run(run_judging(extended, destination, providers=providers, progress=False, workers_per_judge=16))
    assert len(results) == len(calls) == 304
    assert all(calls.count(job["key"]) == 1 for job in parent["jobs"])
    repeated = create_cohort_extension(source, destination, tmp_path, new_catalog=new_catalog, new_agents={"e": "Fifth system"})
    assert repeated == extended
    report = _report(extended, destination, tmp_path, destination / "report.html")
    assert len(report["agents"]) == 5 and report["coverage"]["completed_jobs"] == 304
    assert report["costs"]["known_usd"] == pytest.approx(3.04 + prior["known_usd"])
    assert json.loads((destination / "judging.json").read_text())["imported_jobs"] == 240


def test_v2_hash_locked_geometry_removes_human_reviews_and_preserves_all_science():
    from collections import Counter
    from crest_ais.catalog import _clean_page
    root = Path(__file__).resolve().parents[1]
    profiles = {
        "compositional-regularization.pdf": ("8d5477b165639ed7339b77677da355496778b081c0086d7185a906fbcbbcd40f", [24,21,55,22,16,37,5,23]),
        "label-noise.pdf": ("20b77a6ea8748d2bf5a0fd10ac589bcb6446fe50d5487632682fa87e324308b2", [19,38,74,25,13,52,8]),
        "pest-detection.pdf": ("4ed38075f76698bda3b3d21d3d792286aa1d45124398277119c8cca86ddbdf6f", [42,58,31,34,8,16]),
    }
    if not (root / "data/sakana_ai_scientist_v2/pdfs/compositional-regularization.pdf").exists():
        pytest.skip("Official v2 PDFs are absent")
    for filename, (sha, comments_per_page) in profiles.items():
        path = root / "data/sakana_ai_scientist_v2/pdfs" / filename
        assert hashlib.sha256(path.read_bytes()).hexdigest() == sha
        with fitz.open(path) as document:
            for index, page in enumerate(document):
                cleaned, audit = _clean_page(page, source_sha256=sha)
                counts = Counter(entry["kind"] for entry in audit["removed_lines"])
                assert counts == {"human_margin_review": comments_per_page[index], "editorial_line_number":54,"v2_review_status_header":1}
                assert "Comment:" not in cleaned
                assert "Under review as a workshop paper" not in cleaned
                removed = {(entry["block"],entry["line"]) for entry in audit["removed_lines"]}
                retained = [word for word in page.get_text("words") if (word[5],word[6]) not in removed]
                assert Counter(''.join(''.join(word[4] for word in retained).split())) == Counter(''.join(cleaned.split()))
                assert audit["raw_word_count"] == audit["kept_word_count"] + audit["removed_word_count"]
                # Genuine body statements containing 'generated' remain available.
                if filename == "compositional-regularization.pdf" and index == 1:
                    assert "generated" in cleaned.lower()


def test_v2_geometry_profile_does_not_apply_to_unrelated_margin_science(tmp_path):
    from crest_ais.catalog import _clean_page
    document = fitz.open()
    page = document.new_page()
    page.insert_text((30.509,100), "Comment: a scientific example", fontsize=10)
    page.insert_text((518.794,150), "Figure axis", fontsize=10)
    page.insert_text((73.131,200), "123", fontsize=8)
    raw = page.get_text("text",sort=True)
    cleaned, audit = _clean_page(page,source_sha256="f"*64)
    assert cleaned == raw and audit["removed_lines"] == []
    document.close()


def test_cli_add_agent_prepares_only_new_collection_and_imports_frozen_parent(tmp_path,monkeypatch):
    from crest_ais import cli
    parent = _plan(tmp_path,(2,2,2,2),pairs_per_matchup=2)
    save_plan(parent,tmp_path/"source")
    new_catalog = _new_agent_catalog(tmp_path,count=1)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"data_root":".","output_dir":"results"}))
    directory = tmp_path / "data" / "e"
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_text(json.dumps({"agent_id":"e","display_name":"New system"}))
    seen = []
    def prepare(root_arg,**kwargs):
        assert root_arg == tmp_path.resolve()
        assert kwargs["agents"] == ["e"]
        assert kwargs["output_dir"] == tmp_path / "results/prepared/add-agent/e"
        return new_catalog
    def create(source,run,root,**kwargs):
        seen.append(kwargs)
        return {**parent,"extension":{"original_pairs":12,"additional_pairs":8}}
    monkeypatch.setattr(cli,"prepare_catalog",prepare)
    monkeypatch.setattr(cli,"create_cohort_extension",create,raising=False)
    monkeypatch.setattr(cli,"load_config",lambda *a,**kw:pytest.fail("Existing model/rubric must come from parent"))
    assert cli.main(["add-agent","--config",str(config),"--source-run",str(tmp_path/"source"),"--run-dir",str(tmp_path/"new"),"--agent","e"]) == 0
    assert seen == [{"new_catalog":new_catalog,"new_agents":{"e":"New system"},"pairs_per_matchup":None,"addition_seed":2026}]


def test_unverified_v2_release_fails_closed_before_catalog_publication(tmp_path):
    from crest_ais.catalog import GeometryProfileError
    paper = _pdf(tmp_path,"data/sakana_ai_scientist_v2/unknown.pdf",["Abstract\nAn unverified release may include external reviewer margin commentary."])
    directory=tmp_path/"data/sakana_ai_scientist_v2"
    (directory/"manifest.json").write_text(json.dumps({"agent_id":"sakana_ai_scientist_v2","papers":[paper]}))
    with pytest.raises(GeometryProfileError,match="audited"):
        prepare_catalog(tmp_path,agents=["sakana_ai_scientist_v2"])
    assert not (tmp_path/"results/prepared/catalog.json").exists()


def test_v2_dataset_setup_disclosure_does_not_exclude_unedited_manuscript(tmp_path):
    root=Path(__file__).resolve().parents[1]
    manifest_path=root/"data/sakana_ai_scientist_v2/manifest.json"
    if not manifest_path.exists():
        pytest.skip("Official v2 manifest not present")
    manifest=json.loads(manifest_path.read_text())
    source=next(paper for paper in manifest["papers"] if paper["id"]=="sakana_v2_pest_detection")
    target=tmp_path/source["pdf_path"]
    target.parent.mkdir(parents=True)
    target.write_bytes((root/source["pdf_path"]).read_bytes())
    (tmp_path/"data/sakana_ai_scientist_v2/manifest.json").write_text(json.dumps({"agent_id":"sakana_ai_scientist_v2","papers":[source]}))
    row=prepare_catalog(tmp_path,agents=["sakana_ai_scientist_v2"])[0]
    assert row["eligible_primary"] is True and row["human_setup_assistance"] is True
    assert row["human_setup_notes"]==source["human_setup_notes"]
    assert "Comment:" in (tmp_path/row["full_text_path"]).read_text()
    assert "Comment:" not in (tmp_path/row["blind_text_path"]).read_text()

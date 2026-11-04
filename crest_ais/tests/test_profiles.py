"""The strengths and weaknesses section shows only what saved reasons support."""
import json

from crest_ais.tests.test_add_judge import _complete_parent
from crest_ais.tests.test_pipeline import _verdict


def _profiles(plan, agent, keys, quotes):
    return {"version": "crest-ais-creativity-profiles-v1", "plan_fingerprint": plan["fingerprint"],
            "method": "Method note.",
            "profiles": {agent: {"overall": "Overall view.",
                                 "strengths": [{"theme": "Worked mechanism", "explanation": "Judges credit the mechanism.",
                                                "keys": keys, "quotes": quotes}],
                                 "weaknesses": []}}}


def test_counts_come_from_saved_judgments_and_unverified_quotes_are_dropped(tmp_path, monkeypatch):
    from crest_ais import cli
    plan, source = _complete_parent(tmp_path)
    agent = plan["jobs"][0]["agents"][0]
    keys = [job["key"] for job in plan["jobs"] if agent in job["agents"]]
    pairs = {job["pair_id"] for job in plan["jobs"] if agent in job["agents"]}
    real = "stronger overall creative quality"
    assert real in _verdict()["reason"]
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps(_profiles(plan, agent, keys + ["not-a-saved-judgment"],
                                         [{"key": keys[0], "text": "words no judge wrote"}, {"key": keys[0], "text": real}])))
    monkeypatch.setattr(cli, "PROFILES_PATH", path)
    cli._report(plan, source, tmp_path, tmp_path / "out.html")
    html = (tmp_path / "out.html").read_text()
    section = html.split('<section id="profiles"', 1)[1].split("</section>", 1)[0]
    per_judge = {judge: sum(job["judge"] == judge for job in plan["jobs"] if job["key"] in keys) for judge in ("gemini", "openai")}
    assert (f'Cited in {len(keys)} judgments on {len(pairs)} paper pairs: <span class="judge-name">{per_judge["gemini"]} from '
            f'Gemini 4 Argon</span>, <span class="judge-name">{per_judge["openai"]} from GPT-6 Astra</span>.') in section
    assert "<strong>Strengths:</strong> Worked mechanism.</p>" in section
    assert '<details class="profile-evidence-toggle"><summary>Evidence and quotes' in section
    assert f"“{real}”" in section and "words no judge wrote" not in section
    assert 'href="#profiles"' in html and "Strengths</h4>" in section and "—" not in section


def test_profiles_for_another_plan_are_not_shown(tmp_path, monkeypatch):
    from crest_ais import cli
    plan, source = _complete_parent(tmp_path)
    agent = plan["jobs"][0]["agents"][0]
    stale = _profiles(plan, agent, [plan["jobs"][0]["key"]], [])
    stale["plan_fingerprint"] = "0" * 64
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps(stale))
    monkeypatch.setattr(cli, "PROFILES_PATH", path)
    cli._report(plan, source, tmp_path, tmp_path / "out.html")
    html = (tmp_path / "out.html").read_text()
    assert 'id="profiles"' not in html and 'href="#profiles"' not in html

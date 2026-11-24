"""Rubric changes preserve historical instruments and separate new comparisons."""
from copy import deepcopy
import hashlib
import json

import pytest

from crest import judging
from crest.analysis import analyze
from crest_ais.analysis import analyze as analyze_papers
from crest_ais.protocol import extend_plan, make_plan, plan_fingerprint


NUS = "Compare New, Useful, and Surprising."
AUT = "RUBRIC ID: aut-inspired-pairwise-v1\nCompare fluency, flexibility, and originality."
JUDGES = {'j1': {'model': 'test-1'}, 'j2': {'model': 'test-2'}}
REASON = 'A develops a mechanism from multiple perspectives, whereas B elaborates one familiar approach.'


def answer_inputs():
    return ([{'id': 'q', 'text': 'Propose a bridge.'}],
            [{'question_id': 'q', 'agent': agent, 'key': agent,
              'result': {'text': f'Mechanism {agent}.'}} for agent in ['a', 'b']])


def paper_plan(tmp_path, rubric):
    papers = []
    for agent in ['a', 'b']:
        for index in range(2):
            identity = f'{agent}{index}'
            (tmp_path / f'{identity}.txt').write_text(f'[Page 1] Mechanism {identity}.')
            papers.append({'id': identity, 'agent': agent, 'eligible_primary': True,
                           'blind_text_path': f'{identity}.txt', 'sha256': f'pdf-{identity}'})
    return make_plan(papers, {'a': 'A', 'b': 'B'}, JUDGES, tmp_path, rubric, pairs_per_matchup=1)


def test_historical_nus_prompt_and_content_keys_stay_byte_identical(tmp_path):
    questions, answers = answer_inputs()
    prompt = judging.build_prompt(questions[0]['text'], 'Mechanism a.', 'Mechanism b.', NUS)
    assert hashlib.sha256(prompt.encode()).hexdigest() == '019f0c6c4821a3cbdadd6f8f5598cdafd203337835cf2cff651dcac3b09007b1'
    # 2026-11-24: research judging moved to citation-neutral-v2 (drops the appended uncited
    # source list), so research judgment keys changed (were 80ca8e36..., 0f125f88..., 82081aa2...,
    # 759b3f51...). Saved judgments keep their v1 presentation and still validate. Paper keys below
    # are unchanged.
    assert [job['key'] for job in judging.make_judgment_jobs(questions, answers, JUDGES, NUS)] == [
        '6013c97587ffc9ab72993c07b5a5c76bb321811f60b10cdf06d6cd30f887d0cf',
        'af9a2c7c2b1f87d16fe9dae09a048bbce81eba93d54b017fe4ee0ea689f3088b',
        '4324d0ca38b40973f82d9c6ca0809db734539d97a96533eb613754882be270a5',
        'f7c8bcdfd6e9abdfbc092ff6d25cb25b7aa21ef06edc110ad7d316a734fc47da']
    plan = paper_plan(tmp_path, NUS)
    assert [job['key'] for job in plan['jobs']] == [
        '87463a17187034ca17139c1633058f776ae61174473740bd41332de3c3a78178',
        '046dd9dd867172f12a0d203a09479e394c838a1c924f4ccab508bde63fba96ae',
        'e92ff5bca277e8e19c6c1098c57c93234b6dfa27a0baa2d6d9576874934a6b7a',
        'c63bb27c5e65500621b27de822157458bf0109614e71c21475d5a3bbc953b2a8']
    assert plan['fingerprint'] == '3d0d02e0b9744525c02a45c4229735e2b67ba85c2f22c1f193828bbe86ba528d'


def test_aut_jobs_use_the_selected_guidance_and_separate_content_keys():
    questions, answers = answer_inputs()
    nus = judging.make_judgment_jobs(questions, answers, JUDGES, NUS)
    aut = judging.make_judgment_jobs(questions, answers, JUDGES, AUT)
    assert {job['key'] for job in nus}.isdisjoint(job['key'] for job in aut)
    assert [job['answer_keys'] for job in aut] == [job['answer_keys'] for job in nus]
    for job in aut:
        assert job['protocol_version'] == 'aut-inspired-overall-pairwise-v1'
        assert job['rubric_kind'] == 'aut-inspired'
        assert 'New, Useful, and Surprising' not in job['prompt']
        assert 'Fluency, Flexibility, and Originality' in job['prompt']
        assert 'not a standardized AUT' in job['prompt']
        assert 'fluency' in job['prompt'].lower()
        assert 'explicitly requests multiple ideas' in job['prompt']
        assert 'comparable submission requirements' in job['prompt']
        assert json.loads(job['prompt'].split('UNTRUSTED INPUT DATA (JSON):\n')[1])['A']


def test_answer_analysis_labels_aut_and_rejects_mixed_family_votes():
    questions, answers = answer_inputs()
    rows = [dict(job, verdict={'reason': REASON, 'winner': 'A'})
            for job in judging.make_judgment_jobs(questions, answers, JUDGES, AUT)]
    report = analyze(questions, answers, rows, agents=['a', 'b'], judges=list(JUDGES), bootstrap_samples=0)
    assert report['rubric_kind'] == 'aut-inspired'
    assert report['coverage']['complete_questions'] == 1
    assert 'New, Useful' not in report['method']
    rows[0]['protocol_version'] = 'nus-overall-pairwise-v3'
    rows[0].pop('rubric_kind')
    with pytest.raises(ValueError, match='rubric|protocol'):
        analyze(questions, answers, rows, agents=['a', 'b'], judges=list(JUDGES), bootstrap_samples=0)


def test_aut_paper_context_frozen_metadata_and_extension_remain_in_family(tmp_path):
    nus, aut = paper_plan(tmp_path, NUS), paper_plan(tmp_path, AUT)
    assert aut['judging_protocol'] == 'aut-inspired-overall-pairwise-v1'
    assert aut['rubric_kind'] == 'aut-inspired'
    assert [(j['papers'], j['order']) for j in nus['jobs']] == [(j['papers'], j['order']) for j in aut['jobs']]
    for job in aut['jobs']:
        assert job['judging_protocol'] == 'aut-inspired-overall-pairwise-v1'
        assert 'New, Useful, and Surprising' not in job['prompt']
        assert 'page numbers in BOTH papers' in job['prompt']
        assert 'raw idea-count advantage' in job['prompt']
    extended = extend_plan(aut, tmp_path, pairs_per_matchup=3)
    assert extended['jobs'][:4] == aut['jobs']
    assert extended['rubric_kind'] == 'aut-inspired'
    assert all(j['judging_protocol'] == aut['judging_protocol'] for j in extended['jobs'])
    rows = [dict(key=job['key'], verdict={'reason': REASON, 'winner': 'A'}) for job in aut['jobs']]
    report = analyze_papers(aut, rows)
    assert report['rubric_kind'] == 'aut-inspired'
    assert all(row['judging_protocol'] == 'aut-inspired-overall-pairwise-v1'
               and row['rubric_kind'] == 'aut-inspired' for row in report['judgments'])
    mislabeled = deepcopy(aut)
    mislabeled['jobs'][0]['judging_protocol'] = 'nus-overall-pairwise-v3'
    mislabeled['fingerprint'] = plan_fingerprint(mislabeled)
    with pytest.raises(ValueError, match='rubric|protocol'):
        analyze_papers(mislabeled, rows)
    with pytest.raises(ValueError, match='rubric|protocol|frozen inputs'):
        extend_plan(mislabeled, tmp_path, pairs_per_matchup=3)


def test_aut_rubric_short_name_preserves_instrument():
    from crest.config import ROOT
    from crest.rubrics import AUT_RUBRIC
    renamed = ROOT / 'crest/prompts/aut_pairwise_v1.txt'
    old_path = ROOT / 'crest/prompts/aut_research_pairwise_v1.txt'
    assert AUT_RUBRIC == renamed
    assert not old_path.exists() and not old_path.is_symlink()
    # 2026-11-23: trimmed to 5 KB with the shared RULES AND OUTPUT block (was 45689c21...).
    assert hashlib.sha256(renamed.read_bytes()).hexdigest() == '329bb178a0d1e72abd6a07bf0f3754b3407cf8e5721da928c7996b831641009e'
    contract = json.loads((ROOT / 'crest_ais/configs/contract.json').read_text())
    assert contract['rubric_selection']['aut-inspired'] == renamed.name


def test_default_ais_rubric_uses_canonical_resource_and_keeps_explicit_paths(tmp_path):
    from crest.config import load_config as load_crest_config
    from crest_ais.cli import load_config
    from crest.rubrics import DEFAULT_NUS_RUBRIC
    assert load_config()['rubric'] == DEFAULT_NUS_RUBRIC
    assert load_crest_config()['rubric'] == str(DEFAULT_NUS_RUBRIC)
    path = tmp_path / 'config.json'
    path.write_text('{}')
    assert load_config(path)['rubric'] == DEFAULT_NUS_RUBRIC
    (tmp_path / 'custom.txt').write_text(AUT)
    path.write_text(json.dumps({'rubric': 'custom.txt'}))
    assert load_config(path)['rubric'] == tmp_path / 'custom.txt'


def test_empty_answer_analysis_keeps_frozen_rubric_family():
    questions, answers = answer_inputs()
    report = analyze(questions, answers, [], agents=['a', 'b'], judges=list(JUDGES),
                     bootstrap_samples=0, rubric_kind='aut-inspired')
    assert report['rubric_kind'] == 'aut-inspired'
    assert report['coverage']['complete_questions'] == 0


@pytest.mark.parametrize('field,value', [
    ('rubric_kind', 'nus'), ('judging_protocol', 'nus-overall-pairwise-v3'),
    ('judging_protocol', 'unknown-future-protocol'),
])
def test_paper_result_metadata_cannot_override_frozen_family(tmp_path, field, value):
    plan = paper_plan(tmp_path, AUT)
    rows = [dict(key=job['key'], verdict={'reason': REASON, 'winner': 'A'}) for job in plan['jobs']]
    rows[0][field] = value
    with pytest.raises(ValueError, match='rubric|protocol'):
        analyze_papers(plan, rows)


def test_unknown_rubric_marker_cannot_silently_run_as_nus():
    with pytest.raises(ValueError, match='rubric'):
        judging.make_judgment_jobs(*answer_inputs(), JUDGES, 'RUBRIC ID: unknown-future-rubric')


def test_family_validation_preserves_malformed_job_value_error(tmp_path):
    plan = paper_plan(tmp_path, AUT)
    plan.pop('fingerprint')
    plan['jobs'][0] = None
    with pytest.raises(ValueError, match='job'):
        analyze_papers(plan, [])


def test_archived_nus_v1_preserves_ais_alias_and_judgment_keys():
    from crest.config import ROOT
    from crest.rubrics import DEFAULT_NUS_RUBRIC
    archive = ROOT / 'crest/prompts/nus_pairwise_v1.txt'
    assert archive.is_file()
    old_archive = ROOT / 'crest/prompts/archive/nus_pairwise_v1.txt'
    assert not old_archive.exists() and not old_archive.is_symlink()
    original = archive.read_bytes()
    # Pinned instrument: relocating it must not change its bytes or judgment keys. 2026-11-23:
    # trimmed to 5 KB with the shared RULES AND OUTPUT block (was a70eba75...).
    assert hashlib.sha256(original).hexdigest() == '66f7947e5d00d3e6ec2c49fd915e3db283c72eb7f3f4ecc9937390b97daa2dd0'
    removed_archive = ROOT / 'crest/_archive/reference/nus_pairwise_v1.txt'
    assert not removed_archive.exists() and not removed_archive.is_symlink()
    questions, answers = answer_inputs()
    archived_jobs = judging.make_judgment_jobs(questions, answers, JUDGES, original.decode())
    legacy = ROOT / 'crest_ais/prompts/rubric_v1.txt'
    assert legacy.resolve() == archive.resolve()
    assert legacy.read_bytes() == original
    assert judging.make_judgment_jobs(questions, answers, JUDGES, legacy.read_text()) == archived_jobs
    current_jobs = judging.make_judgment_jobs(questions, answers, JUDGES, DEFAULT_NUS_RUBRIC.read_text())
    assert {job['key'] for job in archived_jobs}.isdisjoint(job['key'] for job in current_jobs)
    assert [job['order'] for job in current_jobs] == [['a', 'b'], ['a', 'b'], ['b', 'a'], ['b', 'a']]


def test_nus_v4_is_v3_plus_a_neutral_rule_for_process_wording():
    from crest.config import ROOT
    from crest.rubrics import DEFAULT_NUS_RUBRIC
    v3 = ROOT / 'crest/prompts/nus_pairwise_v3.txt'
    v4 = ROOT / 'crest/prompts/nus_pairwise_v4.txt'
    # v3 stays a frozen instrument; v4 is the default for new judging.
    assert hashlib.sha256(v3.read_bytes()).hexdigest() == '91524e4cf34343f9c6dfc6694e2b109e69f546b004a9b96956dc3dd621bb34d4'
    assert DEFAULT_NUS_RUBRIC == v4
    old, new = v3.read_text(), v4.read_text()
    rules = new.index('RULES AND OUTPUT')
    assert new[:rules] == old[:old.index('RULES AND OUTPUT')]
    added = new[rules:]
    for phrase in ('"the supplied material"', 'own research', 'neither credit nor penalize'):
        assert phrase in added.replace('\n', ' ')
    assert len(v4.read_bytes()) <= 5120
    contract = json.loads((ROOT / 'crest_ais/configs/contract.json').read_text())
    assert contract['rubric_selection']['nus'] == v4.name

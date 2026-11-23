"""Active setup contracts: explicit model, transport, reasoning and honest pricing."""
import copy
from pathlib import Path

import pytest

from crest.config import DEFAULTS, ROOT, load_config
from crest.costs import assess_cost
from crest.pipeline import Pipeline


GATEWAY_RATES = {'input': 4.4, 'cached_input': .22, 'cache_write_5m': 5.5,
                 'output': 22., 'web_search': .01}
SONNET_GATEWAY_RATES = {'input': 2.2, 'cached_input': .11, 'cache_write_5m': 2.75,
                        'output': 11., 'web_search': 0.}


def test_sonnet_high_client_research_with_headroom_preserves_opus_sol_argon_high_judges():
    config = load_config()
    for values in (DEFAULTS, config):
        research = values['research']['anthropic']
        # The live high-effort pilot exhausted its old 16k allowance before answering;
        # the judge limit is separate and unchanged.
        assert research['max_output_tokens'] == 64000
        assert values['judges']['anthropic']['max_output_tokens'] == 32768
        assert research['budget_cap'] == 'soft'
        assert research['budget_usd'] == 4.0
        # The live 10-turn profile returned an earlier $1.15 answer during deepening.
        assert research['tool_mode'] == 'client'
        assert research['max_continuations'] == 50
        assert research['max_web_searches'] == 30
        assert research['max_web_fetches'] == 10
        assert values['judges']['openai']['model'] == 'gpt-6.1-sol'
        assert values['judges']['openai']['reasoning_effort'] == 'high'
        assert values['judges']['gemini']['model'] == 'gemini-4-argon'
        assert values['judges']['gemini']['thinking_level'] == 'high'
        for section, model, effort, rates in (
                ('research', 'claude-sonnet-5-5', 'high', SONNET_GATEWAY_RATES),
                ('judges', 'claude-opus-5-5', 'high', GATEWAY_RATES)):
            anthropic = values[section]['anthropic']
            assert anthropic['model'] == model
            assert anthropic['effort'] == effort
            assert anthropic['api_base'] == 'https://litellm.evolution.ml'
            assert anthropic['api_key_env'] == 'LITELLM_API_KEY'
            assert anthropic['model_pricing'] == {model: rates}
    assert config['research']['anthropic']['budget_floor_usd'] is None


@pytest.mark.parametrize('section', ['research', 'judges'])
@pytest.mark.parametrize('field,value', [
    ('api_base', 'https://user:secret@example.com'),
    ('api_base', 'https://example.com?key=secret'),
    ('api_base', 'http://remote.example.com'),
    ('api_key_env', 'sk-secret-not-an-env-name'),
    ('model_pricing', {'claude-opus-5-5': {'input': -1}}),
])
def test_anthropic_transport_rejects_unsafe_or_unpriceable_configuration(
        write_master_config, section, field, value):
    with pytest.raises(ValueError, match=field):
        load_config(write_master_config(**{f'{section}.anthropic.{field}': value}))


def test_gateway_only_key_satisfies_anthropic_generation_preflight(tmp_path, monkeypatch):
    config = load_config()
    config['research'] = {'anthropic': config['research']['anthropic']}
    config['cache_dir'] = str(tmp_path / 'cache')
    config['output_dir'] = str(tmp_path / 'out')
    pipeline = Pipeline(config, limit=1)
    monkeypatch.setenv('LITELLM_API_KEY', 'fake-gateway-key')
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    pipeline.preflight('generate')
    monkeypatch.delenv('LITELLM_API_KEY')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fake-native-key')
    with pytest.raises(ValueError, match='LITELLM_API_KEY'):
        pipeline.preflight('generate')


def test_gateway_cost_assessment_uses_configured_rates_not_native_list_prices():
    settings = {'model': 'claude-opus-5-5', 'api_base': 'https://litellm.evolution.ml',
                'model_pricing': {'claude-opus-5-5': GATEWAY_RATES}}
    original = copy.deepcopy(settings)
    result = {'model': 'claude-opus-5-5', 'cost_usd': .123, 'usage': {}, 'raw': {}}
    details = assess_cost(result, agent='anthropic', settings=settings)
    assert details['pricing']['rates']['claude-opus-5-5']['input'] == 4.4
    assert details['pricing']['rates']['claude-opus-5-5']['output'] == 22
    assert details['cost_basis'] == 'gateway_usage_priced_estimate'
    assert details['actual_billed_usd'] is None
    assert settings == original


def test_gpt_researcher_is_a_fifth_budgeted_sol_provider_with_a_bounded_final_write():
    """Candidate deeper profile; only a completed pilot can establish its spend."""
    config = load_config()
    for values in (DEFAULTS, config):
        settings = values['research']['gpt_researcher']
        assert settings['model'] == 'gpt-6.1-sol'
        assert settings['reasoning_effort'] == 'high'
        assert settings['budget_cap'] == 'soft'
        assert settings['budget_usd'] == 4
        assert settings['budget_target_usd'] == 3.4
        assert settings['synthesis_reserve_usd'] == .5
        assert settings['answer_word_limit'] is None
        assert (settings['initial_concurrency'], settings['concurrency']) == (4, 8)
        assert settings['deep_research_breadth'] == 4
        assert settings['deep_research_depth'] == 3
        assert settings['deep_research_concurrency'] == 2
        assert settings['max_iterations'] == 3
        assert settings['max_research_rounds'] == 3
        assert settings['timeout_seconds'] == 5400
        assert settings['call_timeout_seconds'] == 600
        assert settings['synthesis_reserve_usd'] >= (
            settings['max_input_tokens'] * 2.5 +
            settings['synthesis_max_completion_tokens'] * 10) / 1_000_000
    settings = config['research']['gpt_researcher']
    assert Path(settings['gpt_researcher_path']) == ROOT.parent / 'gpt-researcher'
    assert settings['python_executable'].endswith('/gpt-researcher/.venv/bin/python')


def test_gpt_researcher_plan_does_not_invent_a_measured_budget():
    from crest.budget import plan
    estimate = plan('gpt_researcher', 4.)
    assert estimate['settings']['budget_target_usd'] == 3.2
    assert estimate['estimate']['expected_usd'] is None
    assert 'pilot' in estimate['estimate']['note'].lower()


def test_gpt_researcher_uses_its_ledger_without_hosted_search_fees():
    result = {'model': 'gpt-6.1-sol', 'cost_usd': None, 'usage': {},
              'raw': {'accounting': {'known_cost_usd': 2.5, 'reserved_usd': .2,
                                     'unknown_cost': True}}}
    details = assess_cost(result, agent='gpt_researcher')
    assert details['cost_basis'] == 'sdk_usage_priced_estimate'
    assert details['cumulative_known_estimate_usd'] == 2.5
    assert details['unresolved_reserved_exposure_usd'] == .2
    assert details['estimate_incomplete'] is True
    assert details['pricing']['tool_rates']['web_search_search_action_usd'] == 0


def test_report_names_current_models_without_relabeling_opus_as_sonnet():
    from crest.report import LABELS, JUDGE_LABELS
    assert 'Sonnet' not in LABELS['anthropic']
    assert LABELS['gpt_researcher'] == 'GPT Researcher'
    assert JUDGE_LABELS['claude-opus-5-5'] == 'Claude Opus 5.5'
    assert JUDGE_LABELS['gpt-6.1-sol'] == 'GPT-6.1 Sol'


@pytest.mark.parametrize('pricing', [None, {'different-model': GATEWAY_RATES}])
def test_gateway_configuration_requires_tariff_for_selected_model(write_master_config, pricing):
    with pytest.raises(ValueError, match='model_pricing'):
        load_config(write_master_config(**{'research.anthropic.model_pricing': pricing}))


def test_native_anthropic_configuration_can_use_native_rates(write_master_config):
    config = load_config(write_master_config(**{
        'research.anthropic.api_base': 'https://api.anthropic.com',
        'research.anthropic.api_key_env': 'ANTHROPIC_API_KEY',
        'research.anthropic.model_pricing': None,
        'research.anthropic.tool_mode': 'server',
    }))
    assert config['research']['anthropic']['model_pricing'] is None


@pytest.mark.parametrize('source', ['master', 'defaults', 'direct-worker', 'explicit-prior'])
def test_caesar_build_config_splits_research_and_synthesis_effort_with_headroom(source, tmp_path):
    """Generous request limits do not increase the per-answer budget; explicit prior limits survive."""
    from crest.providers.caesar_worker import build_config

    settings = {'master': lambda: load_config()['research']['caesar'],
                'defaults': lambda: DEFAULTS['research']['caesar'],
                'direct-worker': dict,
                'explicit-prior': lambda: {'max_completion_tokens': 10000, 'call_timeout_seconds': 600,
                                           'synthesis_reasoning_effort': 'medium'}}[source]()
    if source in ('master', 'defaults'):
        assert settings['max_completion_tokens'] == 32768
        assert settings['call_timeout_seconds'] == 1200
        assert settings['timeout_seconds'] == 21600
        assert settings['synthesis_reserve_usd'] == 2.6
        assert settings['budget_usd'] == 4
        assert settings['query_max_completion_tokens'] == 6000
        assert settings['max_iterations'] == 300
        assert settings['exploration_model'] == settings['kb_model'] == 'gpt-6-luna'
    prior = source == 'explicit-prior'
    runtime = build_config('Question', settings, tmp_path, 'effort-split')
    assert runtime['LLMHandler']['reasoning_effort'] == 'medium'
    assert runtime['ArtifactSynthesizer']['synthesis_reasoning_effort'] == ('medium' if prior else 'high')
    assert runtime['CaesarAgent']['exploration_llm_config']['reasoning_effort'] == 'low'
    assert runtime['ChromaClientManager']['reasoning_effort'] == 'low'
    assert runtime['LLMHandler']['max_completion_tokens'] == (10000 if prior else 32768)
    assert runtime['LLMHandler']['timeout'] == (600 if prior else 1200)


@pytest.mark.parametrize('agent,overrides,unchanged', [
    ('gpt_researcher', {'reasoning_effort': 'high'}, {}),
    ('gpt_researcher', {'reasoning_effort': 'xhigh'}, {}),
    ('gpt_researcher', {'initial_concurrency': 1, 'concurrency': 1}, {'deep_research_concurrency': 2}),
    ('caesar', {'synthesis_reasoning_effort': 'medium', 'max_completion_tokens': 10000, 'call_timeout_seconds': 600,
                'timeout_seconds': 12600, 'synthesis_reserve_usd': 1.76}, {}),
], ids=['gpt-high-effort', 'gpt-xhigh-effort', 'gpt-serial-answers', 'caesar-prior-headroom'])
def test_explicit_prior_profile_values_remain_loadable(write_master_config, agent, overrides, unchanged):
    """New defaults must not reinterpret saved explicit values."""
    settings = load_config(write_master_config(**{
        f'research.{agent}.{field}': value for field, value in overrides.items()}))['research'][agent]
    for field, value in {**overrides, **unchanged}.items():
        assert settings[field] == value, field


@pytest.mark.parametrize("agent", ["caesar", "openai", "anthropic", "gpt_researcher"])
@pytest.mark.parametrize("mode", ["hard", "auto"])
def test_explicit_prior_enforcement_modes_remain_available(write_master_config, agent, mode):
    """New soft defaults must not reinterpret explicit old hard/auto profiles."""
    config = load_config(write_master_config(**{f"research.{agent}.budget_cap": mode}))
    assert config["research"][agent]["budget_cap"] == mode
    assert all(settings["budget_cap"] == "soft"
               for name, settings in config["research"].items() if name != agent)


def test_gpt_researcher_generation_job_preserves_high_effort_and_token_headroom(tmp_path):
    """Job serialization must not restore the 8k cap that starved a live xhigh call."""
    from crest.providers.gpt_researcher import public_settings
    from crest.providers.gpt_researcher_worker import build_config, normalize_settings

    config = load_config()
    config['cache_dir'] = str(tmp_path / 'cache')
    config['output_dir'] = str(tmp_path / 'out')
    pipeline = Pipeline(config, limit=1, providers={name: object() for name in config['research']})
    job = next(job for job in pipeline.generation_jobs() if job['agent'] == 'gpt_researcher')
    for settings in (DEFAULTS['research']['gpt_researcher'], job['settings']):
        public = public_settings(settings)
        assert public['max_output_tokens'] == 32000
        assert public['synthesis_max_output_tokens'] == 32000
        assert public['reasoning_effort'] == 'high'
        assert public['budget_cap'] == 'soft'
        assert public['budget_usd'] == 4
        normalized = normalize_settings(public)
        assert normalized['budget_target_usd'] - normalized['synthesis_reserve_usd'] == pytest.approx(2.9)
        upstream = build_config(public)
        for role in ('FAST', 'SMART', 'STRATEGIC'):
            assert upstream[f'{role}_TOKEN_LIMIT'] == 32000
        assert upstream['LLM_KWARGS']['max_tokens'] == 32000
        assert upstream['LLM_KWARGS']['reasoning_effort'] == 'high'


def test_explicit_previous_gpt_token_profile_remains_loadable(write_master_config):
    """New defaults must not reinterpret a saved explicit 8k/16k hard profile."""
    from crest.providers.gpt_researcher import public_settings

    config = load_config(write_master_config(**{
        'research.gpt_researcher.max_completion_tokens': 8000,
        'research.gpt_researcher.synthesis_max_completion_tokens': 16000,
        'research.gpt_researcher.budget_target_usd': 3.2,
        'research.gpt_researcher.synthesis_reserve_usd': .35,
        'research.gpt_researcher.budget_cap': 'hard',
    }))
    public = public_settings(config['research']['gpt_researcher'])
    assert public['max_output_tokens'] == 8000
    assert public['synthesis_max_output_tokens'] == 16000
    assert public['budget_target_usd'] == 3.2
    assert public['synthesis_reserve_usd'] == .35
    assert public['budget_cap'] == 'hard'


def test_gpt_answer_parallelism_uses_real_pipeline_limiter_without_collisions(tmp_path):
    """Fake answers exercise scheduling/storage only, never SDK or paid research."""
    import asyncio
    import json

    config = load_config()
    expected = copy.deepcopy(config['research']['gpt_researcher'])
    assert (expected['initial_concurrency'], expected['concurrency']) == (4, 8)
    config['research'] = {'gpt_researcher': expected}
    config.update(cache_dir=str(tmp_path / 'cache'), output_dir=str(tmp_path / 'results'))
    calls, controllers = [], []

    async def run():
        ready = [asyncio.Event() for _ in range(3)]
        release = [asyncio.Event() for _ in range(3)]
        arrivals = [0, 0, 0]
        sizes = (4, 6, 8)  # Real limiter grows by one after two completed answers.

        class BarrierProvider:
            ADAPTER_VERSION = 'offline-gpt-answer-barrier-v1'

            async def generate(self, prompt, settings, job):
                assert settings == expected and settings['deep_research_concurrency'] == 2
                assert job.key not in calls
                calls.append(job.key)
                controllers.append(job.rate_controller)
                assert job.rate_controller.snapshot()['maximum'] == 8
                wave = 0 if len(calls) <= 4 else 1 if len(calls) <= 10 else 2
                arrivals[wave] += 1
                if arrivals[wave] == sizes[wave]:
                    ready[wave].set()
                await release[wave].wait()
                return {'text': f'Offline answer {job.key}', 'model': settings['model'],
                        'citations': [], 'usage': {}, 'cost_usd': 0., 'warnings': [], 'raw': {}}

        pipeline = Pipeline(config, providers={'gpt_researcher': BarrierProvider()}, limit=18)
        task = asyncio.create_task(pipeline.generate())
        try:
            for wave, size in enumerate(sizes):
                await asyncio.wait_for(ready[wave].wait(), timeout=5)
                assert len({id(controller) for controller in controllers}) == 1
                snapshot = controllers[0].snapshot()
                assert snapshot['current'] == snapshot['active'] == size
                assert snapshot['maximum'] == 8
                release[wave].set()
            summary = await asyncio.wait_for(task, timeout=5)
        finally:
            for gate in release:
                gate.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return pipeline, summary

    pipeline, summary = asyncio.run(run())
    assert summary['planned'] == summary['completed'] == 18
    assert summary['failed'] == summary['cached'] == 0
    assert summary['parallelism']['gpt_researcher'] == {
        'current': 8, 'maximum': 8, 'active': 0, 'rate_limit_events': 0, 'peak_slots': 8}
    rows = pipeline.answers()
    assert len(rows) == len(calls) == 18
    for field in ('key', 'question_id', 'cache_record', 'answer_file'):
        assert len({row[field] for row in rows}) == 18
    stage = Path(summary['directory'])
    for row in rows:
        checkpoint = Path(row['cache_record'])
        assert checkpoint.is_relative_to(tmp_path / 'cache')
        assert json.loads(checkpoint.read_text())['result'] == row['result']
        assert (stage / row['answer_file']).read_text() == row['result']['text']
        assert row['result']['text'] == f"Offline answer {row['key']}"
    cached = asyncio.run(pipeline.generate())
    assert cached['completed'] == cached['cached'] == 18 and cached['failed'] == 0
    assert len(calls) == 18, 'Cached answers must not invoke the provider again'


@pytest.mark.parametrize('source', ['defaults', 'master', 'generation-jobs'])
def test_all_research_profiles_use_high_soft_budgets_without_xhigh_or_word_caps(source, tmp_path):
    config = copy.deepcopy(DEFAULTS) if source == 'defaults' else load_config()
    settings = config['research']
    if source == 'generation-jobs':
        config.update(cache_dir=str(tmp_path / 'cache'), output_dir=str(tmp_path / 'out'))
        settings = {job['agent']: job['settings'] for job in Pipeline(config, limit=1).generation_jobs()}
    assert set(settings) == {'caesar', 'openai', 'gemini', 'anthropic', 'gpt_researcher'}
    for name, values in settings.items():
        assert values['answer_word_limit'] is None, name
        assert values['budget_usd'] == 4, name
        assert values['budget_cap'] == 'soft', name
        assert not any(value == 'xhigh' for key, value in values.items()
                       if key.endswith(('effort', 'thinking_level'))), name
    assert settings['caesar']['reasoning_effort'] == 'medium'
    assert settings['caesar']['synthesis_reasoning_effort'] == 'high'
    assert settings['caesar']['exploration_reasoning_effort'] == 'low'
    assert settings['caesar']['kb_reasoning_effort'] == 'low'
    assert settings['openai']['reasoning_effort'] == 'high'
    assert settings['anthropic']['effort'] == 'high'
    assert settings['gpt_researcher']['reasoning_effort'] == 'high'


def test_direct_research_and_judge_fallbacks_use_high_reasoning():
    # Caesar's direct-worker fallback is covered by test_caesar_build_config_splits_research_and_synthesis_effort_with_headroom.
    from crest.providers import anthropic, gpt_researcher_worker, openai

    assert openai._payload('Question', {}, False)['reasoning']['effort'] == 'high'
    assert openai._payload('compare', {}, True)['reasoning'] == {'effort': 'high'}
    assert anthropic._payload([{'role': 'user', 'content': 'Question'}], {}, False)['output_config']['effort'] == 'high'
    upstream = gpt_researcher_worker.build_config({})
    assert upstream['REASONING_EFFORT'] == upstream['LLM_KWARGS']['reasoning_effort'] == 'high'

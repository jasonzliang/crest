import json
from types import SimpleNamespace

import pytest

from crest.config import load_questions
from crest.pipeline import Pipeline


@pytest.mark.parametrize('metadata', [{}, {'category': 'Cross-Domain Synthesis'}])
def test_questions_retain_optional_category_without_changing_text_or_id(tmp_path, metadata):
    path = tmp_path / 'questions.jsonl'
    path.write_text(json.dumps({'id': 'given-id', 'query': '  exact question?  ', **metadata}) + '\n')

    assert load_questions(path) == [
        {'id': 'given-id', 'text': '  exact question?  ', **metadata}
    ]


def test_category_metadata_does_not_change_derived_id_prompt_or_generation_key(tmp_path):
    path = tmp_path / 'questions.jsonl'
    row = {'query': '  exact question?  '}
    path.write_text(json.dumps(row) + '\n')
    config = {
        'questions': str(path), 'cache_dir': str(tmp_path / 'cache'),
        'research_prompt': 'QUESTION:\n{question}', 'research': {'openai': {}},
    }
    providers = {'openai': SimpleNamespace(ADAPTER_VERSION='fixture-v1')}
    original = Pipeline(config, providers=providers)
    original_jobs = original.generation_jobs()

    row['category'] = 'Cross-Domain Synthesis'
    path.write_text(json.dumps(row) + '\n')
    categorized = Pipeline(config, providers=providers)

    assert categorized.questions[0]['category'] == 'Cross-Domain Synthesis'
    assert categorized.questions[0]['id'] == original.questions[0]['id']
    assert categorized.generation_jobs() == original_jobs
    assert original_jobs[0]['prompt'] == 'QUESTION:\n  exact question?  '

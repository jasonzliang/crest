"""Local deterministic citation presentation, independent of provider and order."""

import pytest


@pytest.mark.parametrize(('raw', 'expected'), [
    ('Unlinked prose about OpenAI and Gemini is substantive.',
     'Unlinked prose about OpenAI and Gemini is substantive.'),
    ('Use [Paper title](https://publisher.test/paper?utm_source=chatgpt.com).',
     'Use [Paper title].'),
    ('Evidence [17](https://vertexaisearch.cloud.google.com/redirect/id).', 'Evidence [17].'),
    ('[Paper](https://example.test/path_(v2) "Full title")', '[Paper] "Full title"'),
    ('[**Paper**](https://example.test/a) and ![Diagram](https://example.test/figure.png).',
     '[**Paper**] and ![Diagram].'),
    ('Read <a href="https://example.test/?utm_source=gemini" title="Study title">the study</a>.',
     'Read [the study] "Study title".'),
    ('Read <a title="Study title" href=\'https://example.test/p\'><em>the study</em></a>.',
     'Read [<em>the study</em>] "Study title".'),
    ('See <https://example.test/p> and https://example.test/p.',
     'See [Source 1] and [Source 1].'),
    ('[OpenAI](https://example.test/a) [Gemini](https://other.test/b)',
     '[Source 1] [Source 2]'),
    ('[https://example.test/a](https://example.test/a) and [chatgpt.com](https://example.test/a)',
     '[Source 1] and [Source 1]'),
    ('[Google Search](https://example.test/a) [OpenAI study of scaling](https://example.test/b)',
     '[Source 1] [OpenAI study of scaling]'),
    ('Result [1].\n\n[1]: https://example.test/p "Study title"',
     'Result [1].\n\n[1]: [Source 1] "Study title"'),
    ('Read [Study][ref] and [ref][].\n\n[ref]: <https://example.test/p> \'Study title\'',
     'Read [Study][ref] and [ref][].\n\n[ref]: [Source 1] \'Study title\''),
    ('Sources: https://one.test/a, https://two.test/b; https://one.test/a.',
     'Sources: [Source 1], [Source 2]; [Source 1].'),
    ('Compare (https://example.test/path_(v2)) with www.example.test/p.',
     'Compare ([Source 1]) with [Source 2].'),
    ('Evidence citeturn0search0turn1search2 and [cite:7].',
     'Evidence [Source 1], [Source 2] and [7].'),
])
def test_preserves_citation_content_while_hiding_destinations(raw, expected):
    from crest.presentation import present_answer
    assert present_answer(raw) == expected
    assert present_answer(expected) == expected


def test_source_labels_do_not_depend_on_other_answers_or_tracking_identity():
    from crest.presentation import present_answer
    first = 'Evidence: https://publisher.test/a?utm_source=chatgpt.com and https://publisher.test/b.'
    second = 'Evidence: https://redirect.test/x?source=gemini and https://redirect.test/y.'
    assert present_answer(first) == present_answer(second) == 'Evidence: [Source 1] and [Source 2].'
    assert present_answer('Other https://unrelated.test.') == 'Other [Source 1].'
    assert present_answer(first) == 'Evidence: [Source 1] and [Source 2].'


def test_repeated_urls_differing_only_by_tracking_reuse_a_source_label():
    from crest.presentation import present_answer
    raw = 'https://example.test/p?utm_source=chatgpt.com https://example.test/p?utm_source=gemini'
    assert present_answer(raw) == '[Source 1] [Source 1]'


@pytest.mark.parametrize(('raw', 'expected'), [
    ('[Paper at https://publisher.test/p](https://redirect.test/r)', '[Paper at [Source 1]]'),
    ('[Paper](https://publisher.test/p "Mirror https://mirror.test/p")',
     '[Paper] "Mirror [Source 1]"'),
    ('<a href="https://publisher.test/p">Paper at https://mirror.test/p</a>',
     '[Paper at [Source 1]]'),
    ('[Google Search][ref]\n\n[ref]: https://publisher.test/p',
     '[Source 1][ref]\n\n[ref]: [Source 1]'),
])
def test_raw_urls_and_provider_labels_inside_link_markup_are_also_hidden(raw, expected):
    from crest.presentation import present_answer
    assert present_answer(raw) == expected


def test_native_opaque_identifiers_are_neutral_and_numeric_ids_are_retained():
    from crest.presentation import present_answer
    raw = ('Evidence citeturn0search0, citeturn0search0turn1search2 '
           'and cite17; [cite:opaque-provider-id], [cite:7].')
    rendered = present_answer(raw)
    assert rendered == ('Evidence [Source 1], [Source 1], [Source 2] '
                        'and [17]; [Source 3], [7].')
    assert 'turn0search' not in rendered
    assert 'opaque-provider-id' not in rendered
    assert 'cite:' not in rendered


@pytest.mark.parametrize('raw', [
    'The conditional probability is [p](x | y), where x and y are events.',
    'Evaluate [f](x) and compare [g](x + y).',
    '[p]: x | y\nThis is mathematical notation rather than an external source.',
])
def test_ambiguous_mathematical_bracket_notation_is_preserved(raw):
    from crest.presentation import present_answer
    assert present_answer(raw) == raw

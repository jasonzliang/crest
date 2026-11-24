"""Local deterministic citation presentation, independent of provider and order."""

import pytest

from crest.presentation import present_answer


@pytest.mark.parametrize(('raw', 'expected'), [
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
    ('Evidence \ue200cite\ue202turn0search0\ue202turn1search2\ue201 and [cite:7].',
     'Evidence [Source 1], [Source 2] and [7].'),
    # URLs differing only by tracking parameters reuse one label.
    ('https://example.test/p?utm_source=chatgpt.com https://example.test/p?utm_source=gemini',
     '[Source 1] [Source 1]'),
    # Raw URLs and provider labels inside link markup are also hidden.
    ('[Paper at https://publisher.test/p](https://redirect.test/r)', '[Paper at [Source 1]]'),
    ('[Paper](https://publisher.test/p "Mirror https://mirror.test/p")',
     '[Paper] "Mirror [Source 1]"'),
    ('<a href="https://publisher.test/p">Paper at https://mirror.test/p</a>',
     '[Paper at [Source 1]]'),
    ('[Google Search][ref]\n\n[ref]: https://publisher.test/p',
     '[Source 1][ref]\n\n[ref]: [Source 1]'),
    # Native opaque identifiers become neutral, repeated ones reuse a label, numeric IDs remain.
    ('Evidence \ue200cite\ue202turn0search0\ue201, \ue200cite\ue202turn0search0\ue202turn1search2\ue201 '
     'and \ue200cite\ue20217\ue201; [cite:opaque-provider-id], [cite:7].',
     'Evidence [Source 1], [Source 1], [Source 2] and [17]; [Source 3], [7].'),
    # Text without external destinations is unchanged.
    *[(text, text) for text in [
        'Unlinked prose about OpenAI and Gemini is substantive.',
        # Bracket notation in mathematics is not an external link.
        'The conditional probability is [p](x | y), where x and y are events.',
        'Evaluate [f](x) and compare [g](x + y).',
        '[p]: x | y\nThis is mathematical notation rather than an external source.',
    ]],
])
def test_preserves_citation_content_while_hiding_destinations(raw, expected):
    assert present_answer(raw) == expected
    assert present_answer(expected) == expected


def test_source_labels_do_not_depend_on_other_answers_or_tracking_identity():
    first = 'Evidence: https://publisher.test/a?utm_source=chatgpt.com and https://publisher.test/b.'
    second = 'Evidence: https://redirect.test/x?source=gemini and https://redirect.test/y.'
    assert present_answer(first) == present_answer(second) == 'Evidence: [Source 1] and [Source 2].'
    assert present_answer('Other https://unrelated.test.') == 'Other [Source 1].'
    assert present_answer(first) == 'Evidence: [Source 1] and [Source 2].'


# The pipeline appends collected URLs that the answer text never cites as a bare list.
APPENDED = ('Body cites [a paper](https://cited.test/p).\n\nSources:\n'
            'https://uncited.test/a\nhttps://uncited.test/b?utm_source=openai')


def test_research_presentation_drops_the_appended_list_of_uncited_sources():
    from crest.presentation import ANSWER_PRESENTATION_VERSION, PRESENTATION_VERSION, present_research_answer
    assert present_research_answer(APPENDED) == 'Body cites [a paper].'
    assert ANSWER_PRESENTATION_VERSION == 'citation-neutral-v2' != PRESENTATION_VERSION


@pytest.mark.parametrize('text', [
    'Body.\n\nSources:\nhttps://x.test/a\n\nMore prose after the list.',  # not a trailing list
    'Body cites https://x.test/a.\n\nSources:\nhttps://x.test/a',  # listed URL is cited
    'Body [1].\n\nSources:\n[1] https://x.test/a',  # numbered list written by the answer
    'Body.\n\n**Sources:**\nhttps://x.test/a',  # the answer's own markup
    '\n\nSources:\nhttps://x.test/a',  # nothing would remain
    'Body without any source list.',
])
def test_keeps_source_lists_that_are_cited_or_not_in_the_appended_form(text):
    from crest.presentation import drop_uncited_sources
    assert drop_uncited_sources(text) == text


def test_saved_v1_research_presentations_stay_reproducible():
    from crest.presentation import PRESENTATION_VERSION, present_research_answer
    assert present_research_answer(APPENDED, PRESENTATION_VERSION) == present_answer(APPENDED)
    with pytest.raises(ValueError, match='presentation'):
        present_research_answer(APPENDED, 'citation-neutral-v0')

"""Shared packaged rubric identities, without changing historical NUS inputs."""
from pathlib import Path


NUS_KIND = 'nus'
AUT_KIND = 'aut-inspired'
DEFAULT_NUS_RUBRIC = Path(__file__).resolve().parent / 'prompts' / 'nus_pairwise_v2.txt'
AUT_RUBRIC = DEFAULT_NUS_RUBRIC.with_name('aut_research_pairwise_v1.txt')
AUT_MARKER = 'RUBRIC ID: aut-inspired-pairwise-v1'
NUS_PROTOCOL = 'nus-overall-pairwise-v3'
AUT_PROTOCOL = 'aut-inspired-overall-pairwise-v1'


def rubric_kind(text: str) -> str:
    """Recognize explicit AUT opt-in; unmarked custom/legacy rubrics retain NUS."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError('rubric must be a nonempty string')
    markers = {line.strip() for line in text.splitlines() if line.strip().startswith('RUBRIC ID:')}
    if markers - {AUT_MARKER}:
        raise ValueError('Unsupported rubric identity marker')
    return AUT_KIND if AUT_MARKER in markers else NUS_KIND


def judging_protocol(text: str) -> str:
    return AUT_PROTOCOL if rubric_kind(text) == AUT_KIND else NUS_PROTOCOL


def protocol_rubric_kind(protocol: str | None) -> str:
    """Resolve frozen protocol identities; never silently relabel an unknown one."""
    if protocol in (None, 'nus-overall-pairwise-v2', NUS_PROTOCOL):
        return NUS_KIND
    if protocol == AUT_PROTOCOL:
        return AUT_KIND
    raise ValueError(f'Unsupported judging protocol: {protocol}')


def guidance_names(kind: str) -> str:
    if kind == NUS_KIND:
        return 'New, Useful, and Surprising'
    if kind == AUT_KIND:
        return 'Fluency, Flexibility, and Originality'
    raise ValueError(f'Unsupported rubric kind: {kind}')

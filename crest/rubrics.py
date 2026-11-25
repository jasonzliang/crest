"""Shared packaged rubric identities, without changing historical NUS inputs."""
import hashlib
import json
from pathlib import Path


NUS_KIND = 'nus'
AUT_KIND = 'aut-inspired'
DEFAULT_NUS_RUBRIC = Path(__file__).resolve().parent / 'prompts' / 'nus_pairwise_v3.txt'
AUT_RUBRIC = DEFAULT_NUS_RUBRIC.with_name('aut_pairwise_v1.txt')
AUT_MARKER = 'RUBRIC ID: aut-inspired-pairwise-v1'
# NUS_PROTOCOL keeps naming the frozen v3 protocol: report.py treats exactly this
# value as a strict-reason stage, so saved v3 stages must keep matching it.
NUS_PROTOCOL = 'nus-overall-pairwise-v3'
NUS_PROTOCOL_V3 = NUS_PROTOCOL
NUS_PROTOCOL_V4 = 'nus-overall-pairwise-v4'
CURRENT_NUS_PROTOCOL = NUS_PROTOCOL_V4
AUT_PROTOCOL = 'aut-inspired-overall-pairwise-v1'
# Protocols whose saved verdicts must pass the reason-quality screens.
STRICT_REASON_PROTOCOLS = (NUS_PROTOCOL_V3, NUS_PROTOCOL_V4, AUT_PROTOCOL)


def rubric_kind(text: str) -> str:
    """Recognize explicit AUT opt-in; unmarked custom/legacy rubrics retain NUS."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError('rubric must be a nonempty string')
    markers = {line.strip() for line in text.splitlines() if line.strip().startswith('RUBRIC ID:')}
    if markers - {AUT_MARKER}:
        raise ValueError('Unsupported rubric identity marker')
    return AUT_KIND if AUT_MARKER in markers else NUS_KIND


def judging_protocol(text: str) -> str:
    """The protocol new jobs use for this rubric's family."""
    return AUT_PROTOCOL if rubric_kind(text) == AUT_KIND else CURRENT_NUS_PROTOCOL


def protocol_rubric_kind(protocol: str | None) -> str:
    """Resolve frozen protocol identities; never silently relabel an unknown one."""
    if protocol in (None, 'nus-overall-pairwise-v2', NUS_PROTOCOL_V3, NUS_PROTOCOL_V4):
        return NUS_KIND
    if protocol == AUT_PROTOCOL:
        return AUT_KIND
    raise ValueError(f'Unsupported judging protocol: {protocol}')



def rubric_sha256(text: str) -> str:
    """SHA-256 of the exact rubric text judges received, encoded as UTF-8."""
    if not isinstance(text, str):
        raise ValueError('rubric must be a string')
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _packaged_nus_rubrics() -> list[tuple[str, Path, str]]:
    """(version, path, text) for every packaged NUS rubric, e.g. ('v3', .../nus_pairwise_v3.txt, ...)."""
    return [(path.stem.rsplit('_', 1)[-1], path, path.read_text(encoding='utf-8'))
            for path in sorted(DEFAULT_NUS_RUBRIC.parent.glob('nus_pairwise_v*.txt'))]


def rubric_identity(text: str, file_name: str | None = None) -> dict:
    """Record which rubric a judge read: ``{"file": name, "sha256": hex}``.

    The sha256 is the identity; the file name is a human-readable label from
    when the job was made. Without a name, a packaged NUS rubric is named by
    its exact text, and any other rubric records ``None``.
    """
    sha = rubric_sha256(text)
    if file_name is None:
        file_name = next((path.name for _, path, packaged in _packaged_nus_rubrics() if packaged == text), None)
    elif not isinstance(file_name, str) or not file_name:
        raise ValueError('rubric file name must be a nonempty string')
    return {'file': file_name, 'sha256': sha}


def resolve_rubric_version(rubric_id: dict | None = None, text: str | None = None) -> str | None:
    """Name a packaged NUS rubric ('v1', 'v2', 'v3', ...) by sha256 first, then exact text.

    ``rubric_id`` is a recorded identity; its file name is never trusted, so a
    renamed file still resolves by content. A recorded sha256 that disagrees
    with the saved text raises. Returns None for an unpackaged or AUT rubric.
    """
    if rubric_id is None and text is None:
        raise ValueError('Resolving a rubric needs a rubric_id or the rubric text')
    sha = None
    if rubric_id is not None:
        sha = rubric_id.get('sha256') if isinstance(rubric_id, dict) else None
        if not isinstance(sha, str) or len(sha) != 64:
            raise ValueError('rubric_id must record a sha256 hex digest')
        if text is not None and rubric_sha256(text) != sha:
            raise ValueError('Recorded rubric sha256 differs from the saved rubric text')
    packaged = _packaged_nus_rubrics()
    if sha is not None:
        for version, _, packaged_text in packaged:
            if rubric_sha256(packaged_text) == sha:
                return version
    if text is not None:
        for version, _, packaged_text in packaged:
            if packaged_text == text:
                return version
    return None


def resolve_stage_rubric_version(stage_dir) -> str | None:
    """Resolve a saved judge stage from its manifest rubric_id and/or rubric.txt."""
    stage = Path(stage_dir)
    manifest_path, text_path = stage / 'manifest.json', stage / 'rubric.txt'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.is_file() else {}
    text = text_path.read_text(encoding='utf-8') if text_path.is_file() else None
    return resolve_rubric_version(manifest.get('rubric_id'), text)

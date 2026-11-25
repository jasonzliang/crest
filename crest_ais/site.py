"""Canonical documentation catalog and reproducible page-update dates.

Directory landing pages deliberately retain index.html. Study/run dates are
never inputs to page_updated(): this stamp describes the HTML publication only.
"""
from datetime import date, datetime, timezone
import os
from pathlib import Path
import re

# Repository-relative paths. Old paths are compatibility redirects, not copies. Pages in docs/
# live in one folder per index section; only docs/index.html stays at the top.
PAGES = ({'old': 'docs/judging/nus-rubric.html',
  'canonical': 'docs/judging/nus-rubric.html',
  'label': 'NUS Rubric',
  'updated': '2026-11-05'},
 {'old': 'docs/judging/aut-inspired-rubric.html',
  'canonical': 'docs/judging/aut-inspired-rubric.html',
  'label': 'AUT-Inspired Rubric',
  'updated': '2026-11-05'},
 {'old': 'docs/judging/why-one-overall-judgment.html',
  'canonical': 'docs/judging/why-one-overall-judgment.html',
  'label': 'Why One Overall Judgment',
  'updated': '2026-11-05'},
 {'old': 'docs/judging/judge-models.html',
  'canonical': 'docs/judging/judge-models.html',
  'label': 'Judge Models',
  'updated': '2026-11-05'},
 {'old': 'docs/deep-research/research-pipeline.html',
  'canonical': 'docs/deep-research/research-pipeline.html',
  'label': 'Research Pipeline',
  'updated': '2026-11-05'},
 {'old': 'docs/deep-research/deep-research-comparison-v3.html',
  'canonical': 'docs/deep-research/deep-research-comparison-v3.html',
  'label': 'Deep Research Comparison v3',
  'updated': '2026-11-24'},
 {'old': 'docs/deep-research/deep-research-comparison-v2.html',
  'canonical': 'docs/deep-research/deep-research-comparison-v2.html',
  'label': 'Deep Research Comparison v2',
  'updated': '2026-11-05'},
 {'old': 'docs/deep-research/deep-research-comparison-v1.html',
  'canonical': 'docs/deep-research/deep-research-comparison-v1.html',
  'label': 'Deep Research Comparison v1',
  'updated': '2026-11-05'},
 {'old': 'docs/deep-research/open-source-research-agents.html',
  'canonical': 'docs/deep-research/open-source-research-agents.html',
  'label': 'Open-Source Research Agents',
  'updated': '2026-11-05'},
 {'old': 'docs/ai-scientists/ai-scientist-comparison-method.html',
  'canonical': 'docs/ai-scientists/ai-scientist-comparison-method.html',
  'label': 'AI Scientist Comparison Method',
  'updated': '2026-11-05'},
 {'old': 'docs/ai-scientists/ai-scientist-comparison-v1.html',
  'canonical': 'docs/ai-scientists/ai-scientist-comparison-v1.html',
  'label': 'AI Scientist Comparison v1',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/index.html',
  'canonical': 'crest/_archive/index.html',
  'label': 'Historical Material',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/reference/original-project-overview.html',
  'canonical': 'crest/_archive/reference/original-project-overview.html',
  'label': 'Original Project Overview',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/reference/original-runtime-notes.html',
  'canonical': 'crest/_archive/reference/historical-runtime-notes.html',
  'label': 'Historical Runtime Notes',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/related-work.html',
  'canonical': 'crest/_archive/research/doc/related-work.html',
  'label': 'Related Work',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/design.html',
  'canonical': 'crest/_archive/research/doc/benchmark-design-p2.html',
  'label': 'Benchmark Design P2',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/benchmark-best-practices.html',
  'canonical': 'crest/_archive/research/doc/benchmark-construction.html',
  'label': 'Benchmark Construction',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/misc/category-coverage.html',
  'canonical': 'crest/_archive/research/doc/misc/category-coverage.html',
  'label': 'Category Coverage',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/misc/field-justification.html',
  'canonical': 'crest/_archive/research/doc/misc/field-justification.html',
  'label': 'Field Justification',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/datasheet.html',
  'canonical': 'crest/_archive/research/doc/dataset-datasheet.html',
  'label': 'Dataset Datasheet',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/misc/aiml-dataset-build.html',
  'canonical': 'crest/_archive/research/doc/misc/ai-ml-dataset-build.html',
  'label': 'AI/ML Dataset Build',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/misc/caesar-question-comparison.html',
  'canonical': 'crest/_archive/research/doc/misc/caesar-question-comparison.html',
  'label': 'Caesar Question Comparison',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/item-vetting.html',
  'canonical': 'crest/_archive/research/doc/item-vetting.html',
  'label': 'Item Vetting',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/hallucination-audit.html',
  'canonical': 'crest/_archive/research/doc/hallucination-audit.html',
  'label': 'Hallucination Audit',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/misc/audit-live-c1.html',
  'canonical': 'crest/_archive/research/doc/misc/citation-audit-c1.html',
  'label': 'Citation Audit C1',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/misc/audit-live-c2.html',
  'canonical': 'crest/_archive/research/doc/misc/citation-audit-c2.html',
  'label': 'Citation Audit C2',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/misc/audit-live-c3.html',
  'canonical': 'crest/_archive/research/doc/misc/citation-audit-c3.html',
  'label': 'Citation Audit C3',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/misc/audit-live-c4-c5.html',
  'canonical': 'crest/_archive/research/doc/misc/citation-audit-c4-and-c5.html',
  'label': 'Citation Audit C4 and C5',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/misc/audit-live-c4-remainder.html',
  'canonical': 'crest/_archive/research/doc/misc/citation-audit-c4-remainder.html',
  'label': 'Citation Audit C4 Remainder',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/misc/audit-live-c5-remainder.html',
  'canonical': 'crest/_archive/research/doc/misc/citation-audit-c5-remainder.html',
  'label': 'Citation Audit C5 Remainder',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/paper/p2_benchmark_only/crest-paper-outline.html',
  'canonical': 'crest/_archive/research/paper/p2_benchmark_only/iclr-2027-paper-outline-p2.html',
  'label': 'ICLR 2027 Paper Outline P2',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/misc/paper-comparison.html',
  'canonical': 'crest/_archive/research/doc/misc/paper-comparison-p2-and-p3.html',
  'label': 'Paper Comparison P2 and P3',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/paper/p2_benchmark_only/reviewer-objections.html',
  'canonical': 'crest/_archive/research/paper/p2_benchmark_only/reviewer-objections.html',
  'label': 'Reviewer Objections',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/misc/iclr-metareview.html',
  'canonical': 'crest/_archive/research/doc/misc/iclr-meta-review.html',
  'label': 'ICLR Meta-Review',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/runs/run-outputs.html',
  'canonical': 'crest/_archive/research/doc/runs/run-outputs.html',
  'label': 'Run Outputs',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/runs/run-2026-08-01-0317.html',
  'canonical': 'crest/_archive/research/doc/runs/run-2026-08-01-03-17-utc.html',
  'label': 'Run 2026-08-01 03:17 UTC',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/runs/run-2026-08-01-0154.html',
  'canonical': 'crest/_archive/research/doc/runs/run-2026-08-01-01-54-utc.html',
  'label': 'Run 2026-08-01 01:54 UTC',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/runs/run-2026-07-31-1938.html',
  'canonical': 'crest/_archive/research/doc/runs/run-2026-07-31-19-38-utc.html',
  'label': 'Run 2026-07-31 19:38 UTC',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/runs/run-2026-07-31-0406.html',
  'canonical': 'crest/_archive/research/doc/runs/run-2026-07-31-04-06-utc.html',
  'label': 'Run 2026-07-31 04:06 UTC',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/runs/aborted-runs.html',
  'canonical': 'crest/_archive/research/doc/runs/aborted-runs.html',
  'label': 'Aborted Runs',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/runtime/index.html',
  'canonical': 'crest/_archive/runtime/index.html',
  'label': 'Archived Runtime',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/runtime/judge/rubric.html',
  'canonical': 'crest/_archive/runtime/judge/judge-rubric.html',
  'label': 'Judge Rubric',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/judge-protocol-intent.html',
  'canonical': 'crest/_archive/research/doc/judge-protocol-intent.html',
  'label': 'Judge Protocol Intent',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/runtime/eval/index.html',
  'canonical': 'crest/_archive/runtime/eval/index.html',
  'label': 'Evaluation Scripts',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/misc/deep-research-apis.html',
  'canonical': 'crest/_archive/research/doc/misc/deep-research-apis.html',
  'label': 'Deep Research APIs',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/entrypoints/index.html',
  'canonical': 'crest/_archive/entrypoints/index.html',
  'label': 'Archived Stage Wrappers',
  'updated': '2026-11-05'},
 {'old': 'docs/index.html',
  'canonical': 'docs/index.html',
  'label': 'CREST Documentation',
  'updated': '2026-11-05'})


def page_path(label: str) -> Path:
    """Return a canonical repository-relative path by its public page label.

    Matching ignores case, so callers written before labels were title-cased
    (for example ``page_path('NUS rubric')``) still resolve.
    """
    key = label.casefold()
    return Path(next(p['canonical'] for p in PAGES if p['label'].casefold() == key))


def page_href(label: str, origin: str) -> str:
    """Relative URL from the page labelled ``origin`` to the page labelled ``label``."""
    return Path(os.path.relpath(page_path(label), page_path(origin).parent)).as_posix()


def page_title(destination: Path, fallback: str) -> str:
    """Use catalog labels for recognized report filenames, including old URLs."""
    name = Path(destination).name
    return next((p['label'] for p in PAGES if name != 'index.html' and
                 name in (Path(p['canonical']).name, Path(p['old']).name)), fallback)


def page_updated(updated: str | None = None) -> str:
    """Explicit date, CREST_PAGE_UPDATED, SOURCE_DATE_EPOCH, then UTC build date.

    Pass updated='YYYY-MM-DD' (or set the environment variable) to reproduce
    a publication. Invalid overrides fail rather than silently misdate a page.
    """
    value = updated if updated is not None else os.environ.get('CREST_PAGE_UPDATED')
    if value is not None:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise ValueError('Page update date must be YYYY-MM-DD')
        return date.fromisoformat(value).isoformat()
    epoch = os.environ.get('SOURCE_DATE_EPOCH')
    if epoch is not None:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).date().isoformat()
    return datetime.now(timezone.utc).date().isoformat()


def require_canonical_output(destination: Path, project_root: Path | None = None) -> None:
    """Do not let a regeneration replace a compatibility URL or publish a page outside its folder."""
    name = Path(destination).name
    alias = next((p for p in PAGES if p['old'] != p['canonical'] and
                  Path(p['old']).name == name), None)
    if alias:
        raise ValueError(f'Use canonical output filename {Path(alias["canonical"]).name}; {name} is a compatibility redirect')
    if project_root is None:
        return
    root, target = Path(project_root).resolve(), Path(destination).resolve()
    if not target.is_relative_to(root / 'docs') or target == root / 'docs/index.html':
        return
    page = next((p for p in PAGES if Path(p['canonical']).name == name), None)
    if page and target != root / page['canonical']:
        raise ValueError(f'Use canonical output path {page["canonical"]}; {name} belongs in that folder')
    if target.parent == root / 'docs':
        raise ValueError(f'Only index.html stays at the top of docs/; publish {name} in a section folder')


def prepare_index_date(project_root: Path, destination: Path, updated: str) -> tuple[Path, str] | None:
    """Validate and prepare date wrappers without changing any publication files.

    Standalone exports outside this site's canonical paths do not edit its index.
    Call before replacing a report so malformed index markup preserves both files.
    """
    from html import escape
    from urllib.parse import quote

    root, target = Path(project_root).resolve(), Path(destination).resolve()
    if not any(root / p['canonical'] == target for p in PAGES):
        return
    index = root / 'docs/index.html'
    if not index.exists():
        return
    stamp = page_updated(updated)
    href = escape(quote(os.path.relpath(target, index.parent), safe='/._-'), quote=True)
    source = index.read_text(encoding='utf-8')
    # Bounded tags, not a DOM round-trip or a wildcard spanning arbitrary HTML.
    pattern = (r'(<a\b[^>]*\bhref="' + re.escape(href) + r'"[^>]*>[^<]*</a>\s*)'
               r'<time class="page-link-date" datetime="[^"]*">[^<]*</time>')
    replacement = f'<time class="page-link-date" datetime="{stamp}">Updated {stamp}</time>'
    revised, count = re.subn(pattern, lambda match: match[1] + replacement, source)
    if count != 1:
        raise ValueError(f'Expected one dated index entry for {href}; found {count}')
    revised = re.sub(r'<time class="crest-page-updated" datetime="[^"]*">[^<]*</time>',
                     f'<time class="crest-page-updated" datetime="{stamp}">Updated {stamp}</time>', revised, count=1)
    return None if revised == source else (index, revised)


def write_index_date(prepared: tuple[Path, str] | None) -> None:
    """Atomically write an already validated index update."""
    import tempfile

    if prepared is None:
        return
    index, revised = prepared
    fd, temporary = tempfile.mkstemp(prefix='.index-', suffix='.html', dir=index.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(revised)
        os.replace(temporary, index)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def sync_index_date(project_root: Path, destination: Path, updated: str) -> None:
    """Synchronize a published page's index entry and the index page date."""
    write_index_date(prepare_index_date(project_root, destination, updated))

"""Canonical documentation catalog and reproducible page-update dates.

Directory landing pages deliberately retain index.html. Study/run dates are
never inputs to page_updated(): this stamp describes the HTML publication only.
"""
from datetime import date, datetime, timezone
import os
from pathlib import Path
import re

# Repository-relative paths. Old paths are compatibility redirects, not copies.
PAGES = ({'old': 'docs/judging-method.html',
  'canonical': 'docs/nus-rubric.html',
  'label': 'NUS rubric',
  'updated': '2026-11-05'},
 {'old': 'docs/aut-inspired-rubric.html',
  'canonical': 'docs/aut-inspired-rubric.html',
  'label': 'AUT-inspired rubric',
  'updated': '2026-11-05'},
 {'old': 'docs/overall-creativity-judgment.html',
  'canonical': 'docs/why-one-overall-judgment.html',
  'label': 'Why one overall judgment',
  'updated': '2026-11-05'},
 {'old': 'docs/judge-models.html',
  'canonical': 'docs/judge-models.html',
  'label': 'Judge models',
  'updated': '2026-11-05'},
 {'old': 'docs/crest-guide.html',
  'canonical': 'docs/research-pipeline.html',
  'label': 'Research pipeline',
  'updated': '2026-11-05'},
 {'old': 'docs/deep-research-creativity-v2.html',
  'canonical': 'docs/deep-research-comparison-v2.html',
  'label': 'Deep research comparison v2',
  'updated': '2026-11-05'},
 {'old': 'docs/deep-research-creativity.html',
  'canonical': 'docs/deep-research-comparison-v1.html',
  'label': 'Deep research comparison v1',
  'updated': '2026-11-05'},
 {'old': 'docs/open-source-research-agents.html',
  'canonical': 'docs/open-source-research-agents.html',
  'label': 'Open-source research agents',
  'updated': '2026-11-05'},
 {'old': 'docs/ai-scientist-method.html',
  'canonical': 'docs/ai-scientist-comparison-method.html',
  'label': 'AI scientist comparison method',
  'updated': '2026-11-05'},
 {'old': 'docs/ai-scientist-creativity.html',
  'canonical': 'docs/ai-scientist-comparison-v1.html',
  'label': 'AI scientist comparison v1',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/index.html',
  'canonical': 'crest/_archive/index.html',
  'label': 'Historical material',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/reference/original-project-overview.html',
  'canonical': 'crest/_archive/reference/original-project-overview.html',
  'label': 'Original project overview',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/reference/original-runtime-notes.html',
  'canonical': 'crest/_archive/reference/historical-runtime-notes.html',
  'label': 'Historical runtime notes',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/related-work.html',
  'canonical': 'crest/_archive/research/doc/related-work.html',
  'label': 'Related work',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/design.html',
  'canonical': 'crest/_archive/research/doc/benchmark-design-p2.html',
  'label': 'Benchmark design P2',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/benchmark-best-practices.html',
  'canonical': 'crest/_archive/research/doc/benchmark-construction.html',
  'label': 'Benchmark construction',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/misc/category-coverage.html',
  'canonical': 'crest/_archive/research/doc/misc/category-coverage.html',
  'label': 'Category coverage',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/misc/field-justification.html',
  'canonical': 'crest/_archive/research/doc/misc/field-justification.html',
  'label': 'Field justification',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/datasheet.html',
  'canonical': 'crest/_archive/research/doc/dataset-datasheet.html',
  'label': 'Dataset datasheet',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/misc/aiml-dataset-build.html',
  'canonical': 'crest/_archive/research/doc/misc/ai-ml-dataset-build.html',
  'label': 'AI/ML dataset build',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/misc/caesar-question-comparison.html',
  'canonical': 'crest/_archive/research/doc/misc/caesar-question-comparison.html',
  'label': 'Caesar question comparison',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/item-vetting.html',
  'canonical': 'crest/_archive/research/doc/item-vetting.html',
  'label': 'Item vetting',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/hallucination-audit.html',
  'canonical': 'crest/_archive/research/doc/hallucination-audit.html',
  'label': 'Hallucination audit',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/misc/audit-live-c1.html',
  'canonical': 'crest/_archive/research/doc/misc/citation-audit-c1.html',
  'label': 'Citation audit C1',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/misc/audit-live-c2.html',
  'canonical': 'crest/_archive/research/doc/misc/citation-audit-c2.html',
  'label': 'Citation audit C2',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/misc/audit-live-c3.html',
  'canonical': 'crest/_archive/research/doc/misc/citation-audit-c3.html',
  'label': 'Citation audit C3',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/misc/audit-live-c4-c5.html',
  'canonical': 'crest/_archive/research/doc/misc/citation-audit-c4-and-c5.html',
  'label': 'Citation audit C4 and C5',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/misc/audit-live-c4-remainder.html',
  'canonical': 'crest/_archive/research/doc/misc/citation-audit-c4-remainder.html',
  'label': 'Citation audit C4 remainder',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/misc/audit-live-c5-remainder.html',
  'canonical': 'crest/_archive/research/doc/misc/citation-audit-c5-remainder.html',
  'label': 'Citation audit C5 remainder',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/paper/p2_benchmark_only/crest-paper-outline.html',
  'canonical': 'crest/_archive/research/paper/p2_benchmark_only/iclr-2027-paper-outline-p2.html',
  'label': 'ICLR 2027 paper outline P2',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/misc/paper-comparison.html',
  'canonical': 'crest/_archive/research/doc/misc/paper-comparison-p2-and-p3.html',
  'label': 'Paper comparison P2 and P3',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/paper/p2_benchmark_only/reviewer-objections.html',
  'canonical': 'crest/_archive/research/paper/p2_benchmark_only/reviewer-objections.html',
  'label': 'Reviewer objections',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/misc/iclr-metareview.html',
  'canonical': 'crest/_archive/research/doc/misc/iclr-meta-review.html',
  'label': 'ICLR meta-review',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/runs/run-outputs.html',
  'canonical': 'crest/_archive/research/doc/runs/run-outputs.html',
  'label': 'Run outputs',
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
  'label': 'Aborted runs',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/runtime/index.html',
  'canonical': 'crest/_archive/runtime/index.html',
  'label': 'Archived runtime',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/runtime/judge/rubric.html',
  'canonical': 'crest/_archive/runtime/judge/judge-rubric.html',
  'label': 'Judge rubric',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/judge-protocol-intent.html',
  'canonical': 'crest/_archive/research/doc/judge-protocol-intent.html',
  'label': 'Judge protocol intent',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/runtime/eval/index.html',
  'canonical': 'crest/_archive/runtime/eval/index.html',
  'label': 'Evaluation scripts',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/research/doc/misc/deep-research-apis.html',
  'canonical': 'crest/_archive/research/doc/misc/deep-research-apis.html',
  'label': 'Deep research APIs',
  'updated': '2026-11-05'},
 {'old': 'crest/_archive/entrypoints/index.html',
  'canonical': 'crest/_archive/entrypoints/index.html',
  'label': 'Archived stage wrappers',
  'updated': '2026-11-05'},
 {'old': 'docs/index.html',
  'canonical': 'docs/index.html',
  'label': 'CREST documentation',
  'updated': '2026-11-05'})


def page_path(label: str) -> Path:
    """Return a canonical repository-relative path by its public page label."""
    return Path(next(p['canonical'] for p in PAGES if p['label'] == label))


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


def require_canonical_output(destination: Path) -> None:
    """Do not let a regeneration replace a compatibility URL with a full report."""
    name = Path(destination).name
    alias = next((p for p in PAGES if p['old'] != p['canonical'] and
                  Path(p['old']).name == name), None)
    if alias:
        raise ValueError(f'Use canonical output filename {Path(alias["canonical"]).name}; {name} is a compatibility redirect')


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

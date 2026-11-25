"""Canonical documentation catalog, public site URLs and reproducible page-update dates.

Directory landing pages deliberately retain index.html. Study/run dates are
never inputs to page_updated(): this stamp describes the HTML publication only.

GitHub Pages serves docs/ ("Deploy from a branch": main, /docs) at SITE_URL. The
registry below is the one place for each served page's search title, description
and social/structured-data type; crest_ais.navigation.page_head() turns a record
into <head> tags. After editing a record, or a hand-maintained page's date, run
``python -m crest_ais.site`` to refresh committed heads, links, the sitemap and 404 page.
"""
from datetime import date, datetime, timezone
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from urllib.parse import quote

SITE_URL = 'https://jasonzliang.github.io/crest/'
SITE_NAME = 'CREST'
SITE_ALTERNATE_NAME = 'Creativity of Research Agents'
REPOSITORY_URL = 'https://github.com/jasonzliang/crest'
REPOSITORY_BRANCH = 'main'
# Made for link previews; og:image needs its absolute URL and pixel size.
SOCIAL_IMAGE = {'path': 'docs/social-card.png', 'width': 1280, 'height': 640,
                'alt': 'CREST, Creativity of Research Agents: pairwise LLM judging of deep research '
                       'agents and AI scientist papers'}
# Served by GitHub Pages for any missing URL under SITE_URL, so its links are root-relative.
NOT_FOUND_PAGE = {'canonical': 'docs/404.html', 'label': 'Page Not Found', 'updated': '2026-11-25'}
SITEMAP = 'docs/sitemap.xml'
# Tells GitHub Pages to publish docs/ as-is instead of running Jekyll.
NO_JEKYLL = 'docs/.nojekyll'
PAGE_DATE = re.compile(r'<time class="crest-page-updated" datetime="(\d{4}-\d{2}-\d{2})">')

# Repository-relative paths. Old paths are compatibility redirects, not copies. Pages in docs/
# live in one folder per index section; only docs/index.html stays at the top. Served docs/
# pages also carry 'seo_title' (<title> and og:title; 'label' stays the heading and link
# text), a 50-160 character 'description', 'og_type' and a schema.org 'schema_type'.
PAGES = ({'old': 'docs/judging/nus-rubric.html',
  'canonical': 'docs/judging/nus-rubric.html',
  'label': 'NUS Rubric',
  'updated': '2026-11-05',
  'seo_title': 'NUS Creativity Rubric: New, Useful, Surprising · CREST',
  'description': 'NUS creativity rubric for LLM-as-a-judge: New, Useful and Surprising guide one overall A/B choice between research answers or papers, with worked examples.',
  'og_type': 'article',
  'schema_type': 'TechArticle'},
 {'old': 'docs/judging/aut-inspired-rubric.html',
  'canonical': 'docs/judging/aut-inspired-rubric.html',
  'label': 'AUT-Inspired Rubric',
  'updated': '2026-11-05',
  'seo_title': 'AUT-Inspired Creativity Rubric for LLM Judges · CREST',
  'description': 'Creativity rubric inspired by the Alternate Uses Task (AUT): fluency, flexibility and originality guide one overall A/B choice between answers or papers.',
  'og_type': 'article',
  'schema_type': 'TechArticle'},
 {'old': 'docs/judging/why-one-overall-judgment.html',
  'canonical': 'docs/judging/why-one-overall-judgment.html',
  'label': 'Why One Overall Judgment',
  'updated': '2026-11-05',
  'seo_title': 'Why One Overall Judgment: Joint vs. Criterion Votes · CREST',
  'description': 'Why CREST’s LLM judges make one overall creativity choice, not separate New, Useful and Surprising votes, with evidence from creativity studies and HD-Eval.',
  'og_type': 'article',
  'schema_type': 'TechArticle'},
 {'old': 'docs/judging/judge-models.html',
  'canonical': 'docs/judging/judge-models.html',
  'label': 'Judge Models',
  'updated': '2026-11-05',
  'seo_title': 'Judge Models: LLM-as-a-Judge Settings and Costs · CREST',
  'description': 'LLM-as-a-judge models in CREST: Claude Opus 5.5, GPT-6.1 Sol and Gemini 4 Argon at high effort, with request settings, token prices and cost assumptions.',
  'og_type': 'article',
  'schema_type': 'TechArticle'},
 {'old': 'docs/deep-research/research-pipeline.html',
  'canonical': 'docs/deep-research/research-pipeline.html',
  'label': 'Research Pipeline',
  'updated': '2026-11-05',
  'seo_title': 'Research Pipeline: Run the Deep Research Benchmark · CREST',
  'description': 'Run the CREST deep research benchmark: five systems answer 50 questions, then three LLM judges compare every pair of answers in both orders to rank them.',
  'og_type': 'article',
  'schema_type': 'TechArticle'},
 {'old': 'docs/deep-research/deep-research-comparison-v3.html',
  'canonical': 'docs/deep-research/deep-research-comparison-v3.html',
  'label': 'Deep Research Comparison v3',
  'updated': '2026-11-24',
  'seo_title': 'Deep Research Comparison v3: Creativity of 5 Agents · CREST',
  'description': 'Deep research agent creativity benchmark: Caesar, OpenAI, Anthropic, GPT Researcher and Google Deep Research, 50 questions, 3,000 pairwise LLM judgments.',
  'og_type': 'article',
  'schema_type': 'Report'},
 {'old': 'docs/deep-research/deep-research-comparison-v2.html',
  'canonical': 'docs/deep-research/deep-research-comparison-v2.html',
  'label': 'Deep Research Comparison v2',
  'updated': '2026-11-05',
  'seo_title': 'Deep Research Comparison v2 (Historical) · CREST',
  'description': 'Historical v2 deep research comparison: OpenAI Sol at xhigh effort with web search leads Caesar and Google Deep Research in 600 pairwise LLM judgments.',
  'og_type': 'article',
  'schema_type': 'Report'},
 {'old': 'docs/deep-research/deep-research-comparison-v1.html',
  'canonical': 'docs/deep-research/deep-research-comparison-v1.html',
  'label': 'Deep Research Comparison v1',
  'updated': '2026-11-05',
  'seo_title': 'Deep Research Comparison v1 (Historical) · CREST',
  'description': 'Historical v1 deep research comparison: Caesar leads OpenAI Sol with web search and Google Deep Research in 600 judgments by GPT-6 Astra and Gemini 4 Argon.',
  'og_type': 'article',
  'schema_type': 'Report'},
 {'old': 'docs/deep-research/open-source-research-agents.html',
  'canonical': 'docs/deep-research/open-source-research-agents.html',
  'label': 'Open-Source Research Agents',
  'updated': '2026-11-05',
  'seo_title': 'Open-Source Deep Research Agents · CREST',
  'description': 'Five open-source deep research agents with a creative step that run on an OpenAI key: Co-STORM, GPT-Researcher, open_deep_research, Virtual Lab and TTD-DR.',
  'og_type': 'article',
  'schema_type': 'TechArticle'},
 {'old': 'docs/ai-scientists/ai-scientist-comparison-method.html',
  'canonical': 'docs/ai-scientists/ai-scientist-comparison-method.html',
  'label': 'AI Scientist Comparison Method',
  'updated': '2026-11-05',
  'seo_title': 'AI Scientist Comparison Method · CREST',
  'description': 'How CREST compares AI scientist papers: 96 sampled pairs from ScientistOne, ScientistTwo and three Sakana systems, LLM judging, equal opponent weights.',
  'og_type': 'article',
  'schema_type': 'TechArticle'},
 {'old': 'docs/ai-scientists/ai-scientist-comparison-v1.html',
  'canonical': 'docs/ai-scientists/ai-scientist-comparison-v1.html',
  'label': 'AI Scientist Comparison v1',
  'updated': '2026-11-05',
  'seo_title': 'AI Scientist Comparison v1: Paper Creativity · CREST',
  'description': 'AI scientist paper creativity ranking: three LLM judges compare 86 papers from five systems in 572 judgments; Sakana Agentic Scientist (v3) ranks first.',
  'og_type': 'article',
  'schema_type': 'Report'},
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
  'updated': '2026-11-05',
  'seo_title': 'CREST: Creativity of Research Agents Benchmark',
  'description': 'CREST docs: creativity benchmark for deep research agents and AI scientist papers, with NUS and AUT-inspired rubrics, LLM judge settings, setup and results.',
  'og_type': 'website',
  'schema_type': 'WebSite'})


def published_pages() -> list[dict]:
    """Registry pages that GitHub Pages serves (those under docs/), the index first."""
    return sorted((p for p in PAGES if p['canonical'].startswith('docs/')),
                  key=lambda p: p['canonical'] != 'docs/index.html')


def published_page(project_root: Path, destination: Path) -> dict | None:
    """The served registry page written at destination, or None for any other output path."""
    root, target = Path(project_root).resolve(), Path(destination).resolve()
    return next((p for p in published_pages() if root / p['canonical'] == target), None)


def page_url(canonical: str) -> str:
    """Absolute site URL for a docs/ path; a directory's index.html is its bare folder URL."""
    relative = PurePosixPath(canonical).relative_to('docs').as_posix()
    if relative == 'index.html' or relative.endswith('/index.html'):
        relative = relative[:-len('index.html')]
    return SITE_URL + quote(relative, safe='/')


def repository_url(repo_path: str | PurePosixPath, *, directory: bool = False) -> str:
    """GitHub URL for a repository file (blob) or folder (tree) on the published branch."""
    return (f'{REPOSITORY_URL}/{"tree" if directory else "blob"}/{REPOSITORY_BRANCH}/'
            + quote(PurePosixPath(repo_path).as_posix(), safe='/'))


def page_date(project_root: Path, canonical: str) -> str:
    """The page-update date in a page's site header, else the date of its last commit."""
    match = PAGE_DATE.search((Path(project_root) / canonical).read_text(encoding='utf-8'))
    if match:
        return match[1]
    result = subprocess.run(['git', 'log', '-1', '--format=%cs', '--', canonical], cwd=project_root,
                            capture_output=True, text=True)
    stamp = result.stdout.strip()
    if result.returncode or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', stamp):
        raise ValueError(f'{canonical} has no page-update date and no commit date')
    return stamp


def sitemap_xml(project_root: Path) -> str:
    """Sitemap of every served registry page; lastmod is the date each page shows."""
    rows = ''.join(f'  <url>\n    <loc>{page_url(p["canonical"])}</loc>\n'
                   f'    <lastmod>{page_date(project_root, p["canonical"])}</lastmod>\n  </url>\n'
                   for p in published_pages())
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + rows + '</urlset>\n')


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


def write_text_atomic(path: Path, text: str) -> None:
    """Replace a file in one step, so an interrupted write leaves the old file."""
    import tempfile

    path = Path(path)
    # mkstemp files are private (0600); keep the existing mode, or the usual 0644 for new files.
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    fd, temporary = tempfile.mkstemp(prefix='.' + path.stem + '-', suffix=path.suffix, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_index_date(prepared: tuple[Path, str] | None) -> None:
    """Atomically write an already validated index update."""
    if prepared is None:
        return
    index, revised = prepared
    write_text_atomic(index, revised)


def sync_index_date(project_root: Path, destination: Path, updated: str) -> None:
    """Synchronize a published page's index entry and the index page date."""
    write_index_date(prepare_index_date(project_root, destination, updated))


def main(argv=None) -> int:
    """Refresh served pages' heads and links, then the sitemap, 404 page and .nojekyll; no API calls."""
    import argparse

    from .navigation import refresh_site

    parser = argparse.ArgumentParser(prog='python -m crest_ais.site', description=main.__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1],
                        help='Repository root (default: this checkout)')
    for path in refresh_site(parser.parse_args(argv).root):
        print(path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

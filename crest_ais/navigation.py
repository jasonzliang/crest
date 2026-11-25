"""Shared header, head metadata and link rules for CREST's HTML documentation."""
from html import escape, unescape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
from urllib.parse import quote, unquote, urlsplit

from .site import (NO_JEKYLL, NOT_FOUND_PAGE, PAGE_DATE, REPOSITORY_URL, SITE_ALTERNATE_NAME, SITE_NAME,
                   SITE_URL, SITEMAP, SOCIAL_IMAGE, page_path, page_title, page_updated, page_url,
                   published_page, published_pages, repository_url, sitemap_xml, write_text_atomic)

DATE_CSS = (
    ".crest-page-updated,.page-link-date{font-size:.75rem;color:#637380;white-space:nowrap;font-variant-numeric:tabular-nums}"
    ".crest-page-updated{margin-left:auto;text-align:right}"
    ".index-group .page-link-date{display:inline-block;margin-left:.65rem}"
)

INDEX_CSS = '.index-group li{display:grid;grid-template-columns:minmax(0,1fr) max-content;column-gap:.65rem;align-items:start}.index-group li>a{min-width:0}.index-group .page-link-date{grid-column:2;margin-left:0;text-align:right}.index-group .description{grid-column:1/-1}'

CSS = """
.skip,.skip-link{position:fixed;left:1rem;top:-100px;z-index:20;background:#172c3e;color:#fff;padding:.7rem 1rem}.skip:focus,.skip-link:focus{top:1rem}
.crest-site-header{display:block;margin:0;padding:0;border:0;background:#f5f8f9;color:#172c3e;font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.crest-site-header nav{display:flex;align-items:center;justify-content:flex-start;flex-wrap:wrap;gap:.35rem 1.5rem;max-width:1120px;margin:0 auto;padding:.65rem 1.5rem;font-size:.9rem;line-height:1.5}
.crest-site-header a{display:inline-flex;align-items:center;min-height:40px;margin:0;padding:.35rem 0;border:0;border-radius:0;background:transparent;color:#0b5967;font:inherit;text-decoration:none;text-underline-offset:3px}
.crest-site-header a:hover{background:transparent;text-decoration:underline}
.crest-site-header a:focus-visible{outline:3px solid #b4652b;outline-offset:4px}
.crest-site-header .crest-brand{font-weight:800;letter-spacing:.13em;font-size:1rem}
@media print{.crest-site-header{display:none}}
*,*::before,*::after{box-sizing:border-box}
.crest-site-header~main,body>main{max-width:1120px;margin:0 auto;padding:2.4rem 1.5rem 4rem}
html{color-scheme:light;scroll-padding-top:1.5rem}
body{margin:0;background:#fff;color:#172c3e;font:16px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;--ink:#172c3e;--muted:#526574;--accent:#0b5967;--line:#d7e1e6;--wash:#f5f8f9}
main{min-width:0}
main h1{font-size:clamp(2rem,3.8vw,3.1rem);line-height:1.16;letter-spacing:-.035em;font-weight:750;margin:.8rem 0 1.3rem;max-width:29ch;overflow-wrap:anywhere}
main h2{font-size:1.55rem;line-height:1.3;letter-spacing:-.025em;font-weight:700;margin:2.4rem 0 1rem;padding:0;border:0}
main h3,main .judgment h3{font-size:1.1rem;line-height:1.4;font-weight:700;margin:1.6rem 0 .7rem}
main h4,main h5,main h6{font-size:1rem;line-height:1.4;font-weight:650;margin:1.4rem 0 .5rem}
main .section-heading h2{margin:0}
main>section:not(.index-group)>h2:first-child{margin-top:0}
main>section{border-top:0}
#main-content>section{margin:2.2rem 0 0;padding-top:1.5rem}
#main-content>section~section{border-top:1px solid var(--line);padding-top:2rem}
#main-content>nav[aria-label="Report contents"]{display:flex;flex-wrap:wrap;gap:.5rem 1.2rem;margin:1.5rem 0;padding:1rem 0;border-bottom:1px solid var(--line)}
main>header,main .hero{border-bottom:0}
main .stats,main .judgment{border:0}
main p{margin:.65rem 0 1rem;line-height:1.7}
main ul,main ol{padding-left:1.5rem}main li{margin:.35rem 0}
main blockquote{margin:1rem 0;padding:.5rem 1rem;border-left:3px solid var(--accent);background:var(--wash)}
main hr{margin:1.5rem 0;border:0;border-top:1px solid var(--line)}
main img,main video{max-width:100%;height:auto}main svg{max-width:100%}
main .archive-note{margin:1rem 0;padding:.8rem 1rem;border-left:3px solid #997024;background:#fbf6e9;color:var(--ink);font-size:.9rem;line-height:1.7}
main a{color:#0b5967;text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:3px;overflow-wrap:anywhere}
main nav a{text-decoration:none}
main nav a:hover{text-decoration:underline}
main>nav{font-size:.9rem;line-height:1.6}
main .subtitle{font-size:1.06rem;line-height:1.65;color:#526574}
main .metadata,main .meta{font-size:.8rem;line-height:1.6;color:#526574}
main .small,main .chart-note,main .unit,main .notice,main .notice.compact,main .concept-definitions dd,main .overall-reason,main .answer-map,main .key-limits,main .canonical-names,main .history-label,main .archive-note,main .dated-note,main .sidebar-note,main .model-list>li,main .index-group .description{font-size:.9rem;line-height:1.7;font-weight:400}
main .legend,main .chart-legend,main .heatmap-legend,main .stats span,main .run-stats span,main .diagnostics{font-size:.9rem;line-height:1.6}
main small,main .score small,main .diagnostics small,main .paper-id,main .model-id,main .judge-comparison .model-id,main .file-path,main .judgment-pair .muted{font-size:.8rem;line-height:1.5;font-weight:400}
main code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:.86em;overflow-wrap:anywhere;background:#eef3f5;padding:.1rem .25rem;border-radius:3px}
main pre{font-size:.86rem;line-height:1.6;background:#eef3f5;border:0;border-radius:5px;padding:1rem 1.15rem;overflow:auto}
main pre code{font-size:1em;overflow-wrap:normal;background:transparent;padding:0;border-radius:0}
main .table-scroll{overflow:auto;border:0;border-radius:0;margin:1.2rem 0}
main table{width:100%;border-collapse:collapse;font-size:.9rem;line-height:1.6;text-align:left}
main th,main td{padding:.75rem .9rem;border:0;text-align:left;vertical-align:top}
main caption{font-size:.9rem;line-height:1.6;font-weight:400;text-align:left;padding:0 0 .75rem}
main .heatmap th,main .no-cell,main .unavailable{font-size:.9rem;line-height:1.6}
main th{background:#eaf1f3;color:#183d49;font-weight:650}
main tbody th{background:transparent}
main thead th{border-bottom:1px solid #d7e1e6}
main details{border:0;border-radius:0;padding:0;margin:1.2rem 0;background:transparent}
main details+details{border:0;margin-top:1.2rem}
main summary,main .paper-record summary{padding:.9rem 0;color:#0b5967;font-weight:650;font-size:.9rem;line-height:1.5;cursor:pointer}
main details[open]{padding-bottom:.3rem}
main details[open]>summary{border:0;margin-bottom:.5rem}
main .contents{background:#f5f8f9;border:0;border-radius:5px;padding:0 1rem}
main .contents .sidebar-note{display:block}
main .contents nav{display:block;columns:auto;padding:0 0 .5rem}
main .contents nav ul{list-style:none;padding:0;margin:0;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.4rem 1rem}
main .contents nav a{display:block;margin:0;padding:.25rem 0;background:transparent;font-size:.9rem;line-height:1.6}
main .section-nav{display:flex;flex-wrap:wrap;align-items:center;gap:.55rem .75rem;padding:0 0 1.4rem;margin:0 0 1.4rem;border:0;font-size:.9rem;line-height:1.6}
main .section-nav a{display:inline-flex;align-items:center;min-height:40px;padding:.45rem .7rem;border:0;border-radius:4px;background:#f5f8f9;color:#0b5967;text-decoration:none;white-space:nowrap}
main .section-nav a:hover{background:#e7eff1;text-decoration:underline}
main footer{margin-top:2.5rem;padding-top:1rem;border:0;font-size:.8rem;color:#526574}
main :focus-visible{outline:3px solid #b4652b;outline-offset:3px}
@media(max-width:650px){.crest-site-header nav{gap:.25rem 1rem;padding:.65rem 1.1rem}.crest-site-header~main,body>main{padding:1.7rem 1.1rem 3rem}main h2{font-size:1.35rem}main .contents nav ul{grid-template-columns:1fr}main .section-nav{gap:.5rem}main .section-nav a{font-size:.9rem;padding:.4rem .6rem}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
@media print{.crest-site-header~main,body>main{padding:0;max-width:none}body{font-size:10pt}main h1{font-size:25pt}main h2{font-size:16pt}main .section-nav{display:none}main .table-scroll{overflow:visible;border:0}main table{font-size:8.5pt}main pre{white-space:pre-wrap}}
"""
CSS += DATE_CSS + INDEX_CSS


def _docs_link(root: Path, parent: Path, path: Path, base: str | None) -> str:
    """Relative link from a page's folder, or base + docs/ path for a page served at any URL."""
    if base is None:
        return escape(quote(os.path.relpath(path, parent), safe="/._-"), quote=True)
    relative = Path(path).resolve().relative_to(root / 'docs').as_posix()
    return escape(base + quote('' if relative == 'index.html' else relative, safe='/'), quote=True)


def site_favicon(project_root: Path, destination: Path, *, base: str | None = None) -> str:
    """Use the same local icon in documentation and generated reports."""
    root = Path(project_root).resolve()
    href = _docs_link(root, Path(destination).resolve().parent, root / 'docs/favicon.svg', base)
    return f'<link rel="icon" type="image/svg+xml" href="{href}">'


def site_header(project_root: Path, destination: Path, *, research_report: Path | None = None,
                updated: str | None = None, base: str | None = None) -> str:
    """Site navigation; pass base (a root-relative site path) for a page served at many URLs."""
    root, parent = Path(project_root).resolve(), Path(destination).resolve().parent
    def link(path):
        return _docs_link(root, parent, path, base)
    comparison = research_report if research_report is not None else root / page_path('Deep Research Comparison v3')
    label = page_title(comparison, 'Deep Research Comparison')
    current = ' aria-current="page"' if research_report is not None else ''
    stamp = page_updated(updated)
    return ('<header class="crest-site-header"><nav aria-label="Documentation">'
            f'<a class="crest-brand" href="{REPOSITORY_URL}">{SITE_NAME}</a>'
            f'<a href="{link(root / page_path("Research Pipeline"))}">Research Pipeline</a>'
            f'<a href="{link(comparison)}"{current}>{escape(label)}</a>'
            f'<a href="{link(root / page_path("AI Scientist Comparison v1"))}">AI Scientist Comparison v1</a>'
            f'<a href="{link(root / "docs/index.html")}">All Documents</a>'
            f'<time class="crest-page-updated" datetime="{stamp}">Updated {stamp}</time>'
            '</nav></header>')


def site_href(project_root: Path, destination: Path, target: Path) -> str:
    """URL (percent-encoded, not HTML-escaped) from a page to a repository file.

    GitHub Pages serves only docs/, so a page published there links to other
    repository files on GitHub. Links within docs/, from pages kept outside docs/
    (such as local reports) and to files outside the repository stay relative.
    """
    root, page, target = (Path(p).resolve() for p in (project_root, destination, target))
    docs = root / 'docs'
    if page.is_relative_to(docs) and target.is_relative_to(root) and not target.is_relative_to(docs):
        if target == root:
            return REPOSITORY_URL
        return repository_url(target.relative_to(root).as_posix(), directory=target.is_dir())
    return quote(os.path.relpath(target, page.parent), safe='/')


def _json_ld(data: dict) -> str:
    """JSON that cannot close its <script> element or start markup inside it."""
    text = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    return text.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')


def page_head(project_root: Path, destination: Path, *, title: str, updated: str | None = None,
              description: str | None = None) -> str:
    """<title> and, for a page served from docs/, its search and link-preview tags.

    Every value comes from the page's PAGES record (its seo_title replaces title),
    so generated reports and refreshed hand-maintained pages carry identical tags.
    Other output paths get title and, if given, a fallback description.
    """
    record = published_page(project_root, destination)
    if record is None:
        return f'<title>{escape(title)}</title>' + (
            f'<meta name="description" content="{escape(description)}">' if description else '')
    url, image = page_url(record['canonical']), page_url(SOCIAL_IMAGE['path'])
    seo_title, summary = record['seo_title'], record['description']
    properties = (('og:type', record['og_type']), ('og:site_name', SITE_NAME), ('og:title', seo_title),
                  ('og:description', summary), ('og:url', url), ('og:image', image),
                  ('og:image:width', SOCIAL_IMAGE['width']), ('og:image:height', SOCIAL_IMAGE['height']),
                  ('og:image:alt', SOCIAL_IMAGE['alt']))
    if record['schema_type'] == 'WebSite':
        data = {'@context': 'https://schema.org', '@type': 'WebSite', 'name': SITE_NAME,
                'alternateName': SITE_ALTERNATE_NAME, 'url': url, 'description': summary, 'inLanguage': 'en'}
    else:
        # Only facts the page states: no author or first-publication date is recorded.
        data = {'@context': 'https://schema.org', '@type': record['schema_type'], 'headline': record['label'],
                'description': summary, 'url': url, 'image': image, 'dateModified': page_updated(updated),
                'inLanguage': 'en', 'isPartOf': {'@type': 'WebSite', 'name': SITE_NAME, 'url': SITE_URL}}
    return (f'<title>{escape(seo_title)}</title><meta name="description" content="{escape(summary)}">'
            f'<link rel="canonical" href="{escape(url)}">'
            + ''.join(f'<meta property="{name}" content="{escape(str(value))}">' for name, value in properties)
            + '<meta name="twitter:card" content="summary_large_image">'
            f'<script type="application/ld+json">{_json_ld(data)}</script>')


LINK_ATTRIBUTE = re.compile(r'(?<=\s)(href|src)=("[^"]*"|\'[^\']*\')', re.I)


def _portable_url(root: Path, page: Path, value: str) -> str | None:
    """GitHub URL for a relative link that leaves docs/, keeping query and fragment; else None."""
    url = urlsplit(value)
    if url.scheme or url.netloc or not url.path or url.path.startswith('/'):
        return None
    target = (page.parent / unquote(url.path)).resolve()
    if target.is_relative_to(root / 'docs') or not target.is_relative_to(root):
        return None
    return (site_href(root, page, target) + (f'?{url.query}' if url.query else '')
            + (f'#{url.fragment}' if url.fragment else ''))


class _LinkCounter(HTMLParser):
    """Counts href/src attributes as a browser parses them (script and style text excluded)."""

    def __init__(self, accept):
        super().__init__(convert_charrefs=True)
        self.accept, self.count = accept, 0

    def handle_starttag(self, tag, attrs):
        self.count += sum(1 for name, value in attrs if name in ('href', 'src') and value and self.accept(value))


def portable_links(project_root: Path, page: Path, source: str) -> str:
    """Point a docs/ page's links to repository files outside docs/ at GitHub.

    Only those attribute values change; markup is not reserialized. A parser
    count guards against rewriting look-alike text in scripts or prose.
    """
    root, page = Path(project_root).resolve(), Path(page).resolve()
    changed = 0

    def replace(match):
        nonlocal changed
        new = _portable_url(root, page, unescape(match[2][1:-1]))
        if new is None:
            return match[0]
        changed += 1
        return f'{match[1]}="{escape(new)}"'
    revised = LINK_ATTRIBUTE.sub(replace, source)
    if changed:
        counter = _LinkCounter(lambda value: _portable_url(root, page, value) is not None)
        counter.feed(source)
        counter.close()
        if counter.count != changed:
            raise ValueError(f'{page}: rewrote {changed} links that leave docs/, but the page has {counter.count}')
    return revised


_HEAD_TAG = re.compile(r'<meta\b[^>]*>|<link\b[^>]*>|<script\b[^>]*\btype="application/ld\+json"[^>]*>.*?</script>',
                       re.I | re.S)
_TAG_ATTRIBUTE = re.compile(r'([^\s=/>]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')')


def _is_page_metadata(tag: str) -> bool:
    """Tags page_head() owns: description, canonical, Open Graph, Twitter and JSON-LD."""
    if tag[:7].lower() == '<script':
        return True
    attributes = {m[1].lower(): unescape(m[2] if m[2] is not None else m[3]).strip().lower()
                  for m in _TAG_ATTRIBUTE.finditer(tag)}
    if tag[:5].lower() == '<link':
        return attributes.get('rel') == 'canonical'
    name, prop = attributes.get('name', ''), attributes.get('property', '')
    return name == 'description' or name.startswith('twitter:') or prop.startswith('og:')


def refresh_page(project_root: Path, path: Path) -> str:
    """A served page with its title and metadata from page_head() and portable links.

    The tags go where the report generators emit them, in place of <title>;
    earlier copies are removed. Nothing else in the page changes.
    """
    root, path = Path(project_root).resolve(), Path(path).resolve()
    record = published_page(root, path)
    if record is None:
        raise ValueError(f'{path} is not a page served from docs/')
    source = path.read_text(encoding='utf-8')
    end = source.lower().find('</head>')
    if end < 0:
        raise ValueError(f'{path} has no </head>')
    head, rest = source[:end], source[end:]
    pieces, last = [], 0
    for match in _HEAD_TAG.finditer(head):
        if _is_page_metadata(match[0]):
            start, stop = match.span()
            if head[start - 1:start] == '\n' and head[stop:stop + 1] == '\n':
                stop += 1  # the tag had its own line
            pieces.append(head[last:start])
            last = stop
    head = ''.join(pieces) + head[last:]
    titles = list(re.finditer(r'<title>[^<]*</title>', head))
    stamp = PAGE_DATE.search(rest)
    if len(titles) != 1 or stamp is None:
        raise ValueError(f'{path} needs one <title> and a dated site header')
    tags = page_head(root, path, title=record['label'], updated=stamp[1])
    return head[:titles[0].start()] + tags + head[titles[0].end():] + portable_links(root, path, rest)


def not_found_page(project_root: Path) -> str:
    """GitHub Pages' 404 page; root-relative links work at whatever URL it is served."""
    root = Path(project_root).resolve()
    destination, base = root / NOT_FOUND_PAGE['canonical'], urlsplit(SITE_URL).path
    label = escape(NOT_FOUND_PAGE['label'])
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light">'
            f'<meta name="robots" content="noindex"><title>{label} · {SITE_NAME}</title>'
            + site_favicon(root, destination, base=base) + f'<style>{CSS}</style></head><body>'
            '<a class="skip-link" href="#main-content">Skip to content</a>'
            + site_header(root, destination, updated=NOT_FOUND_PAGE['updated'], base=base)
            + f'<main id="main-content" tabindex="-1"><h1>{label}</h1>'
            '<p>There is no page at this address. The link may be mistyped or out of date.</p>'
            f'<p><a href="{escape(base)}">Browse all CREST documents</a>, or find the code and data in the '
            f'<a href="{escape(REPOSITORY_URL)}">CREST repository on GitHub</a>.</p></main></body></html>\n')


def refresh_site(project_root: Path) -> list[Path]:
    """Refresh served pages' heads and links, then write the sitemap, 404 page and .nojekyll.

    Works offline from committed files. Returns the files whose content changed.
    """
    root = Path(project_root).resolve()
    changed = []

    def write(path, text):
        if not path.exists() or path.read_text(encoding='utf-8') != text:
            write_text_atomic(path, text)
            changed.append(path)
    for record in published_pages():
        write(root / record['canonical'], refresh_page(root, root / record['canonical']))
    write(root / NOT_FOUND_PAGE['canonical'], not_found_page(root))
    write(root / SITEMAP, sitemap_xml(root))
    write(root / NO_JEKYLL, '')
    return changed

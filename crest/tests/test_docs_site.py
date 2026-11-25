"""Publication contracts: canonical URLs, page dates, and unchanged research evidence."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import unquote, urlsplit

from lxml import etree, html
import pytest

ROOT = Path(__file__).resolve().parents[2]
BASELINE = Path(__file__).with_name('docs_evidence_baseline.json')
# Evidence subtrees: these tags plus elements carrying any of these classes.
PROTECTED_TAGS = frozenset({'table', 'svg', 'pre', 'script', 'meta'})
PROTECTED_CLASSES = frozenset({'answer-text', 'reason', 'judgment', 'metadata', 'meta',
                               'question', 'paper-record'})
XML_SPACE = re.compile(r'[ \t\r\n]+')
SECTIONS = {'judging', 'deep-research', 'ai-scientists'}


def protected_elements(page):
    """Document-order evidence elements.

    One tree walk matches what the XPath ``//table | ... | //*[contains(concat(" ",
    normalize-space(@class), " "), " reason ")]`` union selected, several times faster.
    Class tokens split on XML whitespace, as normalize-space does.
    """
    for element in page.iter(etree.Element):
        classes = element.get('class')
        if element.tag in PROTECTED_TAGS or classes and not PROTECTED_CLASSES.isdisjoint(XML_SPACE.split(classes)):
            yield element


def evidence_fingerprints(source):
    """Hash evidence subtrees and all body content except the authorized wrappers.

    Parsing is for comparison only: production HTML is never reserialized.
    Navigation/H1 and link destinations may change, but every other body byte
    represented by the parser (including text, IDs, and data attributes) remains.
    Evidence subtrees additionally keep their original link destinations.
    """
    page = html.fromstring(source)
    def digest(value):
        return hashlib.sha256(value).hexdigest()
    protected = [digest(etree.tostring(e, with_tail=False)) for e in protected_elements(page)]
    # The tree is private to this call, so the body is normalized in place once
    # the protected subtrees have been hashed.
    body = page.find('body')
    for e in body.xpath('.//header[contains(concat(" ", @class, " "), " crest-site-header ")]'):
        e.drop_tree()
    for e in body.xpath('.//h1'):
        e.text = ''
        for child in list(e):
            e.remove(child)
    for e in body.xpath('.//a[@href]'):
        e.set('href', 'LINK')
    return {'body': digest(etree.tostring(body)), 'protected_count': len(protected),
            'protected': digest(''.join(protected).encode())}


def index_entries():
    page = html.fromstring((ROOT / 'docs/index.html').read_bytes())
    return page, page.xpath('//main//li/a')


def test_index_names_match_canonical_titles_headings_filenames_and_dates():
    page, entries = index_entries()
    local = [a for a in entries if not urlsplit(a.get('href')).scheme]
    assert len(local) == 46
    for a in local:
        target = (ROOT / 'docs' / a.get('href')).resolve()
        # Only the index sits at the top of docs/; every other page is in one section folder.
        if target.parent.parent == ROOT / 'docs':
            assert target.parent.name in SECTIONS, target
        label = a.text_content()
        slug = re.sub('[^a-z0-9]+', '-', label.lower()).strip('-') + '.html'
        assert target.name in (slug, 'index.html'), (label, target.name)
        document = html.fromstring(target.read_bytes())
        assert document.findtext('.//title') == label
        assert document.xpath('//h1')[0].text_content() == label
        stamp = document.xpath('//header[@class="crest-site-header"]/nav/time[@class="crest-page-updated"]')
        assert len(stamp) == 1
        assert re.fullmatch(r'\d{4}-\d{2}-\d{2}', stamp[0].get('datetime'))
        assert stamp[0].text == 'Updated ' + stamp[0].get('datetime')
        date = a.getnext()
        assert date.tag == 'time'
        assert date.get('datetime') == stamp[0].get('datetime')
        assert date.text == stamp[0].text
    external = [a for a in entries if urlsplit(a.get('href')).scheme]
    assert [(a.get('href'), a.text_content()) for a in external] == [
        ('https://github.com/jasonzliang/crest#readme', 'Project README'),
        ('https://llm-keys.evolution.ml/guide#claude-code', 'LiteLLM Gateway Setup'),
    ]
    assert len(entries) == 48
    assert page.xpath('//section[@id="current"]//li/a') == external
    for a in external:
        assert not a.getparent().xpath('.//time')
        assert a.getparent().xpath('./span[@class="description"]/text()')[0].strip()
    stamp = page.xpath('//header[@class="crest-site-header"]/nav/time[@class="crest-page-updated"]')
    assert len(stamp) == 1
    assert stamp[0].text == 'Updated ' + stamp[0].get('datetime')
    # sync_index_date moves the index date with each entry it updates.
    assert stamp[0].get('datetime') >= max(a.getnext().get('datetime') for a in local)


def test_all_site_pages_have_one_right_aligned_date():
    for folder in ('docs', 'crest/_archive'):
        for path in (ROOT / folder).rglob('*.html'):
            source = path.read_text()
            page = html.fromstring(source)
            headers = page.xpath('//header[@class="crest-site-header"]')
            if not headers:
                continue
            stamps = headers[0].xpath('.//time[@class="crest-page-updated"]')
            assert len(stamps) == 1, path
            assert stamps[0].getparent().tag == 'nav'
            assert stamps[0] is stamps[0].getparent()[-1], path
            assert stamps[0].text == 'Updated ' + stamps[0].get('datetime')
            # These declarations are the layout contract: the final flex item
            # consumes remaining space on its left and remains right-aligned.
            assert '.crest-page-updated{' in source
            rule = source.split('.crest-page-updated{', 1)[1].split('}', 1)[0]
            assert 'margin-left:auto' in rule and 'text-align:right' in rule


def test_historical_research_evidence_is_preserved():
    baseline = json.loads(BASELINE.read_text())
    assert len(baseline) == 46
    for name, expected in baseline.items():
        assert evidence_fingerprints((ROOT / name).read_bytes()) == expected, name


# Runs every redirect script in its own VM context inside one Node process; a
# process per script (26 per case) made these the slowest tests in the suite.
REDIRECT_HARNESS = r"""
const vm = require('vm');
const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
console.log(JSON.stringify(cases.map(({script, search, hash}) => {
  const link = {href: null};
  let result;
  vm.runInNewContext(script, {
    document: {getElementById: () => link},
    window: {location: {search, hash, replace: x => { result = x; }}},
  });
  return {result, href: link.href};
})));
"""
REDIRECT_QUERIES = [('', ''), ('?source=old%20link&x=1', '#method'), ('?next=%23method', '#answer%3Aone')]


def test_redirects_have_readable_canonical_fallbacks_and_scripts_preserve_query_and_fragment():
    from crest_ais.site import PAGES
    aliases = [p for p in PAGES if p['old'] != p['canonical']]
    assert len(aliases) == 19
    cases, expected = [], []
    for record in aliases:
        path = ROOT / record['old']
        page = html.fromstring(path.read_bytes())
        link = page.xpath('//main//a[@id="canonical-link"]')[0]
        assert link.text_content() == record['label']
        assert (path.parent / link.get('href')).resolve() == ROOT / record['canonical']
        assert path.stat().st_size < 15000
        assert page.xpath('//link[@rel="canonical"]/@href') == [link.get('href')]
        assert not page.xpath('//meta[translate(@http-equiv,"REFSH","refsh")="refresh"]')
        # Execute the actual script, not a duplicated implementation of it.
        script = page.xpath('//script/text()')[-1]
        for search, fragment in REDIRECT_QUERIES:
            cases.append({'script': script, 'search': search, 'hash': fragment})
            target = link.get('href') + search + fragment
            expected.append({'result': target, 'href': target})
    if shutil.which('node') is None:
        pytest.skip('Node is optional; needed to execute redirect JavaScript')
    output = subprocess.run(['node', '-e', REDIRECT_HARNESS], input=json.dumps(cases),
                            capture_output=True, text=True, check=True).stdout
    assert json.loads(output) == expected


def test_site_navigation_and_document_links_resolve_with_fragments():
    from crest_ais.site import PAGES
    aliases = {str((ROOT / p['old']).resolve()): ROOT / p['canonical'] for p in PAGES}
    anchors = {}  # Parse each target once; a per-link XPath scan of large pages was the cost.

    def anchor_names(path, page=None):
        if path not in anchors:
            page = html.fromstring(path.read_bytes()) if page is None else page
            anchors[path] = {value for element in page.iter(etree.Element)
                             for value in (element.get('id'), element.get('name')) if value is not None}
        return anchors[path]

    for record in PAGES:
        path = ROOT / record['canonical']
        page = html.fromstring(path.read_bytes())
        # Historical evidence can cite old URLs; compatibility pages keep these
        # working without rewriting saved answers, tables, or raw metadata.
        for link in page.xpath('//a[@href]'):
            url = urlsplit(link.get('href'))
            if url.scheme or url.netloc or (url.path and not url.path.endswith('.html')):
                continue
            target = (path.parent / unquote(url.path)).resolve() if url.path else path
            assert target.exists(), (path, link.get('href'))
            target = aliases.get(str(target), target)
            if url.fragment:
                names = anchor_names(path, page) if target == path else anchor_names(target)
                assert unquote(url.fragment) in names, (path, link.get('href'))


def test_generated_header_uses_canonical_links_and_reproducible_date(monkeypatch, tmp_path):
    from crest_ais.navigation import site_header
    monkeypatch.setenv('CREST_PAGE_UPDATED', '2026-11-05')
    fragment = html.fromstring(site_header(tmp_path, tmp_path / 'docs/report.html'))
    assert fragment.xpath('.//a/@href')[1:] == [
        'deep-research/research-pipeline.html', 'deep-research/deep-research-comparison-v3.html',
        'ai-scientists/ai-scientist-comparison-v1.html', 'index.html']
    assert fragment.xpath('.//time/@datetime') == ['2026-11-05']
    assert html.fromstring(site_header(tmp_path, tmp_path / 'docs/report.html', updated='2026-11-06')).xpath('.//time/@datetime') == ['2026-11-06']


def test_docs_top_level_holds_only_the_index_and_its_icon():
    tracked = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split('\n')
    docs = [Path(n).relative_to('docs') for n in tracked if n.startswith('docs/')]
    assert sorted(str(n) for n in docs if len(n.parts) == 1) == ['favicon.svg', 'index.html']
    assert {n.parts[0] for n in docs if len(n.parts) > 1} == SECTIONS
    names = [Path(n).name for n in tracked if n.endswith('.html')]
    # One saved upstream page keeps the filename its own saved links use.
    assert [n for n in names if not re.fullmatch(r'[a-z0-9]+(-[a-z0-9]+)*\.html', n)] == [
        'reviewer_release_and_performance.html']


def test_page_href_links_across_section_folders():
    from crest_ais.site import page_href
    assert page_href('NUS Rubric', 'Deep Research Comparison v3') == '../judging/nus-rubric.html'
    assert page_href('Deep Research Comparison v2', 'Deep Research Comparison v3') == 'deep-research-comparison-v2.html'
    assert page_href('AI Scientist Comparison Method', 'AI Scientist Comparison v1') == 'ai-scientist-comparison-method.html'


def test_page_path_matches_labels_without_regard_to_case():
    from crest_ais.site import page_path
    assert page_path('NUS Rubric') == page_path('NUS rubric') == Path('docs/judging/nus-rubric.html')
    assert page_path('why one overall judgment') == Path('docs/judging/why-one-overall-judgment.html')


def test_date_source_precedence_and_validation(monkeypatch):
    from crest_ais.site import page_updated
    monkeypatch.delenv('CREST_PAGE_UPDATED', raising=False)
    monkeypatch.setenv('SOURCE_DATE_EPOCH', '0')
    assert page_updated() == '1970-01-01'
    monkeypatch.setenv('CREST_PAGE_UPDATED', '2026-11-05')
    assert page_updated() == '2026-11-05'
    assert page_updated('2026-11-06') == '2026-11-06'
    for value in ('not a date', '2026-11-31', '20261105', '<script>'):
        with pytest.raises(ValueError):
            page_updated(value)


def test_page_and_index_dates_share_small_readable_muted_style():
    from crest_ais.navigation import DATE_CSS
    # The shared rule is used on the light page and the slightly darker header.
    # Rendered font is 12px (smaller than the former 12.8px); contrast stays AA.
    assert '.crest-page-updated,.page-link-date{' in DATE_CSS
    rule = DATE_CSS.split('.crest-page-updated,.page-link-date{', 1)[1].split('}', 1)[0]
    assert 'font-size:.75rem' in rule
    color = re.search(r'color:#([a-f0-9]{6})', rule)[1]
    def luminance(value):
        channels = [int(value[i:i+2], 16) / 255 for i in (0, 2, 4)]
        channels = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
        return sum(v * weight for v, weight in zip(channels, (.2126, .7152, .0722)))
    assert luminance(color) > luminance('526574')
    for background in ('ffffff', 'f5f8f9'):
        assert (luminance(background) + .05) / (luminance(color) + .05) >= 4.5
    for name in ('docs/index.html', 'docs/deep-research/deep-research-comparison-v2.html'):
        assert DATE_CSS in (ROOT / name).read_text()


def test_index_sync_updates_only_matching_entry_and_index_page_date(tmp_path):
    from crest_ais.site import sync_index_date
    docs = tmp_path / 'docs'; docs.mkdir()
    index = docs / 'index.html'
    original = ('<header><time class="crest-page-updated" datetime="2026-11-05">Updated 2026-11-05</time></header>'
                '<main><li><a href="deep-research/deep-research-comparison-v2.html">Deep Research Comparison v2</a>'
                '<time class="page-link-date" datetime="2026-11-05">Updated 2026-11-05</time></li>'
                '<li><a href="ai-scientists/ai-scientist-comparison-v1.html">AI Scientist Comparison v1</a>'
                '<time class="page-link-date" datetime="2026-11-05">Updated 2026-11-05</time></li></main>')
    index.write_text(original)
    sync_index_date(tmp_path, docs / 'deep-research/deep-research-comparison-v2.html', '2026-11-06')
    page = html.fromstring(index.read_bytes())
    assert page.xpath('//time/@datetime') == ['2026-11-06', '2026-11-06', '2026-11-05']
    assert page.xpath('//time/text()') == ['Updated 2026-11-06', 'Updated 2026-11-06', 'Updated 2026-11-05']
    revised = index.read_bytes()
    sync_index_date(tmp_path, docs / 'unlisted-export.html', '2026-11-07')
    assert index.read_bytes() == revised
    with pytest.raises(ValueError):
        sync_index_date(tmp_path, docs / 'deep-research/deep-research-comparison-v2.html', '2026-02-30')
    assert index.read_bytes() == revised


def test_index_dates_remain_to_the_right_of_wrapping_titles_in_browser():
    """Reserve a right-hand date column even when a title needs several lines.

    One browser and page serve every width: launching Chromium per width
    dominated the runtime, and the layout is recomputed on each resize.
    """
    playwright = pytest.importorskip('playwright.sync_api', reason='Optional browser layout regression')
    with playwright.sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch(headless=True)
        except playwright.Error as error:
            if "Executable doesn't exist" in str(error):
                pytest.skip('Playwright Chromium is not installed')
            raise
        try:
            context = browser.new_context(viewport={'width': 1365, 'height': 900})
            context.route('http://**/*', lambda route: route.abort())
            context.route('https://**/*', lambda route: route.abort())
            page = context.new_page()
            page.goto((ROOT / 'docs/index.html').as_uri(), wait_until='load')
            page.locator('details').evaluate_all('(items) => items.forEach(item => item.open = true)')
            for width in (320, 390, 650, 1365):
                page.set_viewport_size({'width': width, 'height': 900})
                rows = page.locator('main time.page-link-date').evaluate_all('''items => items.map(date => {
                    const item = date.closest('li'), link = item.querySelector('a');
                    const description = item.querySelector('.description');
                    const d = date.getBoundingClientRect(), a = link.getBoundingClientRect();
                    const p = description.getBoundingClientRect(), row = item.getBoundingClientRect();
                    return {label:link.textContent, dateLeft:d.left, dateRight:d.right, dateTop:d.top,
                            linkRight:a.right, linkTop:a.top, linkBottom:a.bottom,
                            descriptionLeft:p.left, descriptionRight:p.right, descriptionTop:p.top,
                            rowLeft:row.left, rowRight:row.right};
                })''')
                assert len(rows) == 46, width
                for row in rows:
                    assert row['dateLeft'] >= row['linkRight'] - 1, (width, row)
                    assert abs(row['dateTop'] - row['linkTop']) <= 1, (width, row)
                    assert row['dateRight'] <= width - 15, (width, row)
                    assert row['descriptionTop'] >= row['linkBottom'] - 1, (width, row)
                    assert abs(row['descriptionLeft'] - row['rowLeft']) <= 1, (width, row)
                    assert abs(row['descriptionRight'] - row['rowRight']) <= 1, (width, row)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
        finally:
            browser.close()


def test_current_guides_link_to_existing_pages_datasets_and_prompts():
    guides = ['README.md', 'docs/deep-research/research-pipeline.html', 'docs/ai-scientists/ai-scientist-comparison-method.html',
              'crest/_archive/index.html', 'crest/_archive/reference/nus_pairwise_v1.md']
    for name in guides:
        path = ROOT / name
        text = path.read_text()
        links = (html.fromstring(text).xpath('//a/@href') if path.suffix == '.html'
                 else re.findall(r'\[[^\]]*\]\(([^)]+)\)', text))
        for link in links:
            url = urlsplit(link)
            if url.scheme or url.netloc or not url.path.endswith(('.txt', '.jsonl', '.html')):
                continue
            assert (path.parent / unquote(url.path)).is_file(), (name, link)

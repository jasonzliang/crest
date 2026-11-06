"""Publication contracts: canonical URLs, page dates, and unchanged research evidence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import unquote, urlsplit

from lxml import etree, html
import pytest

ROOT = Path(__file__).resolve().parents[1]
BASELINE = Path(__file__).with_name('docs_evidence_baseline.json')
PROTECTED = ('//table | //svg | //pre | //script | //meta | '
             '//*[contains(concat(" ", normalize-space(@class), " "), " answer-text ") or '
             'contains(concat(" ", normalize-space(@class), " "), " reason ") or '
             'contains(concat(" ", normalize-space(@class), " "), " judgment ") or '
             'contains(concat(" ", normalize-space(@class), " "), " metadata ") or '
             'contains(concat(" ", normalize-space(@class), " "), " meta ") or '
             'contains(concat(" ", normalize-space(@class), " "), " question ") or '
             'contains(concat(" ", normalize-space(@class), " "), " paper-record ")]')


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
    protected = [digest(etree.tostring(e, with_tail=False)) for e in page.xpath(PROTECTED)]
    body = deepcopy(page.find('body'))
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
    assert len(entries) == 46
    local = [a for a in entries if not urlsplit(a.get('href')).scheme]
    assert len(local) == 45
    assert 'page-update dates, not study dates' in page.text_content()
    for a in local:
        target = (ROOT / 'docs' / a.get('href')).resolve()
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
    assert [a.text_content() for a in external] == ['Project README']
    assert not external[0].getparent().xpath('.//time')


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
    assert len(baseline) == 45
    for name, expected in baseline.items():
        assert evidence_fingerprints((ROOT / name).read_bytes()) == expected, name


def test_redirects_have_readable_canonical_fallbacks():
    from crest_ais.site import PAGES
    aliases = [p for p in PAGES if p['old'] != p['canonical']]
    assert len(aliases) == 26
    for record in aliases:
        path = ROOT / record['old']
        page = html.fromstring(path.read_bytes())
        link = page.xpath('//main//a[@id="canonical-link"]')[0]
        assert link.text_content() == record['label']
        assert (path.parent / link.get('href')).resolve() == ROOT / record['canonical']
        assert path.stat().st_size < 15000
        assert page.xpath('//link[@rel="canonical"]/@href') == [link.get('href')]
        assert not page.xpath('//meta[translate(@http-equiv,"REFSH","refsh")="refresh"]')


@pytest.mark.skipif(shutil.which('node') is None, reason='Node is optional; needed to execute redirect JavaScript')
@pytest.mark.parametrize('search,fragment', [('', ''), ('?source=old%20link&x=1', '#method'),
                                             ('?next=%23method', '#answer%3Aone')])
def test_redirect_scripts_preserve_query_and_fragment(search, fragment):
    from crest_ais.site import PAGES
    for record in PAGES:
        if record['old'] == record['canonical']:
            continue
        page = html.fromstring((ROOT / record['old']).read_bytes())
        link = page.xpath('//main//a[@id="canonical-link"]')[0]
        # Execute the actual script, not a duplicated implementation of it.
        script = page.xpath('//script/text()')[-1]
        harness = ('const link = {href: null}; let result; '
                   'global.document = {getElementById: () => link}; '
                   'global.window = {location: {search: ' + json.dumps(search) + ', hash: ' + json.dumps(fragment) + ', '
                   'replace: x => {result = x}}};\n' + script +
                   '\nconsole.log(JSON.stringify({result, href: link.href}));')
        actual = json.loads(subprocess.check_output(['node', '-e', harness], text=True))
        expected = link.get('href') + search + fragment
        assert actual == {'result': expected, 'href': expected}


def test_site_navigation_and_document_links_resolve_with_fragments():
    from crest_ais.site import PAGES
    aliases = {str((ROOT / p['old']).resolve()): ROOT / p['canonical'] for p in PAGES}
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
                document = page if target == path else html.fromstring(target.read_bytes())
                fragment = unquote(url.fragment)
                assert document.xpath('//*[@id=$id or @name=$id]', id=fragment), (path, link.get('href'))


def test_generated_header_uses_canonical_links_and_reproducible_date(monkeypatch, tmp_path):
    from crest_ais.navigation import site_header
    monkeypatch.setenv('CREST_PAGE_UPDATED', '2026-11-05')
    fragment = html.fromstring(site_header(tmp_path, tmp_path / 'docs/report.html'))
    assert fragment.xpath('.//a/@href')[1:] == [
        'research-pipeline.html', 'deep-research-comparison-v2.html',
        'ai-scientist-comparison-v1.html', 'index.html']
    assert fragment.xpath('.//time/@datetime') == ['2026-11-05']
    assert html.fromstring(site_header(tmp_path, tmp_path / 'docs/report.html', updated='2026-11-06')).xpath('.//time/@datetime') == ['2026-11-06']


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
    for name in ('docs/index.html', 'docs/deep-research-comparison-v2.html', 'docs/deep-research-creativity-v2.html'):
        assert DATE_CSS in (ROOT / name).read_text()


def test_index_sync_updates_only_matching_entry_and_index_page_date(tmp_path):
    from crest_ais.site import sync_index_date
    docs = tmp_path / 'docs'; docs.mkdir()
    index = docs / 'index.html'
    original = ('<header><time class="crest-page-updated" datetime="2026-11-05">Updated 2026-11-05</time></header>'
                '<main><li><a href="deep-research-comparison-v2.html">Deep research comparison v2</a>'
                '<time class="page-link-date" datetime="2026-11-05">Updated 2026-11-05</time></li>'
                '<li><a href="ai-scientist-comparison-v1.html">AI scientist comparison v1</a>'
                '<time class="page-link-date" datetime="2026-11-05">Updated 2026-11-05</time></li></main>')
    index.write_text(original)
    sync_index_date(tmp_path, docs / 'deep-research-comparison-v2.html', '2026-11-06')
    page = html.fromstring(index.read_bytes())
    assert page.xpath('//time/@datetime') == ['2026-11-06', '2026-11-06', '2026-11-05']
    assert page.xpath('//time/text()') == ['Updated 2026-11-06', 'Updated 2026-11-06', 'Updated 2026-11-05']
    revised = index.read_bytes()
    sync_index_date(tmp_path, docs / 'unlisted-export.html', '2026-11-07')
    assert index.read_bytes() == revised
    with pytest.raises(ValueError):
        sync_index_date(tmp_path, docs / 'deep-research-comparison-v2.html', '2026-02-30')
    assert index.read_bytes() == revised


@pytest.mark.parametrize('width', [320, 390, 650, 1365])
def test_index_dates_remain_to_the_right_of_wrapping_titles_in_browser(width):
    """Reserve a right-hand date column even when a title needs several lines."""
    playwright = pytest.importorskip('playwright.sync_api', reason='Optional browser layout regression')
    with playwright.sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch(headless=True)
        except playwright.Error as error:
            if "Executable doesn't exist" in str(error):
                pytest.skip('Playwright Chromium is not installed')
            raise
        try:
            context = browser.new_context(viewport={'width': width, 'height': 900})
            context.route('http://**/*', lambda route: route.abort())
            context.route('https://**/*', lambda route: route.abort())
            page = context.new_page()
            page.goto((ROOT / 'docs/index.html').as_uri(), wait_until='load')
            page.locator('details').evaluate_all('(items) => items.forEach(item => item.open = true)')
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
            assert len(rows) == 45
            for row in rows:
                assert row['dateLeft'] >= row['linkRight'] - 1, row
                assert abs(row['dateTop'] - row['linkTop']) <= 1, row
                assert row['dateRight'] <= width - 15, row
                assert row['descriptionTop'] >= row['linkBottom'] - 1, row
                assert abs(row['descriptionLeft'] - row['rowLeft']) <= 1, row
                assert abs(row['descriptionRight'] - row['rowRight']) <= 1, row
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        finally:
            browser.close()

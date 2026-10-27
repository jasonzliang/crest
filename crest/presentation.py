"""Deterministic, local citation presentation for blinded judge inputs.

This is a presentation transform, not source verification or anonymity against
substantive prose. No URL is fetched or resolved. Raw generation text remains
the provenance record; only the judge's copy has destinations hidden.
"""

import html
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


PRESENTATION_VERSION = 'citation-neutral-v1'
_URL = re.compile(r'(?<![a-z0-9+.-])(?:[a-z][a-z0-9+.-]*://|www\.)[^\s<>"\']+', re.I)
_EXTERNAL_DESTINATION = re.compile(
    r'(?:[a-z][a-z0-9+.-]*://|(?:mailto|tel|doi|urn):|//|www\.)\S+', re.I)
_REFERENCE = re.compile(r'^[ \t]{0,3}\[([^\]\n]+)\]:[ \t]*(?:<([^>\n]+)>|(\S+))([^\n]*)', re.M)
_ANCHOR = re.compile(r'<a\b([^>]*)>(.*?)</a\s*>', re.I | re.S)
_ATTRIBUTE = re.compile(r'([\w:-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))')
_PROVIDER_LABEL = re.compile(
    r'(?:openai|chatgpt|gemini|google(?:\s+search)?|caesar|'
    r'(?:www\.)?(?:openai\.com|chatgpt\.com|gemini\.google\.com|'
    r'vertexaisearch\.cloud\.google\.com))', re.I)
_NATIVE_CITATION = re.compile(r'\ue200cite\ue202([^\ue201]+)\ue201')
_GOOGLE_CITATION = re.compile(r'\[cite:([^\]\n]+)\]', re.I)


def _closing(text: str, start: int, opening: str, closing: str) -> int | None:
    """Find a balanced Markdown delimiter, including escaped/nested delimiters."""
    depth = 0
    quote = None
    index = start
    while index < len(text):
        char = text[index]
        if char == '\\':
            index += 2
            continue
        if opening == '(' and char in '\"\'':
            if quote == char:
                quote = None
            elif quote is None and index > start and text[index - 1].isspace():
                quote = char
        if quote is None:
            if char == opening:
                depth += 1
            elif char == closing:
                depth -= 1
                if depth == 0:
                    return index
        index += 1
    return None


def _destination(value: str) -> tuple[str, str]:
    value = value.strip()
    if value.startswith('<') and '>' in value:
        end = value.index('>')
        return value[1:end], value[end + 1:].strip()
    parts = value.split(None, 1)
    return (parts[0], parts[1] if len(parts) > 1 else '') if parts else ('', '')


def _url_identity(url: str) -> str:
    """Ignore common tracking parameters only when reusing neutral labels."""
    url = html.unescape(url)
    try:
        parts = urlsplit(url)
        query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
                 if not key.lower().startswith('utm_')
                 and key.lower() not in {'gclid', 'fbclid', 'msclkid', 'referrer'}]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    except ValueError:
        return url


def present_answer(text: str) -> str:
    """Hide link destinations, preserving labels, titles, citation IDs and prose.

    Raw/automatic URLs and provider-only link labels become ``[Source N]``.
    Numbering restarts independently for each answer, in occurrence order;
    repeating a URL reuses its label. This is intentionally a local syntactic
    transform, rather than a full Markdown renderer or a semantic redactor.
    """
    if not isinstance(text, str):
        raise ValueError('answer must be text')
    sources = {}
    references = {m.group(1).casefold(): m.group(2) or m.group(3)
                  for m in _REFERENCE.finditer(text)
                  if _EXTERNAL_DESTINATION.fullmatch(m.group(2) or m.group(3))}

    def source(url):
        identity = _url_identity(url)
        if identity not in sources:
            sources[identity] = len(sources) + 1
        return f'[Source {sources[identity]}]'

    def label(value, destination):
        plain = html.unescape(re.sub(r'<[^>]*>', '', value)).strip().strip('*_` ')
        if not plain or _URL.fullmatch(plain) or _PROVIDER_LABEL.fullmatch(plain):
            return source(destination)
        return '[' + render(value) + ']'

    def citation(identifier):
        identifier = identifier.strip()
        if re.fullmatch(r'[\d,\s-]+', identifier):
            return '[' + identifier + ']'
        return source('citation:' + identifier)

    def render(text):
        output = []
        index = 0
        while index < len(text):
            # Reference definitions retain their identifiers and optional titles.
            if index == 0 or text[index - 1] == '\n':
                match = _REFERENCE.match(text, index)
                if match and _EXTERNAL_DESTINATION.fullmatch(match.group(2) or match.group(3)):
                    destination = match.group(2) or match.group(3)
                    prefix = text[index:match.start(2) - 1] if match.group(2) is not None else text[index:match.start(3)]
                    output.append(prefix + source(destination) + render(match.group(4)))
                    index = match.end()
                    continue
            if text[index] == '<':
                match = _ANCHOR.match(text, index)
                if match:
                    attrs = {m.group(1).lower(): html.unescape(next(v for v in m.groups()[1:] if v is not None))
                             for m in _ATTRIBUTE.finditer(match.group(1))}
                    rendered = label(match.group(2), attrs.get('href', ''))
                    if attrs.get('title'):
                        rendered += ' ' + '"' + render(attrs['title']) + '"'
                    output.append(rendered)
                    index = match.end()
                    continue
                match = _URL.match(text, index + 1)
                if match and match.end() < len(text) and text[match.end()] == '>':
                    output.append(source(match.group()))
                    index = match.end() + 1
                    continue
            if text[index] == '[' or text.startswith('![', index):
                start = index + (text[index] == '!')
                end = _closing(text, start, '[', ']')
                if end is not None and text.startswith('(', end + 1):
                    destination_end = _closing(text, end + 1, '(', ')')
                    if destination_end is not None:
                        destination, title = _destination(text[end + 2:destination_end])
                        # Bracket notation also occurs in mathematics, such as
                        # [p](x | y); only recognizable external links qualify.
                        if _EXTERNAL_DESTINATION.fullmatch(destination):
                            rendered = label(text[start + 1:end], destination)
                            output.append(('!' if start != index else '') + rendered + (' ' + render(title) if title else ''))
                            index = destination_end + 1
                            continue
                if end is not None and text.startswith('[', end + 1):
                    ref_end = text.find(']', end + 2)
                    if ref_end != -1:
                        ref_id = text[end + 2:ref_end] or text[start + 1:end]
                        destination = references.get(ref_id.casefold())
                        if destination is not None:
                            rendered = label(text[start + 1:end], destination)
                            output.append(rendered + text[end + 1:ref_end + 1])
                            index = ref_end + 1
                            continue
            match = _NATIVE_CITATION.match(text, index)
            if match:
                output.append(', '.join(citation(identifier)
                                        for identifier in match.group(1).split('\ue202')))
                index = match.end()
                continue
            match = _GOOGLE_CITATION.match(text, index)
            if match:
                output.append(citation(match.group(1)))
                index = match.end()
                continue
            match = _URL.match(text, index)
            if match:
                url = match.group().rstrip('.,;:!?')
                while url and url[-1] in ')]}' and url.count(url[-1]) > url.count({')': '(', ']': '[', '}': '{'}[url[-1]]):
                    url = url[:-1]
                output.append(source(url))
                index += len(url)
                continue
            output.append(text[index])
            index += 1
        return ''.join(output)

    return render(text)

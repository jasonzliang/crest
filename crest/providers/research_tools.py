"""Bounded client-side research tools; never pass a provider's API client here.

``await execute_tool("web_search", {"query": "...", "max_results": 5})``
``await execute_tool("web_fetch", {"url": "https://..."})`` (alias: ``fetch_url``)

Results contain identical ``text``/``content`` strings, ``citations`` with URL and
title, and boolean ``error`` / ``is_error`` flags. Failures have no citations;
the safe, user-facing diagnostic is in ``text`` / ``content``.
Search lazily requires the optional ``ddgs`` package. DDGS public web search is
DuckDuckGo-compatible, but ``backend="auto"`` may use multiple public engines;
results are not guaranteed to come from DuckDuckGo. No paid search API is used.
``client`` is an optional offline-test HTTPX client, not a model API client.
"""
from __future__ import annotations

import asyncio
from html.parser import HTMLParser
import ipaddress
from itertools import islice
import socket
from urllib.parse import urljoin, urlsplit

import httpx

MAX_RESULTS = 5
MAX_QUERY_CHARS = 2000
MAX_URL_CHARS = 2048
MAX_TEXT_CHARS = 16000
MAX_RESPONSE_BYTES = 256 * 1024
MAX_REDIRECTS = 3
SEARCH_TIMEOUT = 15
FETCH_TIMEOUT = 20
DNS_TIMEOUT = 5
HTTP_TIMEOUT = 10
_REDIRECTS = {301, 302, 303, 307, 308}
_TEXT_TYPES = {"text/html", "application/xhtml+xml", "text/plain", "text/markdown"}
_TRUNCATED = "\n[truncated]"


class ToolError(ValueError):
    """A safe, model-facing explanation of a rejected or failed tool call."""


def _result(text, citations=(), *, error=False, truncated=False):
    if truncated or len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS - len(_TRUNCATED)].rstrip() + _TRUNCATED
    return {"text": text, "content": text, "citations": list(citations), "error": error, "is_error": error}


def _arguments(name, arguments):
    if name not in ("web_search", "web_fetch", "fetch_url"):
        raise ToolError("Unknown tool; expected web_search or web_fetch.")
    if not isinstance(arguments, dict):
        raise ToolError("Invalid arguments: expected an object.")
    field = "query" if name == "web_search" else "url"
    allowed = {"query", "max_results"} if name == "web_search" else {"url"}
    value = arguments.get(field)
    maximum = MAX_QUERY_CHARS if field == "query" else MAX_URL_CHARS
    if set(arguments) - allowed or not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ToolError(f"Invalid arguments: supply {field} as a nonempty string (maximum {maximum} characters).")
    count = arguments.get("max_results", MAX_RESULTS)
    if type(count) is not int or count < 1:
        raise ToolError("Invalid arguments: max_results must be a positive integer.")
    return value, min(count, MAX_RESULTS)


def _public_ip(value):
    address = ipaddress.ip_address(value)
    if not address.is_global or address.is_multicast or address.is_reserved:
        return False
    if address.version == 6:
        # Do not permit transition mechanisms to tunnel to an embedded private IPv4.
        if address.is_site_local or address.ipv4_mapped or address.sixtofour or address.teredo:
            return False
        if address in ipaddress.ip_network("64:ff9b::/96"):
            return False
    return True


def _url(value):
    """Validate syntax before DNS; reject parser ambiguities and local names."""
    try:
        if not isinstance(value, str) or not value or len(value) > MAX_URL_CHARS:
            raise ValueError
        if "\\" in value or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or "@" in parsed.netloc:
            raise ValueError
        if "%" in parsed.hostname or parsed.netloc.endswith(":"):
            raise ValueError
        if parsed.port not in (None, 443 if parsed.scheme == "https" else 80):
            raise ValueError
        url = httpx.URL(value)
        host = url.raw_host.decode("ascii").lower().rstrip(".")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            # inet_aton accepts shorthand, octal, hex and integer IPv4; never use those.
            try:
                socket.inet_aton(host)
            except OSError:
                pass
            else:
                raise ValueError("Ambiguous IP address")
            if "." not in host or host.endswith((".localhost", ".local", ".internal", ".localdomain", ".lan", ".home")):
                raise ValueError
            if any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
                   or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in label)
                   for label in host.split(".")):
                raise ValueError
        else:
            if not _public_ip(host):
                raise ValueError
        url = url.copy_with(host=host, fragment=None)
        if len(str(url)) > MAX_URL_CHARS:
            raise ValueError
        return url
    except (ValueError, httpx.InvalidURL, UnicodeError) as exc:
        raise ToolError("Unsafe or invalid URL: use public HTTP(S), no userinfo, and only the scheme's default port.") from exc


async def _destination(url):
    """Validate every DNS answer and pin the connection to one of those addresses."""
    host = url.raw_host.decode("ascii")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        try:
            answers = await asyncio.wait_for(asyncio.to_thread(
                socket.getaddrinfo, host, url.port or (443 if url.scheme == "https" else 80),
                type=socket.SOCK_STREAM), DNS_TIMEOUT)
        except TimeoutError:
            raise
        except OSError as exc:
            raise ToolError("DNS resolution failed for the fetch destination.") from exc
        addresses = [answer[4][0] for answer in answers]
    else:
        addresses = [host]
    if not addresses or any(not _public_ip(address) for address in addresses):
        raise ToolError("Unsafe destination: every resolved address must be a public IP.")
    return url.copy_with(host=addresses[0])


def _clean(value, limit):
    return " ".join(value[:limit].split()) if isinstance(value, str) else ""


def _search_sync(query, count):
    try:
        from ddgs import DDGS
    except ImportError as exc:
        raise ToolError("Search requires the optional ddgs package; install ddgs to enable DDGS public web search.") from exc
    try:
        rows = DDGS(timeout=SEARCH_TIMEOUT).text(query, max_results=count, backend="auto")
        return list(islice(rows, count))
    except TimeoutError:
        raise
    except Exception as exc:
        # Backend errors may contain proxy credentials; never echo their raw message.
        raise ToolError("DDGS public web search failed; no sources were returned.") from exc


async def _search(query, count):
    # The outer deadline bounds the await; cancellation cannot kill a running thread.
    # DDGS also receives a finite network timeout, and iteration is capped in that thread.
    rows = await asyncio.wait_for(asyncio.to_thread(_search_sync, query.strip(), count), SEARCH_TIMEOUT)
    citations, parts, seen = [], [], set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            url = str(_url(row.get("href") or row.get("url") or row.get("link")))
        except ToolError:
            continue
        if url in seen:
            continue
        seen.add(url)
        title = _clean(row.get("title"), 256) or url[:256]
        snippet = (_clean(row.get("body"), 512) or _clean(row.get("snippet"), 512)
                   or _clean(row.get("description"), 512))
        citations.append({"url": url, "title": title})
        parts.append(f"{title}\n{url}\n{snippet}")
    if not citations:
        raise ToolError("DDGS public web search returned no usable sources.")
    return _result("\n\n".join(parts), citations)


class _PageText(HTMLParser):
    """Small text extractor: no scripts, styles, hidden templates, or subrequests."""
    _HIDDEN = {"script", "style", "noscript", "template", "svg"}
    # HTML lets pages omit </head>; any other start tag implicitly opens the body.
    _HEAD = {"head", "title", "meta", "link", "base", "style", "script", "noscript", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.title, self.hidden = [], [], []
        self.in_title = False
        self.in_head = False

    def handle_starttag(self, tag, attrs):
        if tag in self._HIDDEN:
            self.hidden.append(tag)
        if tag == "title":
            self.in_title = True
        if tag == "head":
            self.in_head = True
        elif tag not in self._HEAD:
            self.in_head = False

    def handle_endtag(self, tag):
        if self.hidden and tag == self.hidden[-1]:
            self.hidden.pop()
        if tag == "title":
            self.in_title = False
        if tag == "head":
            self.in_head = False

    def handle_data(self, data):
        if self.hidden:
            return
        if self.in_title:
            self.title.append(data)
        elif not self.in_head:
            self.parts.append(data)


async def _page(response, url):
    media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type not in _TEXT_TYPES:
        raise ToolError("Unsupported content type: only HTML, plain text and Markdown pages are supported.")
    # Request identity and reject servers ignoring it, avoiding decompression bombs.
    if response.headers.get("content-encoding", "identity").strip().lower() != "identity":
        raise ToolError("Unsupported content encoding: the server must return uncompressed text.")
    body, truncated = bytearray(), False
    async for chunk in response.aiter_bytes(chunk_size=8192):
        remaining = MAX_RESPONSE_BYTES - len(body)
        body.extend(chunk[:remaining])
        if len(chunk) > remaining:
            truncated = True
            break
    try:
        text = body.decode(response.encoding or "utf-8", errors="replace")
    except LookupError:
        text = body.decode("utf-8", errors="replace")
    title = str(url)[:256]
    if media_type in ("text/html", "application/xhtml+xml"):
        parser = _PageText()
        parser.feed(text)
        parser.close()
        title = _clean(" ".join(parser.title), 256) or title
        text = " ".join(" ".join(parser.parts).split())
    if not text.strip():
        raise ToolError("The page returned no usable text; no source was recorded.")
    return _result(f"{title}\n{url}\n\n{text.strip()}", [{"url": str(url), "title": title}], truncated=truncated)


async def _fetch(value, client):
    url = _url(value)
    for hop in range(MAX_REDIRECTS + 1):
        pinned = await _destination(url)
        # Standalone Request deliberately bypasses client headers, cookies and params.
        # Host/SNI retain the original identity while TCP uses a checked IP. Close
        # each hop so hosts sharing an IP cannot reuse another host's TLS session.
        request = httpx.Request("GET", pinned, headers={
            "Host": url.netloc.decode("ascii"), "User-Agent": "crest-research/0.2", "Connection": "close",
            "Accept": "text/html, application/xhtml+xml, text/plain, text/markdown", "Accept-Encoding": "identity",
        }, extensions={"sni_hostname": url.raw_host.decode("ascii"), "timeout": httpx.Timeout(HTTP_TIMEOUT).as_dict()})
        response = await client.send(request, stream=True, auth=None, follow_redirects=False)
        try:
            if response.status_code in _REDIRECTS:
                target = response.headers.get("location")
                if not target or hop == MAX_REDIRECTS:
                    raise ToolError("Fetch redirect failed: missing Location or redirect limit exceeded.")
                try:
                    url = _url(urljoin(str(url), target))
                except ValueError as exc:
                    raise ToolError("Unsafe or invalid redirect URL.") from exc
                continue
            if not 200 <= response.status_code < 300:
                raise ToolError(f"Fetch failed with HTTP {response.status_code}; no source was recorded.")
            return await _page(response, url)
        finally:
            await response.aclose()


async def execute_tool(name: str, arguments: dict, *, client=None) -> dict:
    """Run web_search(query, max_results?) or web_fetch(url), returning tool_result data.

    Limits: 5 search results, 3 redirects, 256 KiB retained page bytes, 16,000 output
    characters, 15-second search / 20-second fetch / 5-second DNS deadlines.
    Default fetches use an isolated client with environment proxies disabled;
    injected clients are for offline tests only. No model credentials are read.
    Cancellation propagates; operational errors return error=is_error=True and no sources.
    """
    try:
        value, count = _arguments(name, arguments)
        if name == "web_search":
            return await _search(value, count)
        async with asyncio.timeout(FETCH_TIMEOUT):
            if client is not None:
                return await _fetch(value, client)
            async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=HTTP_TIMEOUT) as clean:
                return await _fetch(value, clean)
    except ToolError as exc:
        return _result(str(exc), error=True)
    except (TimeoutError, httpx.TimeoutException):
        return _result("Research tool timed out; no source was recorded.", error=True)
    except httpx.HTTPError:
        return _result("HTTP fetch failed; no source was recorded.", error=True)

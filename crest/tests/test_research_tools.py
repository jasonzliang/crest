"""Offline contracts for bounded, credential-free client-side research tools."""
import asyncio
import builtins
import socket
import sys
import threading
from types import SimpleNamespace

import httpx

import pytest

from crest.providers import research_tools


def test_unknown_tool_is_an_explicit_error_without_sources():
    result = asyncio.run(research_tools.execute_tool("shell", {"command": "whoami"}))
    assert result["is_error"] is True
    assert "unknown tool" in result["text"].lower()
    assert result["content"] == result["text"]
    assert result["citations"] == []
    assert result["error"]


@pytest.mark.parametrize("name, arguments", [
    ("web_search", None), ("web_search", []), ("web_search", {}),
    ("web_search", {"query": " "}), ("web_search", {"query": 123}),
    ("web_search", {"query": "x" * 2001}),
    ("web_search", {"query": "Q", "max_results": 0}),
    ("web_search", {"query": "Q", "max_results": True}),
    ("web_search", {"query": "Q", "max_results": "5"}),
    ("web_search", {"query": "Q", "api_key": "must not forward"}),
    ("web_fetch", {}), ("web_fetch", {"url": 123}),
    ("web_fetch", {"url": "https://example.test/", "headers": {"x-api-key": "secret"}}),
])
def test_invalid_arguments_are_errors(name, arguments):
    result = asyncio.run(research_tools.execute_tool(name, arguments))
    assert result["is_error"] is True
    assert "argument" in result["text"].lower()
    assert result["citations"] == []


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def resolve(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    async def no_network(*args, **kwargs):
        pytest.fail("Tests must never open a real HTTP connection")

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", no_network)
    # Only search tests providing a fake DDGS may use this optional dependency.
    monkeypatch.setitem(sys.modules, "ddgs", None)


def install_search(monkeypatch, rows):
    calls = []
    main_thread = threading.get_ident()

    class Search:
        def __init__(self, **kwargs):
            assert threading.get_ident() != main_thread
            assert 0 < kwargs["timeout"] <= 20

        def text(self, query, **kwargs):
            calls.append((query, kwargs))
            if isinstance(rows, Exception):
                raise rows
            return rows

    monkeypatch.setitem(sys.modules, "ddgs", SimpleNamespace(DDGS=Search))
    return calls


def fetch(handler, url="https://example.test/page", *, name="web_fetch", **client_options):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), **client_options) as client:
            return await research_tools.execute_tool(name, {"url": url}, client=client)
    return asyncio.run(run())


def assert_error(result, phrase):
    assert result["is_error"] is True
    assert result["error"] is True
    assert phrase.lower() in result["text"].lower()
    assert result["text"] == result["content"]
    assert result["citations"] == []


def test_search_uses_explicit_auto_backend_is_capped_and_runs_off_the_event_loop(monkeypatch):
    def rows():
        for index in range(5):
            yield {"title": "T" * 1000, "href": f"https://example.test/{index}", "body": "B" * 50000}
        pytest.fail("Search must not consume more than five rows")

    calls = install_search(monkeypatch, rows())
    result = asyncio.run(research_tools.execute_tool("web_search", {"query": " research ", "max_results": 1000}))
    assert result["is_error"] is False
    assert calls == [("research", {"max_results": 5, "backend": "auto"})]
    assert len(result["citations"]) == 5
    assert len(result["text"]) <= 16000
    for index, citation in enumerate(result["citations"]):
        assert citation["url"] == f"https://example.test/{index}"
        assert 0 < len(citation["title"]) <= 256
        assert citation["url"] in result["text"]
    assert result["content"] == result["text"]


def test_search_honors_smaller_requested_count(monkeypatch):
    rows = [{"href": f"https://example.test/{i}", "title": f"Paper {i}", "body": "Finding"} for i in range(10)]
    calls = install_search(monkeypatch, rows)
    result = asyncio.run(research_tools.execute_tool("web_search", {"query": "Q", "max_results": 2}))
    assert calls[0][1]["max_results"] == 2
    assert len(result["citations"]) == 2
    assert "Paper 0" in result["text"] and "Finding" in result["text"]


def test_search_filters_invalid_and_duplicate_sources(monkeypatch):
    install_search(monkeypatch, [
        {"href": "javascript:alert(1)", "title": "Fake"},
        {"href": "https://example.test/paper", "title": "Paper", "body": "Finding"},
        {"href": "https://example.test/paper", "title": "Duplicate"},
        {"href": "http://127.0.0.1/", "title": "Private"}, None,
    ])
    result = asyncio.run(research_tools.execute_tool("web_search", {"query": "Q"}))
    assert result["citations"] == [{"url": "https://example.test/paper", "title": "Paper"}]
    assert "Fake" not in result["text"] and "Duplicate" not in result["text"]


@pytest.mark.parametrize("rows", [[], [None, {}, {"title": "No URL"}, {"href": "file:///etc/passwd"}]])
def test_search_without_usable_sources_is_not_a_success(monkeypatch, rows):
    install_search(monkeypatch, rows)
    assert_error(asyncio.run(research_tools.execute_tool("web_search", {"query": "Q"})), "no usable")


def test_missing_optional_search_dependency_is_actionable():
    assert_error(asyncio.run(research_tools.execute_tool("web_search", {"query": "Q"})), "ddgs")


def test_search_backend_failure_is_explicit_and_does_not_echo_secrets(monkeypatch):
    install_search(monkeypatch, RuntimeError("Authorization: SECRET"))
    result = asyncio.run(research_tools.execute_tool("web_search", {"query": "Q"}))
    assert_error(result, "search failed")
    assert "SECRET" not in result["text"]


def test_search_timeout_is_bounded(monkeypatch):
    async def stalled_thread(*args, **kwargs):
        await asyncio.sleep(60)

    monkeypatch.setattr(research_tools, "SEARCH_TIMEOUT", .01)
    monkeypatch.setattr(asyncio, "to_thread", stalled_thread)
    assert_error(asyncio.run(research_tools.execute_tool("web_search", {"query": "Q"})), "timed out")


def test_html_fetch_extracts_title_and_visible_text_without_ddgs():
    def handler(request):
        assert request.url.host == "93.184.216.34"  # DNS is pinned, not resolved again by HTTPX.
        assert request.headers["host"] == "example.test"
        assert request.extensions["sni_hostname"] == "example.test"
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text="""
            <html><head><title>Paper &amp; evidence</title><style>HIDDEN_STYLE</style></head>
            <body><h1>Actual finding</h1><p>Alpha &amp; beta.</p>
            <script>SECRET_SCRIPT</script><noscript>NO_SCRIPT</noscript>
            <template>HIDDEN_TEMPLATE</template><svg><text>SVG_DATA</text></svg></body></html>
        """)

    result = fetch(handler)
    assert result["is_error"] is False
    assert result["citations"] == [{"url": "https://example.test/page", "title": "Paper & evidence"}]
    assert "Actual finding" in result["text"] and "Alpha & beta." in result["text"]
    for hidden in ("HIDDEN_STYLE", "SECRET_SCRIPT", "NO_SCRIPT", "HIDDEN_TEMPLATE", "SVG_DATA"):
        assert hidden not in result["text"]


@pytest.mark.parametrize("name", ["web_fetch", "fetch_url"])
def test_text_fetch_and_alias(name):
    result = fetch(lambda request: httpx.Response(200, text="Plain evidence", headers={"content-type": "text/plain"}), name=name)
    assert result["is_error"] is False
    assert "Plain evidence" in result["text"]
    assert result["citations"][0]["url"] == "https://example.test/page"


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "ftp://example.test/a", "data:text/plain,secret", "//example.test/a",
    "https://user:pass@example.test/", "https://user@example.test/", "https://@example.test/",
    "http://localhost/", "http://LOCALHOST./", "http://a.localhost/", "http://host.local/",
    "http://metadata.internal/", "http://intranet/", "http://127.0.0.1/", "http://127.1/",
    "http://2130706433/", "http://0177.0.0.1/", "http://0x7f000001/", "http://0.0.0.0/",
    "http://10.0.0.1/", "http://172.16.0.1/", "http://192.168.1.1/", "http://169.254.169.254/",
    "http://100.64.0.1/", "http://224.0.0.1/", "http://255.255.255.255/",
    "http://[::1]/", "http://[::]/", "http://[fc00::1]/", "http://[fe80::1]/", "http://[fec0::1]/",
    "http://[::ffff:127.0.0.1]/", "http://[ff02::1]/", "http://[fe80::1%25en0]/",
    "http://[64:ff9b::7f00:1]/", "http://[2002:7f00:1::]/",
    "https://example.test:8080/", "http://example.test:443/", "https://example.test:80/",
    "https://example.test:bad/", "https://example.test:99999/", "https://example.test:/",
    "https://example.test\\@127.0.0.1/", "https://example.test/\r\nHeader: secret",
    " https://example.test/", "https://%6cocalhost/", "https://[bad-ip]/",
])
def test_unsafe_urls_never_make_an_http_request(url):
    def forbidden(request):
        pytest.fail(f"Unsafe URL reached the transport: {url}")
    assert_error(fetch(forbidden, url), "url")


@pytest.mark.parametrize("addresses", [
    ["127.0.0.1"], ["10.0.0.9"], ["169.254.169.254"], ["::1"], ["fe80::2"],
    ["93.184.216.34", "192.168.1.9"], ["fec0::1"], [],
])
def test_every_dns_answer_must_be_public(monkeypatch, addresses):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [
        (socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in addresses
    ])
    assert_error(fetch(lambda request: pytest.fail("Unsafe DNS reached transport")), "destination")


def test_dns_failure_is_explicit(monkeypatch):
    def failed(*args, **kwargs):
        raise socket.gaierror("SECRET resolver info")
    monkeypatch.setattr(socket, "getaddrinfo", failed)
    result = fetch(lambda request: pytest.fail("Unresolved host reached transport"))
    assert_error(result, "dns")
    assert "SECRET" not in result["text"]


def test_dns_timeout_is_bounded(monkeypatch):
    async def stalled_thread(*args, **kwargs):
        await asyncio.sleep(60)
    monkeypatch.setattr(research_tools, "DNS_TIMEOUT", .01)
    monkeypatch.setattr(asyncio, "to_thread", stalled_thread)
    assert_error(fetch(lambda request: pytest.fail("Unresolved host reached transport")), "timed out")


def test_public_ipv6_literal_is_supported():
    result = fetch(lambda request: httpx.Response(200, text="IPv6 evidence"), "https://[2606:4700:4700::1111]/")
    assert result["is_error"] is False


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_relative_redirect_uses_original_host_and_cites_final_url(status):
    requests = []
    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(status, headers={"location": "/final"})
        assert request.url.path == "/final"
        assert request.headers["host"] == "example.test"
        return httpx.Response(200, text="Final evidence")
    result = fetch(handler)
    assert len(requests) == 2
    assert result["citations"][0]["url"] == "https://example.test/final"


@pytest.mark.parametrize("target", [
    "http://127.0.0.1/secrets", "http://169.254.169.254/latest/meta-data/", "//localhost/admin",
    "http://[::1]/", "file:///etc/passwd", "https://user:secret@example.test/", "https://example.test:8080/",
])
def test_redirect_to_unsafe_destination_is_not_followed(target):
    requests = []
    def handler(request):
        requests.append(request)
        assert len(requests) == 1
        return httpx.Response(302, headers={"location": target})
    assert_error(fetch(handler), "url")
    assert len(requests) == 1


def test_redirect_dns_is_validated_again(monkeypatch):
    hosts = []
    def resolve(host, port, *args, **kwargs):
        hosts.append(host)
        ip = "93.184.216.34" if len(hosts) == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "https://other.test/private"})
    assert_error(fetch(handler), "destination")
    assert hosts == ["example.test", "other.test"]
    assert len(requests) == 1


def test_redirect_loop_is_bounded():
    requests = []
    def handler(request):
        requests.append(request)
        assert len(requests) <= 4
        return httpx.Response(302, headers={"location": "/again"})
    assert_error(fetch(handler), "redirect")
    assert len(requests) <= 4


def test_redirect_without_location_is_an_error():
    assert_error(fetch(lambda request: httpx.Response(302)), "redirect")


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_http_failure_never_produces_a_source(status):
    assert_error(fetch(lambda request: httpx.Response(status, text="Not evidence")), f"HTTP {status}")


@pytest.mark.parametrize("content_type", ["application/pdf", "image/png", "application/json", "text/event-stream", ""])
def test_unsupported_content_types_are_explicit(content_type):
    assert_error(fetch(lambda request: httpx.Response(200, content=b"not a page", headers={"content-type": content_type})), "content type")


def test_http_timeout_is_an_explicit_tool_error():
    def timeout(request):
        raise httpx.ReadTimeout("SECRET", request=request)
    result = fetch(timeout)
    assert_error(result, "timed out")
    assert "SECRET" not in result["text"]


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.read_bytes = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.read_bytes += len(chunk)
            yield chunk

    async def aclose(self):
        self.closed = True


def test_large_response_stops_reading_and_bounds_tool_text():
    stream = Chunks([b"evidence " * 910] * 100)
    result = fetch(lambda request: httpx.Response(200, stream=stream, headers={"content-type": "text/plain"}))
    assert result["is_error"] is False
    assert len(result["text"]) <= 16000
    assert "truncated" in result["text"].lower()
    assert stream.read_bytes <= research_tools.MAX_RESPONSE_BYTES + 16384
    assert stream.closed


def test_compressed_responses_are_rejected_without_decompression():
    stream = Chunks([b"not even valid gzip"])
    result = fetch(lambda request: httpx.Response(200, stream=stream, headers={
        "content-type": "text/html", "content-encoding": "gzip"}))
    assert_error(result, "encoding")
    assert stream.read_bytes == 0 and stream.closed


def test_entire_fetch_has_a_deadline_even_for_a_trickling_body(monkeypatch):
    class Slow(Chunks):
        async def __aiter__(self):
            while True:
                yield b"data"
                await asyncio.sleep(.005)
    monkeypatch.setattr(research_tools, "FETCH_TIMEOUT", .02)
    stream = Slow([])
    assert_error(fetch(lambda request: httpx.Response(200, stream=stream, headers={"content-type": "text/plain"})), "timed out")
    assert stream.closed


@pytest.mark.parametrize("body, content_type", [
    ("   ", "text/plain"), ("<title>Not evidence</title><script>hidden</script>", "text/html"),
])
def test_empty_pages_do_not_become_sources(body, content_type):
    assert_error(fetch(lambda request: httpx.Response(200, text=body, headers={"content-type": content_type})), "no usable")


def test_injected_client_auth_cookies_headers_and_params_are_not_inherited():
    requests = []
    def handler(request):
        requests.append(request)
        for header in ("authorization", "proxy-authorization", "x-api-key", "cookie", "anthropic-version"):
            assert header not in request.headers
        assert not request.url.query
        assert request.headers["accept-encoding"] == "identity"
        if len(requests) == 1:
            return httpx.Response(302, headers={"location": "/final", "set-cookie": "session=SECRET"})
        return httpx.Response(200, text="Public evidence")
    result = fetch(handler, auth=("user", "secret"), headers={"x-api-key": "SECRET", "anthropic-version": "secret"},
                   cookies={"session": "SECRET"}, params={"api_key": "SECRET"}, follow_redirects=True)
    assert result["is_error"] is False
    assert len(requests) == 2


def test_default_fetch_creates_a_clean_client_ignoring_environment(monkeypatch):
    real_client = httpx.AsyncClient
    created = []
    def clean_client(**kwargs):
        created.append(kwargs)
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return real_client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text="Evidence")), **kwargs)
    monkeypatch.setenv("HTTP_PROXY", "http://user:secret@127.0.0.1:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://user:secret@127.0.0.1:8080")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "SECRET")
    monkeypatch.setattr(httpx, "AsyncClient", clean_client)
    result = asyncio.run(research_tools.execute_tool("web_fetch", {"url": "https://example.test/"}))
    assert result["is_error"] is False
    assert len(created) == 1


def test_fetch_does_not_import_the_optional_search_package(monkeypatch):
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name == "ddgs":
            pytest.fail("Fetching must not import ddgs")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)
    assert fetch(lambda request: httpx.Response(200, text="Evidence"))["is_error"] is False


def test_caller_cancellation_is_not_swallowed():
    async def cancelled(request):
        raise asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        fetch(cancelled)


def test_normalized_url_length_is_bounded_before_fetch():
    url = "https://example.test/" + "é" * 600
    assert len(url) < 2048
    assert_error(fetch(lambda request: pytest.fail("Oversized encoded URL reached transport"), url), "url")


def test_search_rejects_a_source_whose_normalized_url_exceeds_the_limit(monkeypatch):
    install_search(monkeypatch, [{"href": "https://example.test/" + "é" * 600, "title": "Oversized"}])
    assert_error(asyncio.run(research_tools.execute_tool("web_search", {"query": "Q"})), "no usable")


@pytest.mark.parametrize("target", ["http://[broken/", "https://[::1", "\t/hidden", "/page\n"])
def test_malformed_redirect_is_an_explicit_error(target):
    requests = []
    def handler(request):
        requests.append(request)
        assert len(requests) == 1
        return httpx.Response(302, headers={"location": target})
    # HTTPX may reject a malformed Location while constructing next_request,
    # even with automatic redirects disabled; either path must report an error.
    assert_error(fetch(handler), "")


def test_http_transport_failure_does_not_echo_credentials():
    def failed(request):
        raise httpx.ConnectError("proxy user:SECRET", request=request)
    result = fetch(failed)
    assert_error(result, "http fetch failed")
    assert "SECRET" not in result["text"]


def test_cross_host_redirect_preserves_the_new_host_and_sni():
    hosts = []
    def handler(request):
        hosts.append(request.headers["host"])
        if len(hosts) == 1:
            return httpx.Response(302, headers={"location": "https://other.test/paper"})
        assert request.url.host == "93.184.216.34"
        assert request.extensions["sni_hostname"] == "other.test"
        return httpx.Response(200, text="Evidence")
    result = fetch(handler)
    assert hosts == ["example.test", "other.test"]
    assert result["citations"][0]["url"] == "https://other.test/paper"


def test_actual_search_worker_timeout_returns_before_the_worker_finishes(monkeypatch):
    release = threading.Event()
    entered = threading.Event()
    class Search:
        def __init__(self, **kwargs):
            pass
        def text(self, *args, **kwargs):
            entered.set()
            release.wait(2)
            return []
    monkeypatch.setitem(sys.modules, "ddgs", SimpleNamespace(DDGS=Search))
    monkeypatch.setattr(research_tools, "SEARCH_TIMEOUT", .05)
    async def run():
        try:
            result = await asyncio.wait_for(research_tools.execute_tool("web_search", {"query": "Q"}), .5)
            assert entered.is_set() and not release.is_set()
            assert_error(result, "timed out")
        finally:
            release.set()
    asyncio.run(run())


def test_error_flags_are_boolean_and_messages_are_in_text():
    failed = asyncio.run(research_tools.execute_tool("unknown", {}))
    assert failed["error"] is True and failed["is_error"] is True
    assert failed["text"] == failed["content"] and failed["text"]
    succeeded = fetch(lambda request: httpx.Response(200, text="Public evidence"))
    assert succeeded["error"] is False and succeeded["is_error"] is False


def test_pinned_requests_do_not_reuse_tls_connections_across_original_hosts():
    def handler(request):
        assert request.headers["connection"] == "close"
        return httpx.Response(200, text="Evidence")
    assert fetch(handler)["is_error"] is False


@pytest.mark.parametrize("url_field", ["href", "url", "link"])
@pytest.mark.parametrize("snippet_field", ["body", "snippet", "description"])
def test_search_accepts_compatible_result_field_names_and_bounds_snippets(monkeypatch, url_field, snippet_field):
    install_search(monkeypatch, [{
        url_field: "https://example.test/paper", "title": "Paper",
        snippet_field: "Actual finding. " + "x" * 20000,
    }])
    result = asyncio.run(research_tools.execute_tool("web_search", {"query": "Q"}))
    assert result["error"] is False
    assert result["citations"] == [{"url": "https://example.test/paper", "title": "Paper"}]
    assert "Actual finding." in result["text"]
    assert len(result["text"]) < 900  # One bounded snippet, not the entire backend field.


def test_search_falls_back_past_empty_or_nontext_snippets(monkeypatch):
    install_search(monkeypatch, [{
        "href": "", "url": None, "link": "https://example.test/paper", "title": "Paper",
        "body": {"not": "text"}, "snippet": "   ", "description": "Actual finding.",
    }])
    result = asyncio.run(research_tools.execute_tool("web_search", {"query": "Q"}))
    assert result["error"] is False
    assert "Actual finding." in result["text"]
    assert result["citations"] == [{"url": "https://example.test/paper", "title": "Paper"}]


def test_search_link_alias_cannot_bypass_source_url_validation(monkeypatch):
    install_search(monkeypatch, [{"link": "http://127.0.0.1/secrets", "description": "Not public evidence"}])
    assert_error(asyncio.run(research_tools.execute_tool("web_search", {"query": "Q"})), "no usable")

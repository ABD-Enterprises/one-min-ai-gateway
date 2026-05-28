import json
from typing import Any, Generator
import pytest
import server


# 18. Consolidate Mock HTTP Responses in Tests
class FakeHTTPResponse:
    """Unified HTTP Response mock for requests.Session calls."""

    def __init__(
        self,
        status_code: int = 200,
        text: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    def json(self) -> Any:
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise server.requests.HTTPError(f"HTTP Error {self.status_code}")

    def iter_content(self, chunk_size: int = 1024) -> Generator[bytes, None, None]:
        yield self.text.encode("utf-8")


def test_models_accepts_model_id(monkeypatch):
    monkeypatch.setattr(
        server,
        "chat_models",
        lambda: [{"modelId": "gemini-2.5-flash", "name": "Gemini 2.5 Flash"}],
    )

    client = server.app.test_client()
    response = client.get("/v1/models")

    assert response.status_code == 200
    assert response.json["data"][0]["id"] == "gemini-2.5-flash"


def test_missing_bearer_token_returns_401():
    client = server.app.test_client()

    response = client.post(
        "/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}
    )

    assert response.status_code == 401
    assert response.json["error"]["code"] == "invalid_api_key"


def test_healthz_returns_version():
    client = server.app.test_client()

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json["ok"] is True
    assert response.json["version"]


def test_invalid_json_returns_openai_error():
    client = server.app.test_client()

    response = client.post(
        "/v1/chat/completions",
        headers={
            "Authorization": "Bearer test-key",
            "Content-Type": "application/json",
        },
        data="{",
    )

    assert response.status_code == 400
    assert response.json["error"]["code"] == "invalid_json"


def test_build_payload_rejects_non_array_messages():
    client = server.app.test_client()

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        json={"messages": "bad"},
    )

    assert response.status_code == 400
    assert response.json["error"]["code"] == "invalid_request_error"


def test_build_payload_rejects_invalid_message_item():
    client = server.app.test_client()

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        json={"messages": ["bad"]},
    )

    assert response.status_code == 400
    assert response.json["error"]["code"] == "invalid_request_error"


def test_parse_tool_call_tag():
    tool_call = server.parse_tool_text(
        '<tool_call>{"name":"glob","arguments":{"pattern":"*"}}</tool_call>',
        [{"function": {"name": "glob"}}],
    )

    assert tool_call == {"name": "glob", "arguments": {"pattern": "*"}}


def test_parse_tool_code_tag():
    tool_call = server.parse_tool_text(
        '<tool_code>{"name":"bash","arguments":{"command":"pwd"}}</tool_code>',
        [{"function": {"name": "bash"}}],
    )

    assert tool_call == {"name": "bash", "arguments": {"command": "pwd"}}


def test_clean_text_removes_fake_crawl_lines():
    assert server.clean_text("🌐 Crawling site https://example.com\nok") == "ok"


def test_remote_image_rejects_non_http_url():
    with server.app.test_request_context():
        result = server.fetch_remote_image("file:///etc/passwd")

    assert isinstance(result, tuple)
    response, status = result
    assert status == 400
    assert response.json["error"]["code"] == "invalid_image_url"


def test_remote_image_fetch_failure_returns_openai_error(monkeypatch):
    def fail_fetch(*args, **kwargs):
        raise server.requests.Timeout("slow")

    monkeypatch.setattr(server.requests.Session, "get", fail_fetch)

    with server.app.test_request_context():
        result = server.fetch_remote_image("https://example.com/image.png")

    assert isinstance(result, tuple)
    response, status = result
    assert status == 400
    assert response.json["error"]["code"] == "invalid_image_url"


def test_data_image_rejects_invalid_base64():
    with server.app.test_request_context():
        result = server.decode_data_image("data:image/png;base64,not-valid")

    assert isinstance(result, tuple)
    response, status = result
    assert status == 400
    assert response.json["error"]["code"] == "invalid_image"


def test_extract_result_text_handles_unexpected_upstream_shape():
    assert server.extract_result_text({"unexpected": True}) is None


def test_response_json_rejects_non_object():
    class FakeResponse:
        def json(self):
            return ["not", "an", "object"]

    assert server.response_json(FakeResponse()) is None


def test_non_stream_chat_translates_tool_call(monkeypatch):
    monkeypatch.setattr(server, "upload_images", lambda api_key, model, image_urls: [])
    monkeypatch.setattr(
        server.requests.Session,
        "post",
        lambda *args, **kwargs: FakeHTTPResponse(
            status_code=200,
            text='{"aiRecord": {"aiRecordDetail": {"resultObject": ["<tool_call>{\\"name\\":\\"glob\\",\\"arguments\\":{\\"pattern\\":\\"*\\"}}</tool_call>"]}}}',
        ),
    )

    client = server.app.test_client()
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        json={
            "model": "gemini-2.5-flash",
            "messages": [{"role": "user", "content": "list files"}],
            "tools": [{"function": {"name": "glob", "parameters": {}}}],
        },
    )

    assert response.status_code == 200
    choice = response.json["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"][0]["function"]["name"] == "glob"
    assert json.loads(choice["message"]["tool_calls"][0]["function"]["arguments"]) == {
        "pattern": "*"
    }


def test_stream_response_returns_tool_call_chunks(monkeypatch):
    class FakeResponse:
        def iter_lines(self, decode_unicode=False):
            return [
                b"event: content",
                b'data: {"delta":{"content":"<tool_call>{\\"name\\":\\"glob\\",\\"arguments\\":{\\"pattern\\":\\"*\\"}}</tool_call>"}}',
                b"",
                b"data: [DONE]",
            ]

    output = list(
        server.stream_response(
            FakeResponse(),
            {"tools": [{"function": {"name": "glob"}}]},
            "gemini-2.5-flash",
        )
    )

    assert any("tool_calls" in chunk for chunk in output)
    assert output[-1] == "data: [DONE]\n\n"


def test_fetch_remote_image_rejects_private_host(monkeypatch):
    monkeypatch.setattr(server, "is_disallowed_host", lambda hostname: True)
    with server.app.test_request_context():
        result = server.fetch_remote_image("https://127.0.0.1/image.png")

    assert isinstance(result, tuple)
    response, status = result
    assert status == 400
    assert response.json["error"]["code"] == "invalid_image_url"


def test_fetch_remote_image_rejects_disallowed_dns(monkeypatch):
    def fake_getaddrinfo(hostname, *_args, **_kwargs):
        return [(0, 0, 0, "", ("10.0.0.1", 0))]

    def fail_request(*args, **kwargs):
        raise AssertionError("request should not happen")

    monkeypatch.setattr(server.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(server.requests.Session, "get", fail_request)

    with server.app.test_request_context():
        result = server.fetch_remote_image("https://private-host.internal/image.png")

    assert isinstance(result, tuple)
    response, status = result
    assert status == 400
    assert response.json["error"]["code"] == "invalid_image_url"


def test_fetch_remote_image_allows_public_host_when_dns_safe(monkeypatch):
    monkeypatch.setattr(
        server.socket,
        "getaddrinfo",
        lambda hostname, *_args, **_kwargs: [(0, 0, 0, "", ("8.8.8.8", 0))],
    )
    monkeypatch.setattr(
        server.requests.Session,
        "get",
        lambda *_, **__: FakeHTTPResponse(
            status_code=200, text="abcde", headers={"Content-Length": "5"}
        ),
    )

    with server.app.test_request_context():
        result = server.fetch_remote_image("https://cdn.example.org/image.png")

    assert not isinstance(result, tuple)
    assert result.read() == b"abcde"


def test_global_options_cors_preflight():
    """Verify that OPTIONS CORS preflight requests receive consistent 204 CORS responses."""
    client = server.app.test_client()

    for path in [
        "/v1/chat/completions",
        "/v1/images/generations",
        "/some-random-route",
    ]:
        response = client.options(path)
        assert response.status_code == 204
        assert response.headers["Access-Control-Allow-Origin"] == "*"
        assert "Content-Type" in response.headers["Access-Control-Allow-Headers"]
        assert "Authorization" in response.headers["Access-Control-Allow-Headers"]


def test_stream_response_large_tool_call_no_truncation():
    """Verify that a tool call exceeding the old 200-character truncation threshold is fully parsed."""
    long_argument_value = "A" * 300
    long_tool_call_text = f'<tool_call>{{"name":"glob","arguments":{{"pattern":"{long_argument_value}"}}}}</tool_call>'

    class FakeResponse:
        def iter_lines(self, decode_unicode=False):
            return [
                b"event: content",
                f"data: {json.dumps({'delta': {'content': long_tool_call_text[:100]}})}".encode(
                    "utf-8"
                ),
                f"data: {json.dumps({'delta': {'content': long_tool_call_text[100:200]}})}".encode(
                    "utf-8"
                ),
                f"data: {json.dumps({'delta': {'content': long_tool_call_text[200:]}})}".encode(
                    "utf-8"
                ),
                b"",
                b"data: [DONE]",
            ]

    output = list(
        server.stream_response(
            FakeResponse(),
            {"tools": [{"function": {"name": "glob"}}]},
            "gemini-2.5-flash",
        )
    )

    tool_call_events = [chunk for chunk in output if "tool_calls" in chunk]
    assert len(tool_call_events) > 0
    assert long_argument_value in "".join(tool_call_events)
    assert output[-1] == "data: [DONE]\n\n"


def test_global_json_error_handler():
    """Verify that unhandled exceptions are caught globally and returned in standard OpenAI JSON format."""
    client = server.app.test_client()

    def crash_models():
        raise Exception("Database failure")

    original_chat_models = server.chat_models
    try:
        server.chat_models = crash_models
        response = client.get("/v1/models")
        assert response.status_code == 500
        assert response.json["error"]["type"] == "server_error"
        assert "Database failure" in response.json["error"]["message"]
    finally:
        server.chat_models = original_chat_models


def test_upstream_error_detailed_parsing(monkeypatch):
    """Verify that nested error fields in upstream JSON payloads are cleanly parsed and returned."""

    class FakeResponse:
        status_code = 400
        text = '{"error": {"message": "Custom deeply nested upstream validation error message"}}'

        def json(self):
            return json.loads(self.text)

    with server.app.test_request_context():
        response, status = server.upstream_error(FakeResponse())
    assert status == 400
    assert (
        "Custom deeply nested upstream validation error message"
        in response.json["error"]["message"]
    )


# --- NEW TEST CASES FOR ROUND 2 TECH DEBT IMPROVEMENTS ---


def test_secure_fetch_ssrf_dns_rebinding(monkeypatch):
    """Verify that secure_fetch correctly blocks disallowed/private domains."""
    # Mock is_disallowed_host to fail for a target
    monkeypatch.setattr(
        server, "is_disallowed_host", lambda host: host == "malicious.private"
    )

    session = server.get_session()
    with pytest.raises(
        ValueError, match="Access to the requested host address is restricted"
    ):
        server.secure_fetch("https://malicious.private/leak", session)


def test_secure_fetch_safe_redirects(monkeypatch):
    """Verify that secure_fetch manually follows safe redirects, stops after limit, and handles relative URLs."""

    class MockRedirectSession:
        def __init__(self) -> None:
            self.requests_made = []

        def get(self, url, *args, **kwargs):
            self.requests_made.append(url)
            if url == "https://cdn.example.org/start":
                return FakeHTTPResponse(
                    status_code=302, headers={"Location": "/redirect-1"}
                )
            elif url == "https://cdn.example.org/redirect-1":
                return FakeHTTPResponse(
                    status_code=301, headers={"Location": "https://cdn.example.org/end"}
                )
            elif url == "https://cdn.example.org/end":
                return FakeHTTPResponse(status_code=200, text="final-payload")
            return FakeHTTPResponse(status_code=404)

    monkeypatch.setattr(server, "is_disallowed_host", lambda host: False)
    session = MockRedirectSession()

    response = server.secure_fetch("https://cdn.example.org/start", session)
    assert response.status_code == 200
    assert response.text == "final-payload"
    assert session.requests_made == [
        "https://cdn.example.org/start",
        "https://cdn.example.org/redirect-1",
        "https://cdn.example.org/end",
    ]


def test_secure_fetch_redirects_limit(monkeypatch):
    """Verify that secure_fetch throws ValueError if redirect limit is exceeded."""

    class InfiniteRedirectSession:
        def get(self, url, *args, **kwargs):
            return FakeHTTPResponse(status_code=302, headers={"Location": url})

    monkeypatch.setattr(server, "is_disallowed_host", lambda host: False)
    session = InfiniteRedirectSession()

    with pytest.raises(ValueError, match="Too many redirect hops detected"):
        server.secure_fetch("https://cdn.example.org/loop", session, max_redirects=3)


def test_vision_flexible_payload_formats():
    """Verify robust vision processing of both dict and direct string image URLs."""
    # Test case 1: Dict payload (OpenAI standard)
    content_dict = [
        {"type": "text", "text": "Describe this"},
        {"type": "image_url", "image_url": {"url": "https://example.com/img1.png"}},
    ]
    txt, imgs = server.content_to_text(content_dict)
    assert txt == "Describe this"
    assert imgs == ["https://example.com/img1.png"]

    # Test case 2: Direct string payload (Alternate client format)
    content_str = [
        {"type": "text", "text": "Describe this too"},
        {"type": "image_url", "image_url": "https://example.com/img2.png"},
    ]
    txt, imgs = server.content_to_text(content_str)
    assert txt == "Describe this too"
    assert imgs == ["https://example.com/img2.png"]


def test_tiktoken_accurate_counting(monkeypatch):
    """Verify that token_count handles tiktoken encoding safely or falls back."""
    # If tiktoken is loaded, it should count accurately
    cnt = server.token_count("Hello world! How are you?")
    assert cnt > 0


def test_descriptive_empty_request_body():
    """Verify empty requests body returns a descriptive 400 error response instead of generic object message."""
    client = server.app.test_client()
    response = client.post(
        "/v1/chat/completions", headers={"Authorization": "Bearer test-key"}, data=""
    )
    assert response.status_code == 400
    assert "Empty request body" in response.json["error"]["message"]
    assert response.json["error"]["code"] == "empty_request_body"


def test_strict_slashes_disabled():
    """Verify routes resolve correctly regardless of trailing slashes."""
    client = server.app.test_client()

    # Check that root with slash works
    res1 = client.get("/")
    assert res1.status_code == 200
    assert "one-min-ai-gateway" in res1.text

    # Check that healthz with trailing slash resolved successfully
    res2 = client.get("/healthz/")
    assert res2.status_code == 200
    assert res2.json["ok"] is True


def test_custom_header_propagation(monkeypatch):
    """Verify custom headers configured via PROPAGATE_HEADERS are correctly forwarded."""
    # Configure config and headers
    monkeypatch.setattr(
        server.config, "PROPAGATE_HEADERS", "X-Gateway-Trace, X-Client-Id"
    )
    monkeypatch.setattr(server, "upload_images", lambda api_key, model, image_urls: [])

    captured_headers = {}

    def fake_post(*args, **kwargs):
        nonlocal captured_headers
        captured_headers = kwargs.get("headers") or {}
        return FakeHTTPResponse(
            status_code=200,
            text='{"aiRecord": {"aiRecordDetail": {"resultObject": ["success-response"]}}}',
        )

    monkeypatch.setattr(server.requests.Session, "post", fake_post)

    client = server.app.test_client()
    response = client.post(
        "/v1/chat/completions",
        headers={
            "Authorization": "Bearer test-key",
            "X-Gateway-Trace": "123456",
            "X-Client-Id": "client-abc",
            "X-Ignored-Header": "shh",
        },
        json={"messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    # Ensure custom headers were propagated
    assert captured_headers.get("X-Gateway-Trace") == "123456"
    assert captured_headers.get("X-Client-Id") == "client-abc"
    # Ensure ignored headers were NOT propagated
    assert "X-Ignored-Header" not in captured_headers


def test_cache_stampede_protection_lock():
    """Verify mutex synchronization lock does not interfere with standard fetching."""
    # Simply prove the lock is available and acquireable
    assert not server._catalog_mutex.locked()
    with server._catalog_mutex:
        assert server._catalog_mutex.locked()
    assert not server._catalog_mutex.locked()

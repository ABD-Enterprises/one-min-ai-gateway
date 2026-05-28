import json
import server


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
    def fail_get(*args, **kwargs):
        raise server.requests.Timeout("slow")

    monkeypatch.setattr(server.requests.Session, "get", fail_get)

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
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "aiRecord": {
                    "aiRecordDetail": {
                        "resultObject": [
                            '<tool_call>{"name":"glob","arguments":{"pattern":"*"}}</tool_call>'
                        ]
                    }
                }
            }

    monkeypatch.setattr(server, "upload_images", lambda api_key, model, image_urls: [])
    monkeypatch.setattr(
        server.requests.Session, "post", lambda *args, **kwargs: FakeResponse()
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
    class FakeResponse:
        status_code = 200
        headers = {"Content-Length": "5"}

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=1024 * 1024):
            yield b"abcde"

    monkeypatch.setattr(
        server.socket,
        "getaddrinfo",
        lambda hostname, *_args, **_kwargs: [(0, 0, 0, "", ("8.8.8.8", 0))],
    )
    monkeypatch.setattr(server.requests.Session, "get", lambda *_, **__: FakeResponse())

    with server.app.test_request_context():
        result = server.fetch_remote_image("https://cdn.example.org/image.png")

    assert not isinstance(result, tuple)
    assert result.read() == b"abcde"


# --- NEW TEST CASES FOR 20 TECH DEBT IMPROVEMENTS ---


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
            # Split the very long tool call into multiple sequential chunks
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

    # Ensure tool calls are emitted and the very long argument exists in the delta chunk
    tool_call_events = [chunk for chunk in output if "tool_calls" in chunk]
    assert len(tool_call_events) > 0
    assert long_argument_value in "".join(tool_call_events)
    assert output[-1] == "data: [DONE]\n\n"


def test_global_json_error_handler():
    """Verify that unhandled exceptions are caught globally and returned in standard OpenAI JSON format."""
    client = server.app.test_client()

    # Route index / triggers unhandled exception if we force it, or we trigger a bad requests.get
    # Let's mock a method to raise an unhandled exception
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

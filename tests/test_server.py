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

    response = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]})

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
        headers={"Authorization": "Bearer test-key", "Content-Type": "application/json"},
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

    monkeypatch.setattr(server.requests, "get", fail_get)

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
    monkeypatch.setattr(server.requests, "post", lambda *args, **kwargs: FakeResponse())

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
    assert json.loads(choice["message"]["tool_calls"][0]["function"]["arguments"]) == {"pattern": "*"}


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
    monkeypatch.setattr(server.requests, "get", fail_request)

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

    monkeypatch.setattr(server.socket, "getaddrinfo", lambda hostname, *_args, **_kwargs: [(0, 0, 0, "", ("8.8.8.8", 0))])
    monkeypatch.setattr(server.requests, "get", lambda *_, **__: FakeResponse())

    with server.app.test_request_context():
        result = server.fetch_remote_image("https://cdn.example.org/image.png")

    assert not isinstance(result, tuple)
    assert result.read() == b"abcde"

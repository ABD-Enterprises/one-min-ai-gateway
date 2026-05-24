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

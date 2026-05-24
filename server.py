from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import re
import time
import uuid
from functools import lru_cache
from importlib import metadata
from io import BytesIO
from typing import Any
from urllib.parse import urlparse

import requests
from flask import Flask, Response, jsonify, make_response, request
from werkzeug.exceptions import BadRequest
from waitress import serve


PORT = int(os.getenv("PORT", "5001"))
HOST = os.getenv("HOST", "0.0.0.0")
CATALOG_TTL_SECONDS = int(os.getenv("CATALOG_TTL_SECONDS", "300"))
MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_BYTES", str(10 * 1024 * 1024)))
CORS_ALLOW_ORIGIN = os.getenv("CORS_ALLOW_ORIGIN", "*")

MODEL_API_URL = "https://api.1min.ai/models"
CHAT_API_URL = "https://api.1min.ai/api/chat-with-ai"
CHAT_STREAM_API_URL = "https://api.1min.ai/api/chat-with-ai?isStreaming=true"
ASSET_API_URL = "https://api.1min.ai/api/assets"
FEATURE_API_URL = "https://api.1min.ai/api/features"

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("one-min-ai-gateway")


def gateway_version() -> str:
    try:
        return metadata.version("one-min-ai-gateway")
    except metadata.PackageNotFoundError:
        return "0.1.0"


def cache_bucket() -> int:
    return int(time.time() // CATALOG_TTL_SECONDS) if CATALOG_TTL_SECONDS > 0 else int(time.time())


@lru_cache(maxsize=32)
def fetch_catalog_cached(feature: str, _bucket: int) -> tuple[dict[str, Any], ...]:
    response = requests.get(MODEL_API_URL, params={"feature": feature}, timeout=30)
    response.raise_for_status()
    data = response.json()
    models = data.get("models") or []
    return tuple(entry for entry in models if isinstance(entry, dict))


def fetch_catalog(feature: str) -> list[dict[str, Any]]:
    return list(fetch_catalog_cached(feature, cache_bucket()))


def chat_models() -> list[dict[str, Any]]:
    return fetch_catalog("UNIFY_CHAT_WITH_AI")


def model_id(entry: dict[str, Any]) -> str:
    return str(entry.get("id") or entry.get("modelId") or "")


def vision_model_ids() -> set[str]:
    return {model_id(entry) for entry in fetch_catalog("CHAT_WITH_IMAGE") if model_id(entry)}


def image_model_ids() -> set[str]:
    return {model_id(entry) for entry in fetch_catalog("IMAGE_GENERATOR") if model_id(entry)}


def error_response(message: str, status: int, code: str | None = None):
    return jsonify(
        {
            "error": {
                "message": message,
                "type": "invalid_request_error" if status < 500 else "server_error",
                "param": None,
                "code": code,
            }
        }
    ), status


def bearer_key() -> str | None:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    return header.split(" ", 1)[1].strip()


def add_headers(response):
    response.headers["Access-Control-Allow-Origin"] = CORS_ALLOW_ORIGIN
    response.headers["X-Request-ID"] = str(uuid.uuid4())
    return response


@app.after_request
def add_default_headers(response):
    return add_headers(response)


def request_json() -> dict[str, Any] | tuple[Any, int]:
    try:
        data = request.get_json(force=True)
    except BadRequest:
        return error_response("Invalid JSON body.", 400, "invalid_json")
    if not isinstance(data, dict):
        return error_response("JSON body must be an object.", 400, "invalid_request_error")
    return data


def content_to_text(content: Any) -> tuple[str, list[str]]:
    if isinstance(content, str):
        return content, []
    if not isinstance(content, list):
        return "" if content is None else str(content), []

    text: list[str] = []
    images: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text" or "text" in part:
            text.append(str(part.get("text", "")))
        image_url = part.get("image_url")
        if isinstance(image_url, dict) and image_url.get("url"):
            images.append(str(image_url["url"]))
    return "\n".join(text), images


def format_messages(messages: list[dict[str, Any]]) -> tuple[str, list[str]]:
    lines: list[str] = []
    images: list[str] = []
    for message in messages:
        role = str(message.get("role", "user")).upper()
        content, message_images = content_to_text(message.get("content"))
        images.extend(message_images)

        if role == "ASSISTANT" and message.get("tool_calls"):
            lines.append(f"ASSISTANT TOOL CALLS: {json.dumps(message['tool_calls'], ensure_ascii=False)}")
        elif role == "TOOL":
            name = message.get("name") or message.get("tool_call_id") or "tool"
            lines.append(f"TOOL RESULT ({name}): {content}")
        elif content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines), images


def has_tool_result(messages: list[dict[str, Any]]) -> bool:
    return any(message.get("role") == "tool" for message in messages)


def tool_prompt(tools: list[dict[str, Any]], saw_tool_result: bool) -> str:
    rendered = []
    for tool in tools or []:
        function = tool.get("function", {}) if isinstance(tool, dict) else {}
        name = function.get("name")
        if name:
            rendered.append(
                {
                    "name": name,
                    "description": function.get("description", ""),
                    "parameters": function.get("parameters", {}),
                }
            )
    if not rendered:
        return ""

    lines = [
        "",
        "TOOLS:",
        json.dumps(rendered, ensure_ascii=False),
        "",
        "If a tool is needed, respond with exactly one line and no other text:",
        '<tool_call>{"name":"tool_name","arguments":{"arg":"value"}}</tool_call>',
        "Do not write fake progress lines, fake crawling status, Markdown tool blocks, or natural-language descriptions of a tool call.",
    ]
    if saw_tool_result:
        lines.append("Tool results are already present. Prefer answering the user now.")
    return "\n".join(lines)


def parse_tool_text(text: str, tools: list[dict[str, Any]]) -> dict[str, Any] | None:
    available = {
        tool.get("function", {}).get("name")
        for tool in tools or []
        if isinstance(tool, dict) and tool.get("function", {}).get("name")
    }

    match = re.search(r"<tool_(?:call|code)>\s*(\{.*?\})\s*</tool_(?:call|code)>", text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(1))
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            name = parsed.get("name") or parsed.get("tool")
            args = parsed.get("arguments") or parsed.get("input") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"input": args}
            if name and (not available or name in available):
                return {"name": name, "arguments": args if isinstance(args, dict) else {}}

    match = re.search(r"\[tool_code_bash_call\]:\s*(.+)", text, re.DOTALL)
    if match and (not available or "bash" in available):
        return {"name": "bash", "arguments": {"command": match.group(1).strip()}}

    match = re.search(
        r"\[tool_code:\s*([A-Za-z0-9_-]+)\s+for\s+([A-Za-z0-9_-]+)\s+(['\"])(.*?)\3\s*\]",
        text,
        re.DOTALL,
    )
    if match:
        name = match.group(1)
        if not available or name in available:
            return {"name": name, "arguments": {match.group(2): match.group(4)}}
    return None


def clean_text(text: str) -> str:
    lines = [line for line in text.splitlines() if not line.strip().startswith("🌐 Crawling site ")]
    return "\n".join(lines).strip()


def tool_message(tool_call: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": f"call_{uuid.uuid4().hex[:24]}",
                "type": "function",
                "function": {
                    "name": tool_call["name"],
                    "arguments": json.dumps(tool_call.get("arguments", {}), ensure_ascii=False),
                },
            }
        ],
    }


def upstream_error(response):
    if response.status_code in {401, 403}:
        return error_response("Invalid Authentication", 401, "invalid_api_key")
    try:
        body = response.json()
    except ValueError:
        body = response.text[:500]
    logger.error("1min.ai upstream error %s: %s", response.status_code, body)
    return error_response(f"1min.ai API error ({response.status_code}): {body}", response.status_code)


def response_json(response) -> dict[str, Any] | None:
    try:
        data = response.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def decode_data_image(image_url: str) -> BytesIO | tuple[Any, int]:
    try:
        encoded = image_url.split(",", 1)[1]
    except IndexError:
        return error_response("Invalid image data URL.", 400, "invalid_image")
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return error_response("Invalid base64 image data.", 400, "invalid_image")
    if len(payload) > MAX_IMAGE_BYTES:
        return error_response("Image payload is too large.", 413, "image_too_large")
    return BytesIO(payload)


def fetch_remote_image(image_url: str) -> BytesIO | tuple[Any, int]:
    parsed = urlparse(image_url)
    if parsed.scheme not in {"http", "https"}:
        return error_response("Image URL must use http or https.", 400, "invalid_image_url")
    try:
        fetched = requests.get(image_url, timeout=30, stream=True)
        fetched.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("failed to fetch image URL: %s", exc)
        return error_response("Could not fetch image URL.", 400, "invalid_image_url")
    content_length = fetched.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > MAX_IMAGE_BYTES:
                return error_response("Image payload is too large.", 413, "image_too_large")
        except ValueError:
            pass

    data = BytesIO()
    for chunk in fetched.iter_content(chunk_size=1024 * 1024):
        if not chunk:
            continue
        data.write(chunk)
        if data.tell() > MAX_IMAGE_BYTES:
            return error_response("Image payload is too large.", 413, "image_too_large")
    data.seek(0)
    return data


def upload_images(api_key: str, model: str, image_urls: list[str]) -> list[str] | tuple[Any, int]:
    if not image_urls:
        return []
    if model not in vision_model_ids():
        return error_response(f"This model does not support image inputs: {model}", 400, "model_not_supported")

    paths: list[str] = []
    for image_url in image_urls:
        if image_url.startswith("data:image/"):
            binary_data = decode_data_image(image_url)
        else:
            binary_data = fetch_remote_image(image_url)
        if isinstance(binary_data, tuple):
            return binary_data
        upload = requests.post(
            ASSET_API_URL,
            files={"asset": (f"gateway-{uuid.uuid4()}.png", binary_data, "image/png")},
            headers={"API-KEY": api_key},
            timeout=60,
        )
        if upload.status_code != 200:
            return upstream_error(upload)
        upload_data = response_json(upload)
        if not upload_data:
            return upstream_error(upload)
        try:
            paths.append(upload_data["fileContent"]["path"])
        except KeyError:
            return upstream_error(upload)
    return paths


def build_payload(api_key: str, data: dict[str, Any]):
    messages = data.get("messages") or []
    if not messages:
        return error_response("No message provided.", 400, "invalid_request_error")

    model = data.get("model", "gpt-4o")
    prompt, image_urls = format_messages(messages)
    prompt += tool_prompt(data.get("tools") or [], has_tool_result(messages))

    image_paths = upload_images(api_key, model, image_urls)
    if isinstance(image_paths, tuple):
        return image_paths

    payload: dict[str, Any] = {
        "type": "UNIFY_CHAT_WITH_AI",
        "model": model,
        "promptObject": {"prompt": prompt},
    }
    if image_paths:
        payload["promptObject"]["attachments"] = {"images": image_paths}
    return payload


def extract_result_text(data: dict[str, Any]) -> str | None:
    try:
        result = data["aiRecord"]["aiRecordDetail"]["resultObject"][0]
    except (KeyError, IndexError, TypeError):
        return None
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)


def token_count(text: str) -> int:
    return max(1, len(text) // 4)


@app.route("/", methods=["GET"])
def index():
    return "one-min-ai-gateway\n"


@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify({"ok": True, "version": gateway_version()})


@app.route("/v1/models", methods=["GET"])
def models():
    return jsonify(
        {
            "object": "list",
            "data": [
                {
                    "id": model_id(entry),
                    "object": "model",
                    "created": 1727389042,
                    "owned_by": "1minai",
                }
                for entry in chat_models()
                if model_id(entry)
            ],
        }
    )


@app.route("/v1/chat/completions", methods=["POST", "OPTIONS"])
def chat_completions():
    if request.method == "OPTIONS":
        response = make_response()
        response.headers["Access-Control-Allow-Origin"] = CORS_ALLOW_ORIGIN
        response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
        response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        return response, 204

    api_key = bearer_key()
    if not api_key:
        return error_response("Invalid Authentication", 401, "invalid_api_key")

    data = request_json()
    if isinstance(data, tuple):
        return data
    payload = build_payload(api_key, data)
    if isinstance(payload, tuple):
        return payload

    headers = {"API-KEY": api_key, "Content-Type": "application/json"}
    model = data.get("model", "gpt-4o")
    if data.get("stream"):
        upstream = requests.post(CHAT_STREAM_API_URL, data=json.dumps(payload), headers=headers, stream=True, timeout=180)
        if upstream.status_code != 200:
            return upstream_error(upstream)
        return Response(stream_response(upstream, data, model), content_type="text/event-stream")

    upstream = requests.post(CHAT_API_URL, json=payload, headers=headers, timeout=180)
    if upstream.status_code != 200:
        return upstream_error(upstream)

    upstream_data = response_json(upstream)
    if upstream_data is None:
        return upstream_error(upstream)
    raw_text = extract_result_text(upstream_data)
    if raw_text is None:
        return upstream_error(upstream)
    call = parse_tool_text(raw_text, data.get("tools") or [])
    output_text = clean_text(raw_text)
    prompt_tokens = token_count(payload["promptObject"]["prompt"])
    completion_tokens = token_count(output_text)
    return add_headers(
        jsonify(
            {
                "id": f"chatcmpl-{uuid.uuid4()}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": tool_message(call) if call else {"role": "assistant", "content": output_text},
                        "finish_reason": "tool_calls" if call else "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
            }
        )
    )


def stream_response(upstream, data: dict[str, Any], model: str):
    chunks: list[str] = []
    current_event = None
    stream_id = f"chatcmpl-{uuid.uuid4()}"

    for raw_line in upstream.iter_lines(decode_unicode=False):
        if raw_line == b"":
            current_event = None
            continue
        line = raw_line.decode("utf-8", errors="replace")
        if line.startswith("event:"):
            current_event = line.split(":", 1)[1].strip()
            continue
        if not line.startswith("data:"):
            continue
        raw_data = line.split(":", 1)[1].strip()
        if raw_data == "[DONE]":
            break
        if (current_event or "content") != "content":
            continue
        try:
            parsed = json.loads(raw_data)
            content = parsed.get("content") or parsed.get("delta", {}).get("content") or ""
        except json.JSONDecodeError:
            content = raw_data
        if content:
            chunks.append(content)

    raw_text = "".join(chunks)
    call = parse_tool_text(raw_text, data.get("tools") or [])
    output_text = clean_text(raw_text)
    if call:
        call_payload = tool_message(call)["tool_calls"][0]
        yield "data: " + json.dumps(
            {
                "id": stream_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{"index": 0, "delta": {"tool_calls": [{**call_payload, "index": 0}]}, "finish_reason": None}],
            },
            ensure_ascii=False,
        ) + "\n\n"
        yield "data: " + json.dumps(
            {
                "id": stream_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
            },
            ensure_ascii=False,
        ) + "\n\n"
        yield "data: [DONE]\n\n"
        return

    if output_text:
        yield "data: " + json.dumps(
            {
                "id": stream_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{"index": 0, "delta": {"content": output_text}, "finish_reason": None}],
            },
            ensure_ascii=False,
        ) + "\n\n"

    yield "data: " + json.dumps(
        {
            "id": stream_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        },
        ensure_ascii=False,
    ) + "\n\n"
    yield "data: [DONE]\n\n"


@app.route("/v1/images/generations", methods=["POST"])
def image_generations():
    api_key = bearer_key()
    if not api_key:
        return error_response("Invalid Authentication", 401, "invalid_api_key")

    data = request_json()
    if isinstance(data, tuple):
        return data
    model = data.get("model", "black-forest-labs/flux-schnell")
    if model not in image_model_ids():
        return error_response(f"This model does not support image generation: {model}", 400, "model_not_supported")

    prompt = data.get("prompt")
    if not prompt:
        return error_response("No prompt provided.", 400, "invalid_request_error")

    upstream = requests.post(
        FEATURE_API_URL + "?isStreaming=false",
        json={
            "type": "IMAGE_GENERATOR",
            "model": model,
            "promptObject": {
                "prompt": prompt,
                "n": data.get("n", 1),
                "size": data.get("size", "1024x1024"),
            },
        },
        headers={"API-KEY": api_key, "Content-Type": "application/json"},
        timeout=180,
    )
    if upstream.status_code != 200:
        return upstream_error(upstream)

    upstream_data = response_json(upstream)
    if upstream_data is None:
        return upstream_error(upstream)
    try:
        urls = upstream_data["aiRecord"]["aiRecordDetail"]["resultObject"]
    except (KeyError, TypeError):
        return upstream_error(upstream)
    if not isinstance(urls, list):
        return upstream_error(upstream)
    return jsonify({"created": int(time.time()), "data": [{"url": url} for url in urls]})


if __name__ == "__main__":
    logger.info("one-min-ai-gateway listening on %s:%s", HOST, PORT)
    serve(app, host=HOST, port=PORT, threads=8)

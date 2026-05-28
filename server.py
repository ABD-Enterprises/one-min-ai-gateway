from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import socket
import re
import time
import uuid
import ipaddress
from functools import lru_cache
from importlib import metadata
from io import BytesIO
from typing import Any, Generator
from urllib.parse import urlparse

import requests
from flask import (
    Flask,
    Response,
    jsonify,
    make_response,
    request,
    Blueprint,
    g,
    has_request_context,
)
from werkzeug.exceptions import BadRequest
from waitress import serve


# 7. Centralized Default Model Configurations
DEFAULT_CHAT_MODEL = os.getenv("DEFAULT_CHAT_MODEL", "gpt-4o")
DEFAULT_IMAGE_MODEL = os.getenv("DEFAULT_IMAGE_MODEL", "black-forest-labs/flux-schnell")

# 8. Hardcoded Upstream API Base URLs
ONE_MIN_API_BASE_URL = os.getenv("ONE_MIN_API_BASE_URL", "https://api.1min.ai").rstrip(
    "/"
)
MODEL_API_URL = f"{ONE_MIN_API_BASE_URL}/models"
CHAT_API_URL = f"{ONE_MIN_API_BASE_URL}/api/chat-with-ai"
CHAT_STREAM_API_URL = f"{ONE_MIN_API_BASE_URL}/api/chat-with-ai?isStreaming=true"
ASSET_API_URL = f"{ONE_MIN_API_BASE_URL}/api/assets"
FEATURE_API_URL = f"{ONE_MIN_API_BASE_URL}/api/features"

# 15. Lack of SSL/TLS Verification Customizability
GATEWAY_VERIFY_SSL = os.getenv("GATEWAY_VERIFY_SSL", "true").lower() in (
    "true",
    "1",
    "yes",
)

PORT_ENV = os.getenv("PORT", "5001")
try:
    PORT = int(PORT_ENV)
except ValueError:
    # 12. Crashes on Invalid PORT Environment Variable
    PORT = 5001

HOST = os.getenv("HOST", "0.0.0.0")
CATALOG_TTL_SECONDS = int(os.getenv("CATALOG_TTL_SECONDS", "300"))
MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_BYTES", str(10 * 1024 * 1024)))
CORS_ALLOW_ORIGIN = os.getenv("CORS_ALLOW_ORIGIN", "*")

logger = logging.getLogger("one-min-ai-gateway")

# 5. Persistent Connection Pooling
_session: requests.Session | None = None


def get_session() -> requests.Session:
    """Get or initialize the persistent requests Session for connection pooling.

    Returns:
        requests.Session: The configured requests Session object.
    """
    global _session
    if _session is None:
        _session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=20)
        _session.mount("https://", adapter)
        _session.mount("http://", adapter)
    return _session


# 6. Observability: Request ID Correlation in Logs
class RequestIdFilter(logging.Filter):
    """Logging filter to inject request_id from Flask g into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if has_request_context():
            record.request_id = getattr(g, "request_id", "-")
        else:
            record.request_id = "-"
        return True


def configure_logging() -> None:
    """Configure global and logger-specific logging with correlation IDs."""
    logging.basicConfig(level=logging.INFO)
    root = logging.getLogger()
    req_filter = RequestIdFilter()
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s [Request-ID: %(request_id)s] %(name)s: %(message)s"
    )

    # Configure root handlers
    for handler in root.handlers:
        handler.addFilter(req_filter)
        handler.setFormatter(formatter)

    # Configure gateway logger handlers
    for handler in logger.handlers:
        handler.addFilter(req_filter)
        handler.setFormatter(formatter)
    logger.setLevel(logging.INFO)


def gateway_version() -> str:
    """Retrieve the installed package version or fallback version.

    Returns:
        str: Package version identifier.
    """
    try:
        return metadata.version("one-min-ai-gateway")
    except metadata.PackageNotFoundError:
        return "0.1.1"


def cache_bucket() -> int:
    """Generate cache bucket key based on the TTL configuration.

    Returns:
        int: Time-based bucket identifier.
    """
    return (
        int(time.time() // CATALOG_TTL_SECONDS)
        if CATALOG_TTL_SECONDS > 0
        else int(time.time())
    )


@lru_cache(maxsize=32)
def fetch_catalog_cached(feature: str, _bucket: int) -> tuple[dict[str, Any], ...]:
    """Fetch model catalog with TTL caching.

    Args:
        feature: The model feature identifier.
        _bucket: The current cache bucket ID.

    Returns:
        tuple[dict[str, Any], ...]: The models entries catalog.
    """
    try:
        response = get_session().get(
            MODEL_API_URL,
            params={"feature": feature},
            timeout=30,
            verify=GATEWAY_VERIFY_SSL,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        logger.warning("failed to fetch model catalog for feature %s: %s", feature, exc)
        return tuple()
    except ValueError:
        logger.warning("failed to parse model catalog response for feature %s", feature)
        return tuple()

    models = data.get("models") if isinstance(data, dict) else []
    if not isinstance(models, list):
        models = []
    return tuple(entry for entry in models if isinstance(entry, dict))


def fetch_catalog(feature: str) -> list[dict[str, Any]]:
    """Fetch catalog for a given feature using active cache bucket.

    Args:
        feature: The feature identifier.

    Returns:
        list[dict[str, Any]]: List of matching models.
    """
    return list(fetch_catalog_cached(feature, cache_bucket()))


def chat_models() -> list[dict[str, Any]]:
    """Fetch chat models from the model catalog.

    Returns:
        list[dict[str, Any]]: List of chat models.
    """
    return fetch_catalog("UNIFY_CHAT_WITH_AI")


def model_id(entry: dict[str, Any]) -> str:
    """Safely extract model ID from a catalog entry.

    Args:
        entry: The catalog model entry.

    Returns:
        str: The identified model ID.
    """
    # 19. Inefficient Model ID Parsing Fallbacks
    val = entry.get("id") or entry.get("modelId")
    if not val:
        logger.warning("Catalog model entry lacks a valid identifier: %s", entry)
        return ""
    return str(val)


# 20. Vision and Image Model ID Sets Cache Invalidation
@lru_cache(maxsize=32)
def vision_model_ids_cached(_bucket: int) -> set[str]:
    """Retrieve and cache vision model IDs for the active cache bucket."""
    return {
        model_id(entry) for entry in fetch_catalog("CHAT_WITH_IMAGE") if model_id(entry)
    }


def vision_model_ids() -> set[str]:
    """Retrieve current set of vision model IDs.

    Returns:
        set[str]: Set of model IDs supporting image inputs.
    """
    return vision_model_ids_cached(cache_bucket())


@lru_cache(maxsize=32)
def image_model_ids_cached(_bucket: int) -> set[str]:
    """Retrieve and cache image generator model IDs for the active cache bucket."""
    return {
        model_id(entry) for entry in fetch_catalog("IMAGE_GENERATOR") if model_id(entry)
    }


def image_model_ids() -> set[str]:
    """Retrieve current set of image model IDs.

    Returns:
        set[str]: Set of model IDs supporting image generation.
    """
    return image_model_ids_cached(cache_bucket())


def error_response(
    message: str, status: int, code: str | None = None
) -> tuple[Response, int]:
    """Build a standard OpenAI-compatible API error response.

    Args:
        message: Readable error message.
        status: HTTP status code.
        code: Specific error code.

    Returns:
        tuple[Response, int]: Flask response and status code.
    """
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
    """Extract bearer API key from Authorization header.

    Returns:
        str | None: The API key if found, else None.
    """
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    return header.split(" ", 1)[1].strip()


def add_headers(response: Response) -> Response:
    """Inject standard CORS and Request ID correlation headers into response.

    Args:
        response: Flask Response object.

    Returns:
        Response: The modified Response object.
    """
    response.headers["Access-Control-Allow-Origin"] = CORS_ALLOW_ORIGIN

    # Propagate the request ID if available
    req_id = getattr(g, "request_id", None) or str(uuid.uuid4())
    response.headers["X-Request-ID"] = req_id
    return response


def request_json() -> dict[str, Any] | tuple[Response, int]:
    """Safely parse incoming JSON body.

    Returns:
        dict[str, Any] | tuple[Response, int]: Parsed JSON dict or Flask error response.
    """
    try:
        data = request.get_json(force=True)
    except BadRequest:
        return error_response("Invalid JSON body.", 400, "invalid_json")
    if not isinstance(data, dict):
        return error_response(
            "JSON body must be an object.", 400, "invalid_request_error"
        )
    return data


def content_to_text(content: Any) -> tuple[str, list[str]]:
    """Convert OpenAI message content to prompt text and remote image URLs.

    Args:
        content: OpenAI message content structure.

    Returns:
        tuple[str, list[str]]: Text content and image URLs.
    """
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
    """Format messages array into clean flat prompt and remote image URLs.

    Args:
        messages: List of chat messages.

    Returns:
        tuple[str, list[str]]: Consolidated prompt text and remote image URLs.
    """
    lines: list[str] = []
    images: list[str] = []
    for message in messages:
        role = str(message.get("role", "user")).upper()
        content, message_images = content_to_text(message.get("content"))
        images.extend(message_images)

        if role == "ASSISTANT" and message.get("tool_calls"):
            lines.append(
                f"ASSISTANT TOOL CALLS: {json.dumps(message['tool_calls'], ensure_ascii=False)}"
            )
        elif role == "TOOL":
            name = message.get("name") or message.get("tool_call_id") or "tool"
            lines.append(f"TOOL RESULT ({name}): {content}")
        elif content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines), images


def has_tool_result(messages: list[dict[str, Any]]) -> bool:
    """Check if tool execution output is present in the messages sequence.

    Args:
        messages: The chat messages.

    Returns:
        bool: True if there is a tool response.
    """
    return any(message.get("role") == "tool" for message in messages)


def tool_prompt(tools: list[dict[str, Any]], saw_tool_result: bool) -> str:
    """Format tool declarations into instructions for prompt injection.

    Args:
        tools: Tool declarations.
        saw_tool_result: If tool result was already provided.

    Returns:
        str: Instructions injection snippet.
    """
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
    """Parse output text to discover structured tool calls.

    Args:
        text: Model output text.
        tools: Supported tools configuration.

    Returns:
        dict[str, Any] | None: Parse tool call dictionary, if found.
    """
    available = {
        tool.get("function", {}).get("name")
        for tool in tools or []
        if isinstance(tool, dict) and tool.get("function", {}).get("name")
    }

    match = re.search(
        r"<tool_(?:call|code)>\s*(\{.*?\})\s*</tool_(?:call|code)>", text, re.DOTALL
    )
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
                return {
                    "name": name,
                    "arguments": args if isinstance(args, dict) else {},
                }

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
    """Clean specific crawl status lines from output text.

    Args:
        text: The text to clean.

    Returns:
        str: Cleaned text content.
    """
    lines = [
        line
        for line in text.splitlines()
        if not line.strip().startswith("🌐 Crawling site ")
    ]
    return "\n".join(lines).strip()


def tool_message(tool_call: dict[str, Any]) -> dict[str, Any]:
    """Build standard OpenAI assistant tool response.

    Args:
        tool_call: Decoded tool call details.

    Returns:
        dict[str, Any]: Formatted tool assistant response message.
    """
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": f"call_{uuid.uuid4().hex[:24]}",
                "type": "function",
                "function": {
                    "name": tool_call["name"],
                    "arguments": json.dumps(
                        tool_call.get("arguments", {}), ensure_ascii=False
                    ),
                },
            }
        ],
    }


def upstream_error(response: requests.Response) -> tuple[Response, int]:
    """Parse and translate errors from upstream 1min.ai APIs.

    Args:
        response: Upstream response.

    Returns:
        tuple[Response, int]: Translated API response and status.
    """
    if response.status_code in {401, 403}:
        return error_response("Invalid Authentication", 401, "invalid_api_key")
    try:
        body = response.json()
    except ValueError:
        body = response.text[:500]

    # 10. Upstream Error Detail Parsing
    error_msg = ""
    if isinstance(body, dict):
        if "error" in body:
            err = body["error"]
            if isinstance(err, dict):
                error_msg = err.get("message") or err.get("errorMessage") or ""
            elif isinstance(err, str):
                error_msg = err
        if not error_msg:
            error_msg = (
                body.get("message")
                or body.get("errorMessage")
                or body.get("error")
                or ""
            )

    if not error_msg:
        error_msg = str(body)

    logger.error("1min.ai upstream error %s: %s", response.status_code, error_msg)
    return error_response(
        f"1min.ai API error ({response.status_code}): {error_msg}", response.status_code
    )


def response_json(response: requests.Response) -> dict[str, Any] | None:
    """Parse response JSON safely checking for dictionary type compatibility.

    Args:
        response: requests Response.

    Returns:
        dict[str, Any] | None: Dictionary data structure, or None.
    """
    try:
        data = response.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def is_disallowed_host(hostname: str) -> bool:
    """Validate remote hostname against DNS and loopback/private range bypass.

    Args:
        hostname: Input host address string.

    Returns:
        bool: True if hostname resolves to private ranges or is disallowed.
    """
    normalized = (hostname or "").strip().lower().strip("[]")
    if not normalized:
        return True
    if normalized in {"localhost", "localhost.localdomain"}:
        return True

    try:
        ip = ipaddress.ip_address(normalized)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
    except ValueError:
        pass

    try:
        addresses = socket.getaddrinfo(normalized, None)
    except socket.gaierror:
        return False

    for _, _, _, _, sockaddr in addresses:
        if not sockaddr:
            continue
        ip_str = sockaddr[0]
        if ip_str.startswith("::ffff:"):
            ip_str = ip_str[7:]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return True
    return False


def validate_messages(messages: Any) -> tuple[Response, int] | None:
    """Verify standard schema and format of messages list.

    Args:
        messages: Input raw message structure.

    Returns:
        tuple[Response, int] | None: Error response if invalid, else None.
    """
    if not isinstance(messages, list) or not messages:
        return error_response(
            "messages must be a non-empty array.", 400, "invalid_request_error"
        )

    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            return error_response(
                f"Message at index {index} must be an object.",
                400,
                "invalid_request_error",
            )
    return None


def decode_data_image(image_url: str) -> BytesIO | tuple[Response, int]:
    """Decode local inline base64 image data payload.

    Args:
        image_url: Local base64 string URL.

    Returns:
        BytesIO | tuple[Response, int]: Raw data block, or error response.
    """
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


def fetch_remote_image(image_url: str) -> BytesIO | tuple[Response, int]:
    """Fetch remote HTTP/HTTPS image safely avoiding internal network lookups.

    Args:
        image_url: Remote web address.

    Returns:
        BytesIO | tuple[Response, int]: Downloaded image buffer, or error response.
    """
    parsed = urlparse(image_url)
    if parsed.scheme not in {"http", "https"}:
        return error_response(
            "Image URL must use http or https.", 400, "invalid_image_url"
        )
    if not parsed.hostname:
        return error_response("Invalid image URL.", 400, "invalid_image_url")
    if is_disallowed_host(parsed.hostname):
        return error_response(
            "Image URL host is not allowed.", 400, "invalid_image_url"
        )

    try:
        # Use connection pool session
        fetched = get_session().get(
            image_url,
            timeout=30,
            stream=True,
            allow_redirects=False,
            verify=GATEWAY_VERIFY_SSL,
        )
        fetched.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("failed to fetch image URL: %s", exc)
        return error_response("Could not fetch image URL.", 400, "invalid_image_url")

    if 300 <= fetched.status_code < 400:
        return error_response("Could not fetch image URL.", 400, "invalid_image_url")

    content_length = fetched.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > MAX_IMAGE_BYTES:
                return error_response(
                    "Image payload is too large.", 413, "image_too_large"
                )
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


def upload_images(
    api_key: str, model: str, image_urls: list[str]
) -> list[str] | tuple[Response, int]:
    """Download, validate, and upload images to 1min.ai assets api.

    Args:
        api_key: API credentials token.
        model: Target model selector.
        image_urls: Raw model input image paths.

    Returns:
        list[str] | tuple[Response, int]: Uploaded asset path IDs, or error response.
    """
    if not image_urls:
        return []
    if model not in vision_model_ids():
        return error_response(
            f"This model does not support image inputs: {model}",
            400,
            "model_not_supported",
        )

    paths: list[str] = []
    for image_url in image_urls:
        if image_url.startswith("data:image/"):
            binary_data = decode_data_image(image_url)
        else:
            binary_data = fetch_remote_image(image_url)
        if isinstance(binary_data, tuple):
            return binary_data

        # Use connection pool session
        upload = get_session().post(
            ASSET_API_URL,
            files={"asset": (f"gateway-{uuid.uuid4()}.png", binary_data, "image/png")},
            headers={"API-KEY": api_key},
            timeout=60,
            verify=GATEWAY_VERIFY_SSL,
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


def build_payload(
    api_key: str, data: dict[str, Any]
) -> dict[str, Any] | tuple[Response, int]:
    """Assemble final JSON payload structure required by the upstream API.

    Args:
        api_key: Credentials token.
        data: User request body parameters.

    Returns:
        dict[str, Any] | tuple[Response, int]: Formatted payload dict, or error response.
    """
    messages = data.get("messages") or []
    validation = validate_messages(messages)
    if validation is not None:
        return validation

    model = data.get("model", DEFAULT_CHAT_MODEL)
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
    """Parse result object to extract clean upstream text output.

    Args:
        data: Upstream response data.

    Returns:
        str | None: Raw text result if found, else None.
    """
    try:
        result = data["aiRecord"]["aiRecordDetail"]["resultObject"][0]
    except (KeyError, IndexError, TypeError):
        return None
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)


def token_count(text: str) -> int:
    """Estimate token count for response metric tracking.

    Args:
        text: Core input string.

    Returns:
        int: Estimated token count integer.
    """
    return max(1, len(text) // 4)


# 3. Application Factory Blueprint
bp = Blueprint("gateway", __name__)


@bp.route("/", methods=["GET"])
def index() -> str:
    """Retrieve welcome message.

    Returns:
        str: Welcome message string.
    """
    return "one-min-ai-gateway\n"


@bp.route("/healthz", methods=["GET"])
def healthz() -> tuple[Response, int]:
    """Verify backend system and gateway operational health status.

    Returns:
        tuple[Response, int]: JSON ok and version info.
    """
    return jsonify({"ok": True, "version": gateway_version()}), 200


@bp.route("/v1/models", methods=["GET"])
def models() -> tuple[Response, int]:
    """Retrieve active list of mock/upstream models in OpenAI schema format.

    Returns:
        tuple[Response, int]: OpenAI-compatible model listing.
    """
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
    ), 200


@bp.route("/v1/chat/completions", methods=["POST", "OPTIONS"])
def chat_completions() -> tuple[Response, int] | Response:
    """OpenAI-compatible chat completions proxy endpoint supporting text, images, and streaming.

    Returns:
        tuple[Response, int] | Response: Completion output or chunked EventStream.
    """
    # Note: OPTIONS is also handled globally by before_request but kept for interface completeness
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
    model = data.get("model", DEFAULT_CHAT_MODEL)
    if data.get("stream"):
        # Use connection pool session
        upstream = get_session().post(
            CHAT_STREAM_API_URL,
            data=json.dumps(payload),
            headers=headers,
            stream=True,
            timeout=180,
            verify=GATEWAY_VERIFY_SSL,
        )
        if upstream.status_code != 200:
            return upstream_error(upstream)
        return Response(
            stream_response(upstream, data, model), content_type="text/event-stream"
        )

    # Use connection pool session
    upstream = get_session().post(
        CHAT_API_URL,
        json=payload,
        headers=headers,
        timeout=180,
        verify=GATEWAY_VERIFY_SSL,
    )
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
    return jsonify(
        {
            "id": f"chatcmpl-{uuid.uuid4()}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": tool_message(call)
                    if call
                    else {"role": "assistant", "content": output_text},
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


def stream_response(
    upstream: requests.Response, data: dict[str, Any], model: str
) -> Generator[str, None, None]:
    """Stream response back to client with robust tool call buffering protection.

    Args:
        upstream: Stream response object from 1min.ai.
        data: Core user request body.
        model: Target model indicator.

    Yields:
        Generator[str, None, None]: Server-Sent Event chunk sequences.
    """
    buffered_text = ""
    tail_size = 200
    current_event = None
    stream_id = f"chatcmpl-{uuid.uuid4()}"
    tools = data.get("tools") or []

    # 1. Dynamic Tool Call Streaming Truncation (Parser Buffering)
    in_tool_buffering = False

    def emit_content_chunk(content: str, finish_reason: str | None = None) -> str:
        if not content:
            return ""
        return (
            "data: "
            + json.dumps(
                {
                    "id": stream_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": content},
                            "finish_reason": finish_reason,
                        }
                    ],
                },
                ensure_ascii=False,
            )
            + "\n\n"
        )

    def emit_tool_call(call: dict[str, Any]) -> Generator[str, None, None]:
        call_payload = tool_message(call)["tool_calls"][0]
        yield (
            "data: "
            + json.dumps(
                {
                    "id": stream_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"tool_calls": [{**call_payload, "index": 0}]},
                            "finish_reason": None,
                        }
                    ],
                },
                ensure_ascii=False,
            )
            + "\n\n"
        )
        yield (
            "data: "
            + json.dumps(
                {
                    "id": stream_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {"index": 0, "delta": {}, "finish_reason": "tool_calls"}
                    ],
                },
                ensure_ascii=False,
            )
            + "\n\n"
        )

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
            content = (
                parsed.get("content") or parsed.get("delta", {}).get("content") or ""
            )
        except json.JSONDecodeError:
            content = raw_data

        if content:
            buffered_text += content

            # Start buffering if tag is detected
            if not in_tool_buffering and (
                "<tool_call" in buffered_text or "<tool_code" in buffered_text
            ):
                in_tool_buffering = True

            if in_tool_buffering:
                if "</tool_call>" in buffered_text or "</tool_code>" in buffered_text:
                    call = parse_tool_text(buffered_text, tools)
                    if call:
                        yield from emit_tool_call(call)
                        yield "data: [DONE]\n\n"
                        return
                    else:
                        # Found closing tag but not a valid tool call, disable special buffering to flush
                        in_tool_buffering = False
                elif len(buffered_text) > 8000:
                    # Safety threshold limit exceeded, disable tool buffering to flush
                    in_tool_buffering = False

            if not in_tool_buffering:
                if len(buffered_text) > tail_size:
                    flush = buffered_text[:-tail_size]
                    if flush:
                        cleaned = clean_text(flush)
                        chunk = emit_content_chunk(cleaned)
                        if chunk:
                            yield chunk
                    buffered_text = buffered_text[-tail_size:]

    text = clean_text(buffered_text)
    if text:
        chunk = emit_content_chunk(text)
        if chunk:
            yield chunk

    yield (
        "data: "
        + json.dumps(
            {
                "id": stream_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            },
            ensure_ascii=False,
        )
        + "\n\n"
    )
    yield "data: [DONE]\n\n"


@bp.route("/v1/images/generations", methods=["POST", "OPTIONS"])
def image_generations() -> tuple[Response, int]:
    """OpenAI-compatible image generation proxy endpoint.

    Returns:
        tuple[Response, int]: List of generated asset URLs.
    """
    # Note: OPTIONS is also handled globally by before_request but kept for interface completeness
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
    model = data.get("model", DEFAULT_IMAGE_MODEL)
    if model not in image_model_ids():
        return error_response(
            f"This model does not support image generation: {model}",
            400,
            "model_not_supported",
        )

    prompt = data.get("prompt")
    if not prompt:
        return error_response("No prompt provided.", 400, "invalid_request_error")

    # Use connection pool session
    upstream = get_session().post(
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
        verify=GATEWAY_VERIFY_SSL,
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
    return jsonify(
        {"created": int(time.time()), "data": [{"url": url} for url in urls]}
    ), 200


# 6. Application Factory Pattern Refactoring
def create_app() -> Flask:
    """Flask application factory that configures and prepares the gateway instance.

    Returns:
        Flask: Configured Flask application.
    """
    app = Flask(__name__)

    # 11. Relocate global logging initialization inside create_app
    configure_logging()

    # 4. Global OPTIONS CORS Preflight interceptor
    @app.before_request
    def handle_options_preflight() -> Response | None:
        if request.method == "OPTIONS":
            response = make_response()
            response.headers["Access-Control-Allow-Origin"] = CORS_ALLOW_ORIGIN
            response.headers["Access-Control-Allow-Headers"] = (
                "Content-Type,Authorization"
            )
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            return response, 204
        return None

    # 7. Request ID Correlation & Request Latency Start Hook
    @app.before_request
    def start_request() -> None:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        g.request_id = request_id
        g.start_time = time.time()

    # 18. Consolidate Response Headers Injection & Request Latency Logging Hook
    @app.after_request
    def log_and_headers_response(response: Response) -> Response:
        response = add_headers(response)
        start_time = getattr(g, "start_time", None)
        if start_time is not None:
            # 8. Request Duration and Latency Logging
            duration_ms = (time.time() - start_time) * 1000
            logger.info(
                "%s %s %s - completed in %.2fms",
                request.method,
                request.path,
                response.status_code,
                duration_ms,
            )
        return response

    # 5. Global Exception JSON Error Handler
    @app.errorhandler(Exception)
    def handle_exception(exc: Exception) -> tuple[Response, int]:
        logger.exception("Unhandled error occurred in gateway: %s", exc)
        status_code = 500
        if hasattr(exc, "code") and isinstance(exc.code, int):
            status_code = exc.code
        message = str(exc)
        return error_response(message, status_code, "server_error")

    app.register_blueprint(bp)
    return app


# Maintain backward compatibility with WSGI imports
app = create_app()

if __name__ == "__main__":
    logger.info("one-min-ai-gateway listening on %s:%s", HOST, PORT)
    try:
        threads_conf = int(os.getenv("WAITRESS_THREADS", "8"))
    except ValueError:
        # 9. Hardcoded Waitress Server Thread Concurrency
        threads_conf = 8
    serve(app, host=HOST, port=PORT, threads=threads_conf)

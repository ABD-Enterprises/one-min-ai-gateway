# one-min-ai-gateway

OpenAI-compatible gateway for [1min.ai](https://1min.ai/).

1min.ai exposes a feature-oriented API. This gateway provides a small
OpenAI-compatible surface for clients that expect `/v1/models`,
`/v1/chat/completions`, and `/v1/images/generations`.

## Run

Use the published container image:

```sh
docker run --rm -p 5001:5001 ghcr.io/abd-enterprises/one-min-ai-gateway:latest
```

Or build locally with Docker Compose:

```sh
docker compose up -d --build
```

The gateway listens at:

```text
http://localhost:5001/v1
```

Clients pass the 1min.ai API key as an OpenAI-style bearer token. The
gateway does not store API keys.

Useful environment variables:

- `PORT`: listen port inside the container, default `5001`
- `HOST`: listen host, default `0.0.0.0`
- `CATALOG_TTL_SECONDS`: model catalog cache TTL, default `300`
- `MAX_IMAGE_BYTES`: maximum image upload/fetch payload, default `10485760`
- `CORS_ALLOW_ORIGIN`: CORS origin value, default `*`

## Plain Python

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e .
python server.py
```

## OpenCode

Example provider config:

```jsonc
{
  "provider": {
    "1min-ai": {
      "name": "1min.ai Gateway",
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "baseURL": "http://localhost:5001/v1"
      },
      "models": {
        "gemini-2.5-flash": {
          "name": "Gemini 2.5 Flash"
        }
      }
    }
  }
}
```

Store the credential with OpenCode or pass it as the client API key.

## Endpoints

- `GET /healthz`
- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/images/generations`

## Tool Calling

1min.ai models do not consistently return native OpenAI `tool_calls`.
The gateway includes a best-effort compatibility shim for common
tool-call-shaped text patterns and converts those into OpenAI-compatible
`tool_calls`.

This is intentionally conservative. It should not be treated as a
guarantee of native tool calling support from every model.

## Security

- API keys are read from request `Authorization: Bearer ...` headers.
- API keys are not written to disk.
- Prompts and keys are not logged by default.

## Image Publishing

Pushes to `main` publish `ghcr.io/abd-enterprises/one-min-ai-gateway:latest`
and a commit-SHA tag.

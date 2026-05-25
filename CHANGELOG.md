# Changelog

## 0.1.1

- Hardened image fetch path against private-network/localhost hosts.
- Rejected invalid chat payloads (non-array `messages`, malformed message items) with
  4xx errors.
- Improved streaming response behavior to emit SSE chunks incrementally instead of
  buffering full responses.
- Guarded model catalog fetch failures so gateway endpoints return gracefully on
  upstream data errors.

## 0.1.0

- Initial public release.
- OpenAI-compatible `/v1/models`, `/v1/chat/completions`, and
  `/v1/images/generations` endpoints for 1min.ai.
- Multi-architecture GHCR image publishing for `linux/amd64` and
  `linux/arm64`.

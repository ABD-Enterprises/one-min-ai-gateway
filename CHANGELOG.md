# Changelog

## Unreleased

- [INTERNAL] Regenerate the fleet-core block in `AGENTS.md` to the current standard.
- [INTERNAL] Refresh the generated fleet core; preserve repository-specific instructions.
- [INTERNAL] CI hygiene: both `ci.yml` jobs have a `timeout-minutes` sized from their recorded run times, a superseded pull-request run is cancelled (push and tag runs never are), and the runner fallback is the hosted label the repository variable already holds instead of a self-hosted ARM64 pool that a public repository cannot use.

- [INTERNAL] Route CI jobs to the organization's self-hosted Linux runners
  (`LINUX_RUNNER_LABELS`) and stop persisting checkout credentials.
- [INTERNAL] Adopt the fleet agent-file standard: `AGENTS.md` with the shared core and
  repository rules, and a `CLAUDE.md` that only imports it.

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

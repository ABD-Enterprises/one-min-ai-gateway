# Agent instructions: one-min-ai-gateway

<!-- fleet-core:begin (generated: edit the fleet source, not this block) -->
## Fleet core

Applies to new work after a repository adopts this baseline; do not retroactively invalidate in-flight work under its existing contract. It is generated from one source; repository-specific rules go outside the markers.

### Evidence
- Read live state before stating it: fetch the remote, read the default branch, run the command. A number or an "X is missing" taken from a doc or a stale checkout is a claim to verify. A figure in a doc carries its date and how it was read.
- Find the root cause before proposing a remedy. For an unreachable or hung host, check its network interface and the previous boot's log before blaming memory.
- Give one account of a fact. If two places disagree, fix or flag one.
- Say plainly what you did not verify.

### Changes
- One bounded task per change request. Stay in scope: no drive-by edits and no agent scratch files committed.
- Agent-authored code changes follow SureForge: one bounded work contract, supervised run and validation, independent review, then delivery. The operator may invoke a headless coder adapter; the interactive editor need not be the process coder. An unsupported route remains blocked; do not silently bypass it.
- An exception requires an explicit dated repository-specific rule outside this block naming its scope, reason, validation and delivery route. Limit exceptions to non-code work, read-only mirrors or archived repositories, and bounded pilot restrictions. An exception never relaxes review, protection or an explicit run contract; preserve stricter rules, including human-start requirements.
- Run the repository's validation (named below) before pushing. Inside a supervised run, its contract and delivery process govern commits and publication. For a permitted exception, commit, push a branch (never the default branch) and open the change request yourself within the limits below.
- Generated-policy checks establish instruction consistency; they do not establish runtime enforcement or OS confinement.
- A change request merges when a fresh-context review of the exact head has no unresolved P0 or P1 findings and every required check is green. A new commit needs a new review; a clean automatic merge of the base branch keeps the review.
- At most three open non-draft change requests per repository. While the fleet backlog check reports a backlog, finish and land existing work and start nothing new.
- Fix a finding that takes minutes in the current change; fold the rest into an existing tracking issue. A session closes at least as many issues as it opens on its own initiative; tickets the owner asks for in chat are separate.

### Safety
- Never print, log or commit tokens, passwords or keys. Use the credential helper the repository names.
- One writer per checkout: separate worktrees for separate writers. Do not force-push, rebase or delete a branch another session may own.
- Private repositories run CI on self-hosted runners only. A job that must not share a host (for example signing) runs on a dedicated self-hosted runner group, never on a GitHub-hosted runner without the owner's approval.
- Ask the owner only for a step no agent can do or for a spend or legal commitment; decide and record everything else.

### Layout
- AGENTS.md is the canonical agent file; where a CLAUDE.md exists it only imports it. Keep this file under 200 lines.
- Name this repository's validation command, merge rule and changelog rule outside the markers. Rules kept outside the repository are not visible here: if a task seems to need one, ask rather than guess.
- Rules any adopter needs live in SureForge and in this core; rules that name a machine, account or model live in the operator's own configuration repository, from which each tool's settings are meant to be generated so every agent on every machine follows the same rules.
- Shared skills are installed per machine from the fleet skills hub. Name the ones this repository expects below.

### Forge: GitHub
- Prefer REST (`gh api repos/OWNER/REPO/...`) to GraphQL for single reads: the rate-limit pools are shared by every session on the account.
- Required checks and review rules are branch protection or rulesets; read them with `gh api`. Review-thread resolution needs GraphQL.
<!-- fleet-core:end -->

## Repository-specific

- Public repository: AGENTS.md is world-readable, and so is anything an agent writes into this repository, its pull requests and its CI logs. Keep customer, account and internal-host names, keys and private paths out of every file, comment and commit message.
- What it is: an OpenAI-compatible gateway in front of the 1min.ai API (`GET /healthz`, `GET /v1/models`, `POST /v1/chat/completions`, `POST /v1/images/generations`), one Flask app served by Waitress (README; `server.py`, `main()`).
- Layout: all code is in `server.py` (one module, about 1,500 lines); tests are in `tests/test_server.py`; `Dockerfile` and `docker-compose.yml` build the image; `bin/setup` and `bin/validate` are developer helpers; `contract/` and `internal/operator-notes/` are leftovers of the retired ORC tooling (do not extend them).
- Validation (`.github/workflows/ci.yml`, job `test`; `bin/validate` runs the same four steps): `ruff check . && ruff format --check . && mypy . && pytest` after `python -m pip install -e ".[test]"`. The suite uses mocks, runs in about a second and needs no key. Use the versions `pyproject.toml` pins (ruff below 0.16): a newer ruff reports rules CI never runs, and a global ruff 0.17 reports 17 findings on a clean tree. Prefer a throwaway virtualenv outside the repository over the global tools.
- Merge: the fleet core's merge rule applies. GitHub enforces the organization ruleset "ABD default branch baseline" (no deletion or force push on `main`); branch protection on `main` requires no status checks and zero approving reviews (read 2026-10-21), so the independent review and a green `CI` run are the gate, not GitHub. All three merge methods are enabled; use squash.
- Changelog: `CHANGELOG.md` has an `## Unreleased` section; add one line there with a label from the pull request template (`[FEATURE]`, `[FIX]`, `[INTERNAL]`, `[SECURITY]`, `[BREAKING]`). The template is a leftover of the ORC adoption; the labels are still the ones the file uses. No CI check enforces it (the only workflow is `ci.yml`).
- Deploy on merge: a push to `main` (and a `v*` tag) makes the `publish-image` job build and push `ghcr.io/abd-enterprises/one-min-ai-gateway` (`latest`, a SHA tag, semver tags; `linux/amd64` and `linux/arm64`) to the public registry. Every merge is a release. Do not push a tag or merge an unreviewed head.
- CI runners: this repository is public, so it uses GitHub-hosted runners by the fleet rule. The repository variable `LINUX_RUNNER_LABELS` is `["ubuntu-latest"]` (read 2026-10-21), which overrides the organization's self-hosted value (visible only to private repositories). `ci.yml` falls back to `["self-hosted","Linux","ARM64","docker"]` if the variable is ever deleted; do not delete it, because public pull requests must not run on operator hardware.
- Secrets and keys: the gateway holds no key of its own. It takes the caller's `Authorization: Bearer` token and forwards it to the upstream as the `API-KEY` header (`bearer_key()`, `chat_completions`). The README says prompts and keys are not logged by default; the code logs request method, path, status and timing, model-catalog warnings and upstream error text, so do not add logging of request bodies, headers or keys. Never put a real 1min.ai key in a test, fixture, example or `.env`; tests use fake values and mocks. Never run the server against the real upstream, or call `api.1min.ai`, unless asked.
- Config (`server.py`, `Config`): configuration comes from process environment variables only; nothing loads a `.env` file (`docker compose` reads `.env` only for the `ONE_MIN_GATEWAY_PORT` substitution, and `.env` is git-ignored). Names only when checking: `env | cut -d= -f1 | grep -E 'ONE_MIN|GATEWAY|PROPAGATE|CORS'`, never print values.
- Defaults that widen exposure: `HOST` is `0.0.0.0`, `CORS_ALLOW_ORIGIN` is `*`, and there is no inbound authentication. `ONE_MIN_API_BASE_URL` decides where callers' keys are sent, so changing it to a host you do not control hands over every key. `GATEWAY_VERIFY_SSL=false` switches off certificate checking for upstream calls (local tests only). `PROPAGATE_HEADERS` copies the named request headers to the upstream. Do not change these defaults, or add `Authorization`-like names to `PROPAGATE_HEADERS`, without a reviewed reason.
- Image fetching: image URLs in chat requests are fetched by the server; it rejects loopback and private addresses and re-checks the resolved address (`server.py`, hostname validation near line 707). Weakening or removing that check is a security change; keep its tests (`tests/test_server.py`).
- Install and run hazards: `bin/setup` creates `.venv`, upgrades pip and installs from the network, then runs `bin/validate`; run it only when asked. `docker compose up -d --build` starts a container that restarts on boot (`restart: unless-stopped`) and publishes port 5001 on all interfaces; run it only when asked and stop it afterwards. There are no install-time hooks (no postinstall, prepare or husky).
- Skills: this repository expects no hub skills.

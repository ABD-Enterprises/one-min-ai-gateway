# ORC AI Adapter (Codex)

<!-- BEGIN ORC-STANDARDS LOCAL ADAPTER -->

This repo uses ORC: a ticket-driven coding loop that runs low-friction by default.

The unit of work is an **ai-task contract** (scope · done_when · validation · evidence) — that contract **is the spec** ORC satisfies. Everything below only sets *how strictly* it's enforced.

Posture — two modes: vibe (unlocked, you drive) and enterprise (org-floor-locked compliance):

- ORC's operator surface is **two modes** — strictness is expressed through your ai-task contract's `validation` + the mode (warn vs block), not by hand-setting dials. **vibe** (default) is genuinely low-friction: the scope, design, and capture gates do not block (capture still RECORDS metrics — it warns instead of blocking), validation runs on the host by default, and there is no claim-lease ceremony. **enterprise** is the locked compliance mode — full rigor + containment + the additive Attestation axis — pinned by the org floor: you can raise above it, never below, and `orc posture` prints the active floor. Switch with `orc posture <vibe|enterprise>`.
- **Attestation** gates compliance overhead (metrics capture, required evidence, multi-scanner cadence, audit-log retention, control coverage). Every gate is OFF in vibe, inert below its threshold, and advisory-first — opting into enterprise is what turns enforcement on. It never substitutes for the containment net. Pin it fleet-wide via the org floor.
- **Internal engine** (not an operator surface): the `hardened`/`regulated` postures and the raw O/R/C/A dials still *resolve* for back-compat, but you don't set them by hand — the **mode + your contract's `validation`** express strictness. The engine never changes who authors the diff, and never lowers GitHub's gates: branch protection, required checks, CodeQL/secret-scanning/push-protection, and org-floor policy stay in force in every mode.

Division of labor (Capability + Router, not a dial):

- Which agent authors the diff is a Capability — the configured coding backend (`.ai/config.json#continuity.model_provider`). The orchestrating/planning agent plans, grooms, reviews, and drives the board; the router delegates implementation to the backend through the loop. Hand-author trivial or mechanical changes directly when spinning up the backend is not worth the overhead.
- O = who merges / how unattended; R = how hard the work is verified (the scope/design/capture gates); C = how contained the coder is (strict claim-leases and related containment policy).
- Metrics are always recorded — `orc metrics` (cost/effort/routing) is a primary product — but the capture check is warn-only at vibe and enforced at hardened.

Source of truth:

- Board and provider: `.ai/config.json`
- Task state: external ticket board, not repo markdown
- Runtime CLI: `orc` on your PATH — this thin-adopted repo has no tracked bin/orc shim, so the global ORC launcher drives the loop

Windows shells:

- Use `orc <verb>` (the launcher on PATH); this thin-adopted repo has no `bin/orc` shim. In PowerShell or `cmd.exe`, `orc <verb>` works directly; from a full ORC engine checkout you can also run `node tools/orc/cli.mjs <verb>`.

Startup:

- If the branch contains a ticket id, run `orc current`. On `main` / `master` or with no ticket id, run `orc next`. For new work with no ticket, run `orc plan "<title>"`.
- Confirm a coding backend is available before relying on the loop to implement; otherwise hand-author the change or provision a backend — do not silently treat hand-authoring as the configured-backend path.
- Read ticket comments with `orc comments` and diffs with `orc diff` (lockfiles / generated / vendor stripped). Never re-fetch the raw thread or raw diff into the agent context.
- Search before broad reads: use `rg` or targeted queries to locate the exact symbol/config/evidence, and read only the surrounding lines you need.

Hard rules:

- AI task state lives on the external board only. Do not use `docs/roadmap`, `state/`, `work.json`, `state.json`, `markdown.json`, or markdown task lists.
- Canonical states: `ready_for_work` = unclaimed impl; `in_development` = active impl; `ready_for_local_testing` = cloud-completed handoff; `in_local_testing` = local-validation. Cloud agents may transition to `ready_for_local_testing`; local machines pick up with `orc validate-next`.
- Cloud/container agents run advisory `validation.cloud_preflight` checks only. Do not open a PR or transition to `in_pr_review` until local validation has passed. Production deploys stay on protected CI or trusted local runners.
- Local validation mirrors CI-required flags as closely as practical; CI failures override local assumptions. `orc validate` base-freshness failures are blockers — rebase onto the named target and rerun before pushing.
- Run local validation before pushing; inspect failed check logs; rerun CI only for concrete infra/cancellation/flaky-test reasons. When a self-hosted runner is configured, prefer it for CI-parity feedback before pushing (advisory like other local validation).
- Same-repo concurrency is narrow: run ONE free-running session per repo, or use `orc parallel` for sanctioned same-repo fanout.
- Blocked PRs are first-class work. Before taking new `ready_for_work`, inspect owned open PRs and drain red/dirty/blocked ones (security/required CI first, then stale base, review/size blockers, metadata gates, dependency queues). Do not stack feature commits onto a `size:xl` / `needs-independent-review` branch.
- Before editing any source file, search the issue tracker for the filename and the pattern you are about to change; coordinate on overlaps.
- Enforce zero bad churn: keep edits scoped to the root cause, preserve the touched file's style, avoid drive-by formatting/import sorting/public API renames, and do not commit scratch harnesses, IDE dotfiles, or agent-specific utility scripts.
- Treat push as remote verification, not iterative debugging: run the ticket's `validation.local` commands before the first push; if CI fails, reproduce locally before another push.
- Use host-scoped author email aliases for agent commits when available, and include `Co-Authored-By: <Agent> (<host>) ...` trailers.
- Run configured local-first reviews before CI spend when `.ai/config.json#local_review` declares them. Track actionable findings in GitHub Issues, not markdown logs.
- In-session subagents extend hands, not leases: they may search, read, inspect, summarize, classify, and report — they must NOT claim/transition tickets, add evidence, push, open/comment/merge PRs, or mutate provider state, and must NOT spawn further subagents. Close completed subagents immediately after consuming their results; completed subagents still count against runtime pools until closed, so a "subagent pool full" warning is usually hygiene, not repo state.
- Before local validation, pre-push, or other expensive milestones, respect the board-state heartbeat; stop if the ticket is blocked, reassigned, or no longer in the active state for this session.
- Do not commit local lease/controller/planner/handoff state files. `.ai/` is local-only; only repos that run their own board (ORC itself) track `.ai/config.json`, while adopted repos keep it untracked and bootstrap it via `orc adopt`. This adapter is tracked so fresh clones discover the ORC contract; repo-specific guidance lives outside the managed block (`orc adopt --force` preserves it).
- "Get latest" means update this repo only: `git fetch origin --prune && git pull --ff-only`.
- Secret-resolution commands run UNSANDBOXED. Any `.ai/secrets.json` `exec:` source — or any command that fetches a secret from a local secret manager, agent, keychain, or socket (whatever you use: `pass`, `gopass`, `vault`, a cloud provider's secrets CLI, an OS keychain, 1Password's `op`, …) — MUST run with the agent Bash sandbox disabled. The sandbox blocks the local socket/agent these tools rely on, so they fail misleadingly (auth timeouts, "not signed in", or hangs) even when correctly configured and unlocked. That is the sandbox, NOT a real auth failure — do not loop or ask the operator to re-authenticate; re-run unsandboxed. Only if the unsandboxed command still errors does an actual credential problem apply. See `docs/credentials.md`.

<!-- END ORC-STANDARDS LOCAL ADAPTER -->

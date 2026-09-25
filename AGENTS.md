# ORC AI Adapter (Codex)

<!-- BEGIN ORC-STANDARDS LOCAL ADAPTER -->

This repo uses sure-forge (formerly ORC): a ticket-driven coding loop that runs low-friction by default.

The unit of work is an **ai-task contract** (scope · done_when · validation · evidence) — that contract **is the spec** sure-forge satisfies. Everything below only sets *how strictly* it's enforced.

Posture — two modes: vibe (unlocked, you drive) and enterprise (org-floor-locked compliance):

- sure-forge's operator surface is **two modes** — strictness is expressed through your ai-task contract's `validation` + the mode, not by hand-setting legacy strictness keys. **vibe** (default) is genuinely low-friction: the scope, design, and capture gates do not block, validation runs on the host by default, and there is no claim-lease ceremony. **enterprise** is the locked compliance mode pinned by the org floor: stricter validation, containment, and evidence requirements can block, and `orc posture` prints the active floor. Switch with `orc posture <vibe|enterprise>`.
- Enterprise carries the compliance-only extras your organization requires, including metrics capture, required evidence, scanner cadence, audit-log retention, and control coverage. Those requirements stay advisory until the active mode or floor makes them block.

Division of labor (Capability + Router):

- Which agent authors the diff is a Capability — the configured coding backend (`.ai/config.json#continuity.model_provider`). The orchestrating/planning agent plans, grooms, reviews, and drives the board; the router delegates implementation to the backend through the loop. Hand-author trivial or mechanical changes directly when spinning up the backend is not worth the overhead.
- Metrics are always recorded — `orc metrics` (cost/effort/routing) is a primary product — but missing capture is advisory at vibe and can block in enterprise when the active policy requires it.

Source of truth:

- Board and provider: `.ai/config.json`
- Task state: external ticket board, not repo markdown
- Runtime CLI: `orc` on your PATH — this thin-adopted repo has no tracked bin/orc shim, so the global ORC launcher drives the loop

Windows shells:

- Use `orc <verb>` (the launcher on PATH); this thin-adopted repo has no `bin/orc` shim. In PowerShell or `cmd.exe`, `orc <verb>` works directly; from a full ORC engine checkout you can also run `node tools/orc/cli.mjs <verb>`.

Startup:

- If the branch contains a ticket id, run `orc current`. On `main` / `master` or with no ticket id, run `orc next`. For new work with no ticket, run `orc plan "<title>"`.
- Sanctioned filing/grooming path: use `orc plan "<title>"` to file new repo work and the `refine-*` workflow to groom it. Do not open agent-authored implementation tickets with `gh issue create`, because that bypasses the ai-task contract and the `tier:` / `defect_origin:` labels sure-forge expects.
- Recovery after `gh issue create`: keep the issue, run `orc refine-route --apply` to adopt any missing `ai/*` state, then finish the contract + `tier:` / `defect_origin:` labels through the `refine-*` workflow before any coder claims it. Human hand-filed issues remain allowed; this recovery step is only for agent-filed bypasses.
- Queue semantics: pinned ready tickets pull first (max 3, GitHub-enforced).
- Everything else is oldest-first, so promotion order is priority.
- Confirm a coding backend is available before relying on the loop to implement; otherwise hand-author the change or provision a backend — do not silently treat hand-authoring as the configured-backend path.
- Read ticket comments with `orc comments` and diffs with `orc diff` (lockfiles / generated / vendor stripped). Never re-fetch the raw thread or raw diff into the agent context.
- Every autonomous batch ends with the standard records-derived report via `orc batch close`; set `.ai/config.json#continuity.handoff_anchor` to post that report to a fixed issue, or leave it unset for print-only.
- Search before broad reads: use `rg` or targeted queries to locate the exact symbol/config/evidence, and read only the surrounding lines you need.
- For multiple related read-only GitHub lookups, prefer one bounded GraphQL query with aliases over repeated one-endpoint-at-a-time calls when that reduces round trips. Request only decision-relevant fields, set explicit pagination limits on every connection, record `rateLimit { cost remaining resetAt }` for batched investigations, and reuse the result within the run. Do not replace focused calls with oversized queries or unbounded graph traversal. Fall back to REST for one-off lookups, logs or artifacts, unavailable GraphQL surfaces, and mutations where REST has clearer idempotency or failure semantics.

Hard rules:

- AI task state lives on the external board only. Do not use `docs/roadmap`, `state/`, `work.json`, `state.json`, `markdown.json`, or markdown task lists.
- Canonical states: `ready_for_work` = unclaimed impl; `in_development` = active impl; `ready_for_local_testing` = cloud-completed handoff; `in_local_testing` = local-validation. Cloud agents may transition to `ready_for_local_testing`; local machines pick up with `orc validate-next`.
- Cloud/container agents run advisory `validation.cloud_preflight` checks only. Do not open a PR or transition to `in_pr_review` until local validation has passed. Production deploys stay on protected CI or trusted local runners.
- Local validation mirrors CI-required flags as closely as practical; CI failures override local assumptions. `orc validate` base-freshness failures are blockers — rebase onto the named target and rerun before pushing.
- Run local validation before pushing; inspect failed check logs; rerun CI only for concrete infra/cancellation/flaky-test reasons. When a self-hosted runner is configured, prefer it for CI-parity feedback before pushing (advisory like other local validation).
- Same-repo concurrency is narrow: run ONE free-running session per repo, or use `orc parallel` for sanctioned same-repo fanout.
- Blocked PRs are first-class work. Before taking new `ready_for_work`, inspect owned open PRs and drain red/dirty/blocked ones (security/required CI first, then stale base, review/size blockers, metadata gates, dependency queues). Do not stack feature commits onto a `size:xl` / `needs-independent-review` branch.
- Before editing any source file, search the issue tracker for the filename and the pattern you are about to change; coordinate on overlaps.
- **Consolidate; do not accrete.** When evidence shows a shared invariant, duplicate implementation, repeated failure shape, or high-fan-in behavior, identify the invariant and inspect sibling definitions and consumers before coding the fix. Prefer the smallest complete failure-class fix at the authoritative producer, shared predicate, state transition, or existing chokepoint over patching one consumer. Purely local or mechanical fixes do not require an exhaustive repository audit. If the complete class fix needs files outside approved scope, stop, record the incomplete class, and file a bounded follow-up instead of broadening the current PR or claiming the class is closed.
- Enforce zero bad churn: keep edits scoped to the root cause, preserve the touched file's style, avoid drive-by formatting/import sorting/public API renames, and do not commit scratch harnesses, IDE dotfiles, or agent-specific utility scripts.
- Treat push as remote verification, not iterative debugging: run the ticket's `validation.local` commands before the first push; if CI fails, reproduce locally before another push.
- Use host-scoped author email aliases for agent commits when available, and include `Co-Authored-By: <Agent> (<host>) ...` trailers.
- Run configured local-first reviews before CI spend when `.ai/config.json#local_review` declares them. Track actionable findings in GitHub Issues, not markdown logs.
- In-session subagents extend hands, not leases: they may search, read, inspect, summarize, classify, and report — they must NOT claim/transition tickets, add evidence, push, open/comment/merge PRs, or mutate provider state, and must NOT spawn further subagents. Close completed subagents immediately after consuming their results; completed subagents still count against runtime pools until closed, so a "subagent pool full" warning is usually hygiene, not repo state.
- Before local validation, pre-push, or other expensive milestones, respect the board-state heartbeat; stop if the ticket is blocked, reassigned, or no longer in the active state for this session.
- Do not commit local lease/controller/planner/handoff state files. `.ai/` is local-only; only repos that run their own board (sure-forge itself) track `.ai/config.json`, while adopted repos keep it untracked and bootstrap it via `orc adopt`. This adapter is tracked so fresh clones discover the sure-forge contract; repo-specific guidance lives outside the managed block (`orc adopt --force` preserves it).
- "Get latest" means update this repo only: `git fetch origin --prune && git pull --ff-only`.
- Secret-resolution commands run UNSANDBOXED. Any `.ai/secrets.json` `exec:` source — or any command that fetches a secret from a local secret manager, agent, keychain, or socket (whatever you use: `pass`, `gopass`, `vault`, a cloud provider's secrets CLI, an OS keychain, 1Password's `op`, …) — MUST run with the agent Bash sandbox disabled. The sandbox blocks the local socket/agent these tools rely on, so they fail misleadingly (auth timeouts, "not signed in", or hangs) even when correctly configured and unlocked. That is the sandbox, NOT a real auth failure — do not loop or ask the operator to re-authenticate; re-run unsandboxed. Only if the unsandboxed command still errors does an actual credential problem apply. See `docs/credentials.md`.

<!-- END ORC-STANDARDS LOCAL ADAPTER -->

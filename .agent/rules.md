# ORC AI Adapter (Antigravity)

<!-- BEGIN ORC-STANDARDS LOCAL ADAPTER -->

This repo uses ORC's ticket-driven autonomous coding loop.

Division of labor (Capability + Router, not a dial):

- Which agent authors the diff is a Capability — the configured coding backend (`.ai/config.json#continuity.model_provider`; the toolchain catalog's "Default coding agent") — resolved by the always-on router, not by a dial. The orchestrating/planning agent plans, grooms, reviews, and drives the board; when a coding backend is configured the router delegates implementation to it through the loop. Hand-authoring is the un-orchestrated fallback (no backend available, or an explicit per-knob override), not the default when a backend exists.
- The O/R/C dials govern the risk posture around the work, never authorship: O = who merges / how unattended, R = how hard it is verified, C = how contained the coder is.
- The loop is the unit of execution; the router and effort/cost telemetry are always-on (lit even at vibe). `orc metrics` (cost/effort/routing) is a primary product, so implementation should flow through the loop to be captured.

Source of truth:

- Board and provider: `.ai/config.json`
- Task state: external ticket board, not repo markdown
- Runtime CLI: `bin/ai-pipeline`

Startup:

- If the branch contains a ticket id, run `bin/ai-pipeline current`. If on `main` / `master` or no ticket id, run `bin/ai-pipeline next` before implementing. If the operator is asking for new work and no ticket exists, run `bin/ai-pipeline plan "<title>"`.
- Before relying on the loop to implement, confirm a coding backend is available (`orc fleet-health` / the toolchain catalog — a Capability, not a dial). If none is configured, provision one from the manifest or proceed in un-orchestrated mode; do not silently treat hand-authoring as the configured-backend path.
- Read ticket comments with `ai-pipeline comments` (default: structured-metadata only; `--all` opts into full thread). Read diffs with `ai-pipeline diff` (lockfiles / generated / vendor stripped; 200KB cap). Never re-fetch raw thread or raw diff into the agent context.
- Search before broad reads: use `rg`, targeted provider queries, or deterministic CLI commands to locate the exact symbol, config, or ticket evidence before opening large files/directories. Read only the surrounding lines needed, and stop exploration once the next safe implementation step is clear.
- Treat `ai-pipeline claim` / `next` continuity notices as startup inputs.

Hard rules:

- AI task state lives on the external board only. Do not use `docs/roadmap`, `state/`, `work.json`, `state.json`, `markdown.json`, or markdown task lists.
- Canonical states: `ready_for_work` = unclaimed impl; `in_development` = active impl lease; `ready_for_local_testing` = cloud-completed handoff; `in_local_testing` = local-validation lease. Cloud agents may transition to `ready_for_local_testing`; local machines pick up with `ai-pipeline validate-next`.
- Cloud/container agents run advisory `validation.cloud_preflight` checks only. Do not open a PR or transition to `in_pr_review` until local validation has passed. Production deploys stay on protected CI or trusted local runners; cloud containers may only do preview/sandbox deploys unless the repo explicitly documents trusted-cloud.
- Local validation mirrors CI-required flags as closely as practical; CI failures override local assumptions. Validation scripts tolerate unset optional env vars under `set -u`. `ai-pipeline validate` base-freshness failures are blockers — rebase onto the named target and rerun before pushing.
- Run local validation before pushing; inspect failed check logs; rerun CI only for concrete infra/cancellation/flaky-test reasons.
- Supported same-repo concurrency is narrow: run ONE free-running session per repo, or use `ai-pipeline parallel` for sanctioned same-repo fanout, or work on non-overlapping repos. Two independent free-running sessions on one repo are unsupported until the fenced coordinator lands.
- Blocked PRs are first-class work. Before taking new `ready_for_work`, inspect owned open PRs in this repo; classify each red/dirty/blocked PR as `RED_CI_REQUIRED`, `SECURITY_REQUIRED`, `MERGE_CONFLICT_DIRTY`, `SIZE_REVIEW_BLOCK`, `REVIEW_THREAD_BLOCK`, `METADATA_GATE_BLOCK`, `WORKFLOW_SECONDARY_FAILURE`, or `DEPENDENCY_QUEUE`. Drain security/required CI first, then stale base, review/size blockers, metadata gates, workflow secondary failures, and clean dependency queues. Use `ai-pipeline review-comments --pr <number>` for review blockers. Do not stack more feature commits onto a `size:xl` / `needs-independent-review` branch; split/re-roll or get independent review.
- Before editing any source file, search the issue tracker for the filename and the pattern you are about to add or change; coordinate if an open issue is already refactoring that file or removing that pattern.
- Enforce zero bad churn: keep edits scoped to the ticket/root cause, preserve the touched file's established style, avoid drive-by formatting/import sorting/public API renames, and do not commit scratch harnesses, IDE dotfiles, or agent-specific utility scripts unless the ticket explicitly requires them.
- Treat push as remote verification, not iterative debugging: run the ticket's `validation.local` commands and cheap PR-essential/changelog validators before the first push whenever the repo provides them; if remote CI fails, inspect logs and reproduce locally before another push or rerun.
- Use host-scoped author email aliases for agent commits when available, and include `Co-Authored-By: <Agent> (<host>) ...` trailers.
- Run configured local-first reviews before CI spend when `.ai/config.json#local_review` declares them. Track actionable local-review findings in GitHub Issues, not markdown logs.
- In-session subagents extend hands, not leases: they may search, read, inspect, summarize, classify, and report — they must NOT claim/transition tickets, add evidence, push, open/comment/merge PRs, or mutate provider state. Subagents are leaf-level — they must NOT spawn further subagents; only the parent session orchestrates. Do not paste raw subagent transcripts into tickets, PRs, or commits; extract verified facts.
- Before local validation, pre-push, or other expensive milestones, respect the board-state heartbeat; stop if the ticket is blocked, reassigned, or no longer in the active state for this session.
- Do not commit local lease/controller/planner/handoff state files. `.ai/` is local-only. This adapter is tracked so fresh clones discover the ORC contract; repo-specific guidance lives outside the managed block (`ai-pipeline adopt --force` preserves it).
- "Get latest" means update this repo only: `git fetch origin --prune && git pull --ff-only`.

<!-- END ORC-STANDARDS LOCAL ADAPTER -->

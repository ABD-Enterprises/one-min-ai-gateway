# ORC AI Adapter (Claude)

<!-- BEGIN ORC-STANDARDS LOCAL ADAPTER -->

This repo uses ORC: a ticket-driven coding loop that runs low-friction by default.

Posture — vibe (default) and hardened (the switch):

- ORC has two postures. **vibe** (O0 R0 C0) is the default and is genuinely low-friction: the scope, design, and capture gates do not block (capture still RECORDS metrics — it warns instead of blocking), validation runs on the host by default, and there is no claim-lease ceremony. **hardened** (O0 R1 C1) is the opt-in switch — `orc posture hardened` — that turns governance on: scope/design/capture enforced (rigor) and strict claim-leases (containment). Validation still runs on the host by default; the network-denied container is an explicit opt-in via `validation.isolation: "container"` and is required for untrusted PR authors. Switch anytime with `orc posture <vibe|hardened>`; `.ai/config.json#governance.overrides` (the O/R/C axes) persists it.
- The O/R/C dials GOVERN this friction. They never change who authors the diff, and they never lower GitHub's gates — branch protection, required checks, CodeQL/secret-scanning/push-protection, and org-floor policy stay in force at every posture.

Division of labor (Capability + Router, not a dial):

- Which agent authors the diff is a Capability — the configured coding backend (`.ai/config.json#continuity.model_provider`). The orchestrating/planning agent plans, grooms, reviews, and drives the board; the router delegates implementation to the backend through the loop. Hand-author trivial or mechanical changes directly when spinning up the backend is not worth the overhead.
- O = who merges / how unattended; R = how hard the work is verified (the scope/design/capture gates); C = how contained the coder is (strict claim-leases and related containment policy).
- Metrics are always recorded — `orc metrics` (cost/effort/routing) is a primary product — but the capture check is warn-only at vibe and enforced at hardened.

Source of truth:

- Board and provider: `.ai/config.json`
- Task state: external ticket board, not repo markdown
- Runtime CLI: `bin/ai-pipeline`

Windows shells:

- In PowerShell or `cmd.exe`, use `node tools/orc/cli.mjs <verb>` or `bin\orc.cmd <verb>` instead of the extensionless `bin/ai-pipeline` / `bin/orc` bash scripts. Calling those scripts directly from PowerShell or `cmd.exe` opens the Windows app-picker instead of running ORC.
- The extensionless `bin/ai-pipeline` / `bin/orc` scripts are fine under Git-Bash.

Startup:

- If the branch contains a ticket id, run `bin/ai-pipeline current`. On `main` / `master` or with no ticket id, run `bin/ai-pipeline next`. For new work with no ticket, run `bin/ai-pipeline plan "<title>"`.
- Confirm a coding backend is available before relying on the loop to implement; otherwise hand-author the change or provision a backend — do not silently treat hand-authoring as the configured-backend path.
- Read ticket comments with `ai-pipeline comments` and diffs with `ai-pipeline diff` (lockfiles / generated / vendor stripped). Never re-fetch the raw thread or raw diff into the agent context.
- Search before broad reads: use `rg` or targeted queries to locate the exact symbol/config/evidence, and read only the surrounding lines you need.

Hard rules:

- AI task state lives on the external board only. Do not use `docs/roadmap`, `state/`, `work.json`, `state.json`, `markdown.json`, or markdown task lists.
- Canonical states: `ready_for_work` = unclaimed impl; `in_development` = active impl; `ready_for_local_testing` = cloud-completed handoff; `in_local_testing` = local-validation. Cloud agents may transition to `ready_for_local_testing`; local machines pick up with `ai-pipeline validate-next`.
- Cloud/container agents run advisory `validation.cloud_preflight` checks only. Do not open a PR or transition to `in_pr_review` until local validation has passed. Production deploys stay on protected CI or trusted local runners.
- Local validation mirrors CI-required flags as closely as practical; CI failures override local assumptions. `ai-pipeline validate` base-freshness failures are blockers — rebase onto the named target and rerun before pushing.
- Run local validation before pushing; inspect failed check logs; rerun CI only for concrete infra/cancellation/flaky-test reasons. When a self-hosted runner is configured, prefer it for CI-parity feedback before pushing (advisory like other local validation).
- Same-repo concurrency is narrow: run ONE free-running session per repo, or use `ai-pipeline parallel` for sanctioned same-repo fanout.
- Blocked PRs are first-class work. Before taking new `ready_for_work`, inspect owned open PRs and drain red/dirty/blocked ones (security/required CI first, then stale base, review/size blockers, metadata gates, dependency queues). Do not stack feature commits onto a `size:xl` / `needs-independent-review` branch.
- Before editing any source file, search the issue tracker for the filename and the pattern you are about to change; coordinate on overlaps.
- Enforce zero bad churn: keep edits scoped to the root cause, preserve the touched file's style, avoid drive-by formatting/import sorting/public API renames, and do not commit scratch harnesses, IDE dotfiles, or agent-specific utility scripts.
- Treat push as remote verification, not iterative debugging: run the ticket's `validation.local` commands before the first push; if CI fails, reproduce locally before another push.
- Use host-scoped author email aliases for agent commits when available, and include `Co-Authored-By: <Agent> (<host>) ...` trailers.
- Run configured local-first reviews before CI spend when `.ai/config.json#local_review` declares them. Track actionable findings in GitHub Issues, not markdown logs.
- In-session subagents extend hands, not leases: they may search, read, inspect, summarize, classify, and report — they must NOT claim/transition tickets, add evidence, push, open/comment/merge PRs, or mutate provider state, and must NOT spawn further subagents.
- Before local validation, pre-push, or other expensive milestones, respect the board-state heartbeat; stop if the ticket is blocked, reassigned, or no longer in the active state for this session.
- Do not commit local lease/controller/planner/handoff state files. `.ai/` is local-only (except the tracked `.ai/config.json`). This adapter is tracked so fresh clones discover the ORC contract; repo-specific guidance lives outside the managed block (`ai-pipeline adopt --force` preserves it).
- "Get latest" means update this repo only: `git fetch origin --prune && git pull --ff-only`.

<!-- END ORC-STANDARDS LOCAL ADAPTER -->

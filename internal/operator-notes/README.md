# Operator Notes

This directory stores operator-curated context for Planner runs.

Use one Markdown file per topic. Good notes explain durable operating context:
why this repo does something, patterns agents should preserve, and practices
agents should avoid.

Rules:

- Keep notes as prose written or approved by the operator.
- Do not store secrets, credentials, tokens, or machine-local paths here.
- Planner runs read these notes before refining tickets.
- Planner output cites the note that influenced each non-obvious decision.

Suggested files:

- onboarding.md
- release-process.md
- recurring-failure-modes.md

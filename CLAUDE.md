# RoboRecon Project Guidance

## Overview

RoboRecon is a payment reconciliation dashboard that closes the loop between a merchant ledger, Razorpay records, settlement arithmetic, and bank credits. The MVP is a deterministic benchmark and operations workspace, not a general accounting system.

## Stack

- **Backend:** Python 3.12+, FastAPI, SQLAlchemy async, Pydantic v2, PostgreSQL 16
- **Frontend:** React 19, TypeScript 5, Vite 8, TanStack Query/Table, shadcn/ui, Tailwind CSS v4
- **Infrastructure:** Docker Compose for offline PostgreSQL/API/Web; separate Vercel projects with Neon for hosting
- **Testing:** pytest and Ruff in the API container; Vitest, TypeScript, ESLint, and Vite build in the Web test container

## Structure

```text
apps/api/app/       FastAPI routes, models, deterministic engine, evaluation, adapters
apps/api/tests/     Backend tests and fixed benchmark helper
apps/web/src/       React operations workspace
apps/api/http/      REST Client judge-flow requests
scripts/            Container-only demo and verification entrypoints
```

## Domain Rules

- Store all monetary amounts as integer INR paise; never use floats for money.
- Use UUID primary keys and batch-scoped source records.
- Deterministic policy owns matching, scoring, hard gates, thresholds, evidence, and autonomous Match Links.
- Ground Truth is evaluation-only and must never enter matcher inputs, queries, scoring, or evidence.
- AI and Copilot are read-only, advisory, bounded, cited, and fail safe to deterministic fallback or review.
- Human approve/reject actions are terminal and append outcome-focused audit events.

## Deployment Rules

- `docker compose up` starts PostgreSQL, API, and Web only. The test-only `api-test` profile is opt-in.
- Hosted API deployments use a pooled Neon `DATABASE_URL`, `SERVERLESS=true`, and explicit `CORS_ORIGINS`.
- Keep provider keys and database credentials out of source and documentation.
- Use the existing Dockerfiles and container checks; do not install project dependencies on the host.

## Verification

```bash
npm run verify
```

Run focused container checks when iterating. The full API invocation has `pythonpath = tests` in `apps/api/pytest.ini` so the benchmark helper is importable without a shell workaround.

## Collaboration

Preserve unrelated worktree changes. Keep implementation commits scoped to the requested task.

## Agent skills

### Issue tracker

Issues and specs for this repo live as GitHub issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Triage uses the default canonical labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Domain docs use a single-context layout at the repo root. See `docs/agents/domain.md`.

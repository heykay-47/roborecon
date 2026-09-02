# RoboRecon

RoboRecon is a deterministic finance-operations control plane for closing the lifecycle between a merchant ledger, Razorpay activity, settlement arithmetic, and bank credits. It is designed to be judgeable in 90 seconds and safe when optional integrations are unavailable.

## 90-Second Judge Flow

Run this from a checkout with Docker available:

```bash
docker compose up --build -d
./scripts/demo-reset.sh
```

Then open <http://localhost:3000>:

1. **Overview:** confirm the seeded benchmark badge, match rate, precision, false positives, autonomous rate, runtime, and money totals.
2. **Runs:** open the latest completed run and inspect the two stage metrics, per-class metrics, and every acceptance gate.
3. **Exceptions:** open an unresolved case, inspect deterministic evidence and candidates, run the optional advisory investigation, then approve or reject one case.
4. **Audit:** confirm the reset, run, investigation, and terminal review events are linked to the batch and actor.
5. **Copilot:** ask the seeded settlement question and follow its typed source citations. Without an AI key it displays the deterministic fallback, not fabricated prose.

The same deterministic acceptance check can be run without the browser:

```bash
docker compose run --rm api-test python -m app.demo.acceptance
```

## Safety Boundary

The system has one authoritative path:

```text
Ledger + Razorpay + Settlement + Bank Credit
                |
                v
     deterministic two-stage policy
                |
                +--> autonomous Match Links
                +--> evidence-backed Exceptions
                |
                +--> read-only advisory AI and Copilot
```

The matcher owns normalization, candidate scoring, hard contradiction gates, thresholds, and autonomous resolution. AI receives bounded persisted evidence only. It cannot mutate records, create an autonomous Match Link, access hidden evaluation truth, or turn an outage into a false success. Provider and AI failures fall back to deterministic results and human review.

All money is integer INR paise. Ground Truth is stored separately for evaluation and is never read by matcher inputs, scoring, or evidence.

## Seeded Benchmark

The deterministic demo uses seed `razorrecon-v1` and contains:

- 120 merchant Ledger entries plus provider-only and malformed records.
- Exact identifiers, fee/GST arithmetic, date shifts, fuzzy references, duplicates, amount mismatches, missing Razorpay records, missing Settlements, missing Bank Credits, refunds, held/released amounts, and ambiguous candidates.
- A hidden Evaluation Case for each scenario, with per-class results and exception recall.
- A deterministic class-diverse investigation portfolio of five exceptions.

## Metrics

The UI and acceptance CLI use these definitions:

| Metric | Definition |
| --- | --- |
| Precision | Correct autonomous Match Links divided by all autonomous Match Links. |
| False positives | Autonomous Match Links that contradict Ground Truth. |
| Match rate | Correctly resolved matchable Evaluation Cases divided by all matchable Evaluation Cases. |
| Stage autonomy | Matchable cases closed autonomously at that reconciliation stage divided by matchable cases eligible for that stage. |
| End-to-end autonomy | Matchable cases whose complete required lifecycle is autonomous divided by all matchable cases. |
| Exception recall | Seeded non-matchable cases surfaced as the expected exception outcome divided by all non-matchable cases. |
| Money reconciled | INR gross value of correctly closed Ledger entries; Settlement net is reported separately. |
| Money unresolved | Ledger value without an accepted Match Link, including open and confirmed-no-match outcomes. |

Acceptance gates require 100% autonomous precision, zero false positives, at least 95% match rate, at least 90% strict end-to-end autonomy, at least 90% Stage A/Stage B/per-positive-class accuracy, 100% exception recall, and at most five seconds deterministic runtime.

## Local Development

The supported local path uses Docker Compose only:

```bash
cp .env.example .env
docker compose up --build -d
```

Services are PostgreSQL (`5432`), API (`8000`), and Web (`3000`). Health checks gate API startup on PostgreSQL and Web startup on the API. `api-test` is a test-only Compose profile and is not part of the normal running path.

Useful commands:

```bash
npm run verify
npm run demo
```

`npm run verify` runs the documented backend and frontend container checks. No host Python or Node installation is required.

The request examples in `apps/api/http/judge-flow.http` mirror the browser flow: health, demo reset, run, metrics, exceptions, transactions, audit, and optional Test Mode sync.

## Hosted Deployment

The supported low-cost hosted topology is separate Vercel projects rooted at `apps/web` and `apps/api`, backed by a pooled Neon connection. Configure `VITE_API_URL` on Web and `DATABASE_URL`, `SERVERLESS=true`, and `CORS_ORIGINS` on API. Never commit connection strings or provider keys.

See [deployment instructions](docs/DEPLOYMENT.md) for the exact Vercel configs, Neon asyncpg settings, bundle and duration limits, and the Cloud Run Docker fallback.

## Project Structure

```text
apps/api/          FastAPI API, deterministic engine, persistence, evaluation, AI adapters
apps/web/          React/Vite operations workspace
apps/api/http/     Judge-flow REST Client requests
scripts/           Container-only demo and verification entrypoints
docs/              Deployment and final acceptance handoff
docker-compose.yml Offline PostgreSQL, API, and Web orchestration
```

## Truthful Limitations

- Live Vercel, Neon, Razorpay, and AI credentials are not stored here; the offline demo and mocked outage paths are the reproducible acceptance baseline.
- Test Mode imports are source-only batches and do not support benchmark precision claims.
- Startup uses SQLAlchemy table creation and idempotent adjustments rather than a full migration tool.
- Some exception prioritization and filtering is intentionally in-memory for the fixed demo scale.
- The API's 60-second hosted function limit bounds long-running syncs and reconciliation runs.

## License

Portfolio project for demonstration and evaluation.

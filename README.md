# RoboRecon

RoboRecon is a deterministic finance operations workspace. It connects merchant ledger entries to Razorpay activity, settlement arithmetic, and bank credits. You can inspect the local demo in about 90 seconds, even when optional integrations are unavailable.

## 90-second judge flow

Run this from a checkout with Docker available:

```bash
docker compose up --build -d
./scripts/demo-reset.sh
```

Then open <http://localhost:3000>:

1. **Overview.** Check the seeded benchmark badge, match rate, precision, false positives, end-to-end autonomous resolution, runtime, and money totals.
2. **Runs.** Open the latest completed run. Check both stage metrics, the per-class metrics, and every acceptance gate. Select **Assess batch close** to generate the evidence-locked Batch Close Brief.
3. **Exceptions.** Open an unresolved case. Inspect its deterministic evidence and candidates, run the optional advisory investigation, then approve or reject the case.
4. **Audit.** Check that reset, run, investigation, and terminal review events link to the right batch and actor.
5. **Copilot.** Ask the seeded settlement question and follow its typed source citations. Without an AI key, Copilot shows the deterministic fallback instead of inventing an answer.

### Batch Close Brief

The Batch Close Brief is available on completed Run detail pages. **Ready** means the run has no Open Exceptions and no Money Unresolved. Any unresolved work produces **Review required**. The assessment reports deterministic full-run coverage separately from AI coverage, groups every Open Exception into cited themes, and states that `0 financial records changed`.

The provider is read-only and receives only a bounded run digest. `AI_MAX_BATCH_CLOSE_PROMPT_CHARS` sets the maximum provider input size. Invalid, incomplete, unavailable, or timed-out provider output produces a clearly labeled deterministic fallback. A later terminal Review Decision marks the latest brief stale; select **Reassess batch close** to create a new append-only assessment.

## Try it in the browser

The seeded offline judge flow runs in the local web application at <http://localhost:3000>.

Run the same deterministic acceptance check without the browser:

```bash
docker compose run --rm api-test python -m app.demo.acceptance
```

## Safety boundary

RoboRecon reconciles records through this path:

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

The deterministic matcher handles normalization, candidate scoring, contradiction gates, thresholds, and autonomous resolution. AI receives only bounded persisted evidence. It cannot mutate records, create an autonomous Match Link, access hidden evaluation truth, or turn an outage into a success. Provider and AI failures return deterministic results for human review.

All monetary values use integer INR paise. Ground Truth is stored separately for evaluation and is never read by matcher inputs, scoring, or evidence.

## Seeded benchmark

The deterministic demo uses seed `roborecon-v1`. It includes:

- 120 merchant Ledger entries, plus provider-only and malformed records.
- Exact identifiers, fee/GST arithmetic, date shifts, fuzzy references, duplicates, amount mismatches, missing Razorpay records, missing Settlements, missing Bank Credits, refunds, held and released amounts, and ambiguous candidates.
- One hidden Evaluation Case for each scenario, with per-class results and exception recall.
- Five exceptions selected across the investigation classes.

## Metrics

The UI and acceptance CLI calculate these metrics only for the fixed synthetic demo, where hidden Ground Truth is available. A 100% result describes this finite benchmark, not production accuracy, a forecast, or a guarantee. Imported Razorpay batches do not receive truth-based accuracy metrics.

| Metric | Definition |
| --- | --- |
| Precision | Correct autonomous Match Links divided by all autonomous Match Links. |
| False positives | Autonomous Match Links that contradict Ground Truth. |
| Match rate | Correctly resolved matchable Evaluation Cases divided by all matchable Evaluation Cases. |
| Stage autonomy | Matchable cases closed autonomously at that reconciliation stage divided by matchable cases eligible for that stage. |
| End-to-end autonomy | Matchable cases whose complete required lifecycle is autonomous divided by all matchable cases. |
| Exception recall | Seeded non-matchable cases surfaced as the expected exception outcome divided by all non-matchable cases. |
| Money reconciled | INR gross value of correctly closed Ledger entries. Settlement net is reported separately. |
| Money unresolved | Ledger value without an accepted Match Link, including open and confirmed-no-match outcomes. |

The seeded benchmark requires at least 98% autonomous-link precision, no more than eight incorrect selected links, at least 90% match rate, at least 90% strict end-to-end autonomy, at least 90% Stage A, Stage B, and positive-class accuracy, 100% exception recall, and deterministic runtime of no more than five seconds. Crossed-reference noise gives the matcher real errors to handle instead of a perfect score. These are test gates, not production performance claims.

## Local development

Use Docker Compose for local development:

```bash
cp .env.example .env
docker compose up --build -d
```

The stack includes PostgreSQL (`5432`), the API (`8000`), and the Web app (`3000`). Health checks start the API after PostgreSQL is ready and start the Web app after the API is ready. `api-test` is a test-only Compose profile and is not part of the normal running stack.

Useful commands:

```bash
npm run verify
npm run demo
```

`npm run verify` runs the backend and frontend checks in containers. You do not need Python or Node installed on the host.

The request examples in `apps/api/http/judge-flow.http` cover health, demo reset, runs, Batch Close Brief assessment, metrics, exceptions, transactions, audit, and optional Test Mode sync.

### Razorpay Test Mode sync

The connector sends read-only `GET` requests to Razorpay for orders, payments, refunds, settlements, and settlement reconciliation details. It stores each response in a separate, unscored source batch and never writes to Razorpay.

1. Generate Test Mode API keys in the Razorpay Dashboard under `Account & Settings -> API Keys`.
2. Create the ignored local environment file and fill in the two Razorpay fields:

```bash
cp .env.example .env
```

```text
RAZORPAY_KEY_ID=rzp_test_...
RAZORPAY_KEY_SECRET=...
```

3. Start or restart the API with Docker Compose:

```bash
docker compose up --build -d postgres api web
```

4. Trigger a sync and inspect the returned `batchId` and `sourceCounts`:

```bash
curl --fail --silent --show-error --request POST http://localhost:8000/razorpay/sync
```

Use Test Mode keys only while developing. If either key is absent, the endpoint uses its fixed local demo connector so the offline flow remains reproducible. Never commit `.env` or share the secret.

## Hosted deployment

The supported low-cost hosted setup uses separate Vercel projects rooted at `apps/web` and `apps/api`, backed by a pooled Neon connection. Configure `VITE_API_URL` on Web and `DATABASE_URL`, `SERVERLESS=true`, and `CORS_ORIGINS` on the API. Never commit connection strings or provider keys.

For a guided setup that opens the provider dashboards, captures Neon and Razorpay Test Mode values, and walks through both Vercel deployments, run:

```bash
./scripts/host-setup.sh
```

The wizard keeps hosted values in the ignored `.env.hosted.local` file and leaves the local Compose `.env` unchanged.

## Project structure

```text
apps/api/          FastAPI API, deterministic engine, persistence, evaluation, AI adapters
apps/web/          React/Vite operations workspace
apps/api/http/     Judge-flow REST Client requests
scripts/           Container-only demo and verification entrypoints
docker-compose.yml PostgreSQL, API, and Web orchestration
```

## Truthful limitations

- Live Vercel, Neon, Razorpay, and AI credentials are not stored here. The offline demo and mocked outage paths are the reproducible acceptance baseline.
- Test Mode imports are source-only batches and do not support benchmark precision claims.
- Startup uses SQLAlchemy table creation and idempotent adjustments rather than a full migration tool.
- Some exception prioritization and filtering is intentionally in memory for the fixed demo scale.
- The API's 60-second hosted function limit bounds long-running syncs and reconciliation runs.

## License

Portfolio project for demonstration and evaluation.

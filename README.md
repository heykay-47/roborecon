# RoboRecon

RoboRecon is a deterministic finance-operations control plane for closing the lifecycle between a merchant ledger, Razorpay activity, settlement arithmetic, and bank credits. It is designed to be judgeable in 90 seconds and safe when optional integrations are unavailable.

## 90-Second Judge Flow

Run this from a checkout with Docker available:

```bash
docker compose up --build -d
./scripts/demo-reset.sh
```

Then open <http://localhost:3000>:

1. **Overview:** confirm the seeded benchmark badge, match rate, precision, false positives, end-to-end autonomous resolution, runtime, and money totals.
2. **Runs:** open the latest completed run and inspect the two stage metrics, per-class metrics, and every acceptance gate. Select **Assess batch close** to generate the evidence-locked Batch Close Brief.
3. **Exceptions:** open an unresolved case, inspect deterministic evidence and candidates, run the optional advisory investigation, then approve or reject one case.
4. **Audit:** confirm the reset, run, investigation, and terminal review events are linked to the batch and actor.
5. **Copilot:** ask the seeded settlement question and follow its typed source citations. Without an AI key it displays the deterministic fallback, not fabricated prose.

## Screenshots

The seeded offline judge flow is available from the running local web application at
<http://localhost:3000>.

### Batch Close Brief

The Batch Close Brief is available on completed Run detail pages. **Ready** means the run has no Open Exceptions and no Money Unresolved. Any unresolved work produces **Review required**. The assessment reports deterministic full-run coverage separately from AI coverage, groups every Open Exception into cited themes, and states that `0 financial records changed`.

The provider is read-only and receives only a bounded run digest. `AI_MAX_BATCH_CLOSE_PROMPT_CHARS` sets the maximum provider input size. Invalid, incomplete, unavailable, or timed-out provider output produces a clearly labeled deterministic fallback. A later terminal Review Decision marks the latest brief stale; select **Reassess batch close** to create a new append-only assessment.

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

The deterministic demo uses seed `roborecon-v1` and contains:

- 120 merchant Ledger entries plus provider-only and malformed records.
- Exact identifiers, fee/GST arithmetic, date shifts, fuzzy references, duplicates, amount mismatches, missing Razorpay records, missing Settlements, missing Bank Credits, refunds, held/released amounts, and ambiguous candidates.
- A hidden Evaluation Case for each scenario, with per-class results and exception recall.
- A deterministic class-diverse investigation portfolio of five exceptions.

## Metrics

The UI and acceptance CLI compute these metrics only for the fixed synthetic demo, where hidden Ground Truth is available. A 100% result means the deterministic matcher handled that finite benchmark; it is not a measured production accuracy rate, forecast, or guarantee. Imported Razorpay batches are not assigned truth-based accuracy metrics.

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

Seeded benchmark acceptance gates require at least 98% autonomous-link precision, no more than eight incorrect selected links, at least 90% match rate, at least 90% strict end-to-end autonomy, at least 90% Stage A/Stage B/per-positive-class accuracy, 100% exception recall, and at most five seconds deterministic runtime. The fixed data includes crossed-reference noise so the benchmark measures real deterministic errors instead of producing perfect scores. These are test gates, not production performance claims.

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

The request examples in `apps/api/http/judge-flow.http` cover health, demo reset, runs, Batch Close Brief assessment, metrics, exceptions, transactions, audit, and optional Test Mode sync.

### Razorpay Test Mode Sync

The connector makes read-only `GET` requests to Razorpay for orders, payments, refunds, settlements, and settlement reconciliation details. It stores the response as a separate, unscored source batch; it never writes to Razorpay.

1. Generate Test Mode API keys in Razorpay Dashboard under `Account & Settings -> API Keys`.
2. Create the ignored local environment file and fill only the two Razorpay fields:

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

4. Trigger one sync and inspect the returned `batchId` and `sourceCounts`:

```bash
curl --fail --silent --show-error --request POST http://localhost:8000/razorpay/sync
```

Use Test Mode keys only while developing. If either key is absent, the endpoint intentionally uses its fixed local demo connector instead, so the offline flow remains reproducible. Never commit `.env` or share the secret.

## Hosted Deployment

The supported low-cost hosted topology is separate Vercel projects rooted at `apps/web` and `apps/api`, backed by a pooled Neon connection. Configure `VITE_API_URL` on Web and `DATABASE_URL`, `SERVERLESS=true`, and `CORS_ORIGINS` on API. Never commit connection strings or provider keys.

## Project Structure

```text
apps/api/          FastAPI API, deterministic engine, persistence, evaluation, AI adapters
apps/web/          React/Vite operations workspace
apps/api/http/     Judge-flow REST Client requests
scripts/           Container-only demo and verification entrypoints
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

import asyncio
import json

from app.database import async_session
from app.demo.service import reset_demo
from app.evaluation.service import evaluate_run
from app.reconciliation.service import run_reconciliation


async def _run() -> None:
    async with async_session() as session:
        batch = await reset_demo(session)
        run = await run_reconciliation(session, batch.id)
        report = await evaluate_run(session, run.id)
        print(
            json.dumps(
                {
                    "runId": str(run.id),
                    "benchmarkAvailable": report.benchmark_available,
                    "precision": report.precision,
                    "falsePositives": report.false_positives,
                    "matchRate": report.match_rate,
                    "autonomousResolutionRate": report.autonomous_resolution_rate,
                    "durationMs": report.duration_ms,
                    "perClass": {
                        name: {
                            "matchRate": metrics.match_rate,
                            "precision": metrics.precision,
                        }
                        for name, metrics in report.per_class.items()
                    },
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    asyncio.run(_run())

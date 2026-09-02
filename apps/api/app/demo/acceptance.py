import asyncio
import json

from app.database import async_session
from app.demo.service import reset_demo
from app.evaluation.model import EvaluationReport
from app.evaluation.service import evaluate_run
from app.reconciliation.service import run_reconciliation


def acceptance_payload(report: EvaluationReport) -> dict[str, object]:
    assert report.stage_metrics is not None
    assert report.per_class is not None
    return {
        "benchmarkAvailable": report.benchmark_available,
        "precision": report.precision,
        "falsePositives": report.false_positives,
        "matchRate": report.match_rate,
        "stageAAutonomyRate": report.stage_metrics["ledger_to_razorpay"].autonomy_rate,
        "stageBAutonomyRate": report.stage_metrics["razorpay_to_settlement"].autonomy_rate,
        "endToEndAutonomyRate": report.end_to_end_autonomy_rate,
        "exceptionRecall": report.exception_recall,
        "durationMs": report.duration_ms,
        "perClass": {
            name: {"accuracy": metrics.match_rate, "precision": metrics.precision}
            for name, metrics in report.per_class.items()
        },
        "acceptanceChecks": report.acceptance_checks,
        "acceptancePassed": report.acceptance_passed,
    }


def acceptance_exit_code(report: EvaluationReport) -> int:
    return 0 if report.acceptance_passed else 1


async def _run() -> int:
    async with async_session() as session:
        batch = await reset_demo(session)
        run = await run_reconciliation(session, batch.id)
        report = await evaluate_run(session, run.id)
        print(json.dumps(acceptance_payload(report), sort_keys=True))
        return acceptance_exit_code(report)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))

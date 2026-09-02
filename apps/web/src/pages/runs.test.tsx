import { fireEvent, screen } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { RunsPage } from "@/pages/runs";
import { RunDetailPage } from "@/pages/run-detail";
import { renderWithProviders } from "@/test/render";
import type { RunDetail, RunSummary } from "@/types/api";

const run: RunSummary = {
  runId: "run-001",
  batchId: "batch-001",
  batchKind: "demo",
  status: "completed",
  sourceRowCount: 415,
  sourceCounts: { ledger: 120 },
  startedAt: "2026-08-26T09:00:00Z",
  completedAt: "2026-08-26T09:00:02Z",
  durationMs: 1840,
  throughput: 225.54,
  metrics: null,
  errorMessage: null,
};

const detail: RunDetail = {
  ...run,
  metrics: {
    runId: "run-001",
    reportVersion: 1,
    benchmarkAvailable: true,
    precision: 100,
    falsePositives: 0,
    falsePositiveRate: 0,
    matchRate: 100,
    endToEndAutonomyRate: 100,
    exceptionRecall: 100,
    correctlyResolved: 76,
    matchableCases: 76,
    autonomousCases: 76,
    openExceptions: 0,
    financiallyUnresolvedCases: 0,
    moneyReconciled: 1_000_00,
    moneyUnresolved: 0,
    settlementNet: 1_000_00,
    recordsProcessed: 415,
    durationMs: 1840,
    throughput: 225.54,
    perClass: {
      exactId: {
        scenarioClass: "exactId",
        cases: 40,
        matchableCases: 40,
        correctlyResolved: 40,
        matchRate: 100,
        autonomousCases: 40,
        falsePositives: 0,
        precision: 100,
        openExceptions: 0,
        financiallyUnresolvedCases: 0,
        moneyReconciled: 1_000_00,
        moneyUnresolved: 0,
      },
    },
    stageMetrics: null,
    reviewAdjusted: {},
    acceptanceChecks: { runtime: true, precision: true },
    acceptancePassed: true,
  },
  results: [
    {
      resultId: "result-001",
      stage: "ledger_to_razorpay",
      status: "matched",
      primarySourceType: "ledger",
      primarySourceId: "ledger-001",
      amount: 1_000_00,
      currency: "INR",
      score: 100,
      runnerUpScore: 0,
      margin: 100,
      autonomous: true,
      selectedIds: ["ledger-001"],
      evidence: [],
      candidates: [],
    },
  ],
  links: [],
  exceptions: [],
};

describe("runs routes", () => {
  it("navigates from a run row to its detail route", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.includes("/reconciliation-runs/run-001")) return Promise.resolve(new Response(JSON.stringify(detail)));
      return Promise.resolve(new Response(JSON.stringify({ items: [run], total: 1, page: 1, pageSize: 50 })));
    });

    renderWithProviders(
      <Routes>
        <Route path="/runs" element={<RunsPage />} />
        <Route path="/runs/:runId" element={<RunDetailPage />} />
      </Routes>,
      { route: "/runs" },
    );
    fireEvent.click(await screen.findByRole("link", { name: /run-001/i }));

    expect(await screen.findByRole("heading", { name: /run run-001/i })).toBeInTheDocument();
  });

  it("shows acceptance checks and per-class metrics on detail", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(detail)));
    renderWithProviders(
      <Routes>
        <Route path="/runs/:runId" element={<RunDetailPage />} />
      </Routes>,
      { route: "/runs/run-001" },
    );

    expect(await screen.findByText("Acceptance checks")).toBeInTheDocument();
    expect(screen.getByText("Exact Id")).toBeInTheDocument();
    expect(screen.getAllByText("100.0%", { exact: false }).length).toBeGreaterThan(0);
    expect(document.getElementById("result-result-001")).toBeInTheDocument();
  });

  it("keeps placeholder rows visible while fetching the next run page", async () => {
    let resolveNextPage: ((value: Response) => void) | undefined;
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.includes("page=2")) {
        return new Promise<Response>((resolve) => {
          resolveNextPage = resolve;
        });
      }
      return Promise.resolve(new Response(JSON.stringify({ items: [run], total: 51, page: 1, pageSize: 25 })));
    });

    renderWithProviders(<RunsPage />, { route: "/runs" });
    fireEvent.click(await screen.findByRole("button", { name: /next page/i }));

    expect(await screen.findByRole("status", { name: "Updating runs" })).toBeInTheDocument();
    resolveNextPage?.(new Response(JSON.stringify({ items: [{ ...run, runId: "run-002" }], total: 51, page: 2, pageSize: 25 })));
    expect(await screen.findByText("run-002")).toBeInTheDocument();
  });
});

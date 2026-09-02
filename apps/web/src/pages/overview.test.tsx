import { fireEvent, screen, waitFor } from "@testing-library/react";
import { OverviewPage } from "@/pages/overview";
import { renderWithProviders } from "@/test/render";
import type { Batch, RunMetrics } from "@/types/api";

const metrics: RunMetrics = {
  runId: "run-001",
  reportVersion: 1,
  benchmarkAvailable: true,
  precision: 99.1,
  falsePositives: 1,
  falsePositiveRate: 0.9,
  matchRate: 96.4,
  endToEndAutonomyRate: 84.2,
  exceptionRecall: 100,
  correctlyResolved: 73,
  matchableCases: 76,
  autonomousCases: 64,
  openExceptions: 9,
  financiallyUnresolvedCases: 3,
  moneyReconciled: 125_430_00,
  moneyUnresolved: 7_120_00,
  settlementNet: 132_550_00,
  recordsProcessed: 415,
  durationMs: 1840,
  throughput: 225.54,
  perClass: {
    exactId: {
      scenarioClass: "exactId",
      cases: 40,
      matchableCases: 40,
      correctlyResolved: 39,
      matchRate: 97.5,
      autonomousCases: 38,
      falsePositives: 1,
      precision: 97.4,
      openExceptions: 1,
      financiallyUnresolvedCases: 1,
      moneyReconciled: 54_000_00,
      moneyUnresolved: 1_000_00,
    },
  },
  stageMetrics: null,
  reviewAdjusted: {
    closedCases: 5,
    reviewedCases: 5,
    approvedCases: 4,
    rejectedCases: 1,
    resolvedCases: 68,
    matchRate: 97.1,
    moneyReconciled: 126_000_00,
  },
  acceptanceChecks: {
    benchmarkAvailable: true,
    precision: false,
    falsePositives: false,
    matchRate: true,
    endToEndAutonomy: false,
    stageACorrectness: true,
    stageBCorrectness: true,
    positiveClassAccuracy: true,
    exceptionRecall: true,
    runtime: true,
  },
  acceptancePassed: false,
};

const batch: Batch = {
  batchId: "batch-001",
  kind: "demo",
  status: "completed",
  seed: "roborecon-v1",
  groundTruthAvailable: true,
  sourceRowCount: 415,
  startedAt: "2026-08-26T09:00:00Z",
  completedAt: "2026-08-26T09:00:02Z",
  sourceCounts: { ledger: 120, razorpay: 240, settlement: 55 },
};

const runSummary = {
  runId: "run-001",
  batchId: "batch-001",
  batchKind: "demo" as const,
  status: "completed" as const,
  sourceRowCount: 415,
  sourceCounts: { ledger: 120 },
  startedAt: "2026-08-26T09:00:00Z",
  completedAt: "2026-08-26T09:00:02Z",
  durationMs: 1840,
  throughput: 225.54,
  metrics,
  errorMessage: null,
};

function jsonResponse(data: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(data), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

describe("OverviewPage", () => {
  it("renders API metric values and run controls instead of dashboard literals", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.includes("/reconciliation-runs")) return jsonResponse({ items: [runSummary], total: 1, page: 1, pageSize: 1 });
      if (url.includes("/batches")) {
        return jsonResponse({ items: [batch], total: 1, page: 1, pageSize: 1 });
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    renderWithProviders(<OverviewPage />);

    expect(await screen.findByText("96.4%", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("99.1%", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("₹1,25,430.00", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("415", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("End-to-end autonomous resolution")).toBeInTheDocument();
    expect(screen.getByText("Money reconciled")).toBeInTheDocument();
    expect(screen.getByText("Money unresolved")).toBeInTheDocument();
    expect(screen.getByText("roborecon-v1", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("Seeded benchmark available")).toBeInTheDocument();
    expect(screen.getByText(/not production accuracy estimates or guarantees/i)).toBeInTheDocument();
    expect(screen.getByText("Benchmark match rate")).toBeInTheDocument();
    expect(screen.getByText("Benchmark precision")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /run reconciliation/i })).toBeEnabled();
  });

  it("uses reset output to enable reconciliation when no completed run exists", async () => {
    let reset = false;
    const resetBatch: Batch = { ...batch, status: "completed", batchId: "batch-reset" };
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.includes("/reconciliation-runs") && init?.method === "POST") {
        return jsonResponse({
          runId: "run-reset",
          batchId: "batch-reset",
          batchKind: "demo",
          status: "completed",
          sourceRowCount: 415,
          sourceCounts: {},
          startedAt: "2026-08-26T09:00:00Z",
          completedAt: "2026-08-26T09:00:02Z",
          durationMs: 2000,
          throughput: 207.5,
          metrics: null,
          errorMessage: null,
          results: [],
          links: [],
          exceptions: [],
        }, 201);
      }
      if (url.includes("/reconciliation-runs")) return jsonResponse({ items: [], total: 0, page: 1, pageSize: 1 });
      if (url.includes("/batches")) {
        return jsonResponse({ items: reset ? [resetBatch] : [], total: reset ? 1 : 0, page: 1, pageSize: 1 });
      }
      if (url.includes("/demo/reset")) {
        reset = true;
        return jsonResponse(resetBatch);
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderWithProviders(<OverviewPage />);

    const runButton = await screen.findByRole("button", { name: /run reconciliation/i });
    expect(runButton).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /reset demo data/i }));

    await waitFor(() => expect(runButton).toBeEnabled());
    fireEvent.click(runButton);
    await waitFor(() =>
      expect(globalThis.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/reconciliation-runs"),
        expect.objectContaining({ body: JSON.stringify({ batchId: "batch-reset" }) }),
      ),
    );
  });

  it("renders the loading state while the API is pending", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fetchSpy.mockImplementation(() => new Promise(() => undefined));
    renderWithProviders(<OverviewPage />);
    expect(screen.getByText("Loading summary…")).toBeInTheDocument();
  });

  it("renders an empty state when no completed run exists", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.includes("/reconciliation-runs")) return jsonResponse({ items: [], total: 0, page: 1, pageSize: 1 });
      return jsonResponse({ items: [], total: 0, page: 1, pageSize: 1 });
    });

    renderWithProviders(<OverviewPage />);
    expect(await screen.findByText("No completed run yet")).toBeInTheDocument();
  });

  it("renders an error state when the metrics request fails", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("network unavailable"));

    renderWithProviders(<OverviewPage />);
    expect(await screen.findByText("Could not load summary")).toBeInTheDocument();
  });

  it("does not show metrics from a run belonging to a different latest batch", async () => {
    const newerBatch = { ...batch, batchId: "batch-new" };
    const olderRun = { ...runSummary, batchId: batch.batchId };
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.includes("/batches")) return jsonResponse({ items: [newerBatch], total: 1, page: 1, pageSize: 1 });
      if (url.includes("/reconciliation-runs")) return jsonResponse({ items: [olderRun], total: 1, page: 1, pageSize: 1 });
      throw new Error(`Unexpected request: ${url}`);
    });

    renderWithProviders(<OverviewPage />);

    expect(await screen.findByText("No completed run yet")).toBeInTheDocument();
    expect(screen.queryByText("96.4%", { exact: false })).not.toBeInTheDocument();
  });

  it("confirms reset and disables both actions while reset is pending", async () => {
    let resolveReset: ((value: Response) => void) | undefined;
    const resetBatch = { ...batch, batchId: "batch-reset" };
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.includes("/batches")) return jsonResponse({ items: [batch], total: 1, page: 1, pageSize: 1 });
      if (url.includes("/reconciliation-runs") && init?.method !== "POST") {
        return jsonResponse({ items: [runSummary], total: 1, page: 1, pageSize: 1 });
      }
      if (url.includes("/demo/reset")) {
        return new Promise<Response>((resolve) => {
          resolveReset = resolve;
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);

    renderWithProviders(<OverviewPage />);
    const resetButton = await screen.findByRole("button", { name: "Reset demo data" });
    const runButton = screen.getByRole("button", { name: "Run reconciliation" });

    fireEvent.click(resetButton);
    expect(confirm).toHaveBeenCalledWith("Reset the demo data? Current demo records will be replaced.");
    expect(resetButton).toBeEnabled();

    fireEvent.click(resetButton);
    await waitFor(() => expect(resetButton).toBeDisabled());
    expect(runButton).toBeDisabled();

    resolveReset?.(new Response(JSON.stringify(resetBatch)));
  });

  it("disables reset while reconciliation is pending", async () => {
    let resolveRun: ((value: Response) => void) | undefined;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.includes("/batches")) return jsonResponse({ items: [batch], total: 1, page: 1, pageSize: 1 });
      if (url.includes("/reconciliation-runs") && init?.method === "POST") {
        return new Promise<Response>((resolve) => {
          resolveRun = resolve;
        });
      }
      if (url.includes("/reconciliation-runs")) return jsonResponse({ items: [runSummary], total: 1, page: 1, pageSize: 1 });
      throw new Error(`Unexpected request: ${url}`);
    });

    renderWithProviders(<OverviewPage />);
    const runButton = await screen.findByRole("button", { name: "Run reconciliation" });
    const resetButton = screen.getByRole("button", { name: "Reset demo data" });
    fireEvent.click(runButton);

    await waitFor(() => expect(runButton).toBeDisabled());
    expect(resetButton).toBeDisabled();
    resolveRun?.(new Response(JSON.stringify({ ...runSummary, runId: "run-new" })));
  });
});

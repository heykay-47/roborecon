import { fireEvent, screen, waitFor } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { CopilotPage } from "@/pages/copilot";
import { renderWithProviders } from "@/test/render";

describe("Copilot page", () => {
  it("keeps the settlement form content padded from the card edges", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input);
      if (path.includes("reconciliation-runs")) {
        return new Response(JSON.stringify({ items: [{ runId: "run-001", batchId: "batch-001", batchKind: "demo", status: "completed" }], total: 1, page: 1, pageSize: 25 }));
      }
      return new Response(JSON.stringify({ items: [], total: 0, page: 1, pageSize: 200 }));
    });

    renderWithProviders(
      <Routes>
        <Route path="/copilot" element={<CopilotPage />} />
      </Routes>,
      { route: "/copilot" },
    );

    const formCard = (await screen.findByRole("heading", { name: "Ask about a settlement" })).closest('[data-slot="card"]');
    expect(formCard?.querySelector('[data-slot="card-content"]')).toHaveClass("py-4");
  });

  it("renders a grounded answer with clickable citations and calculation", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = String(input);
      if (path.includes("reconciliation-runs")) {
        return new Response(JSON.stringify({ items: [{ runId: "run-001", batchId: "batch-001", batchKind: "demo", status: "completed", sourceRowCount: 2, sourceCounts: {}, startedAt: "2026-08-26T01:00:00Z", completedAt: "2026-08-26T01:00:01Z", durationMs: 1000, throughput: 2, metrics: null, errorMessage: null }], total: 1, page: 1, pageSize: 25 }));
      }
      if (path.includes("transactions")) {
        expect(path).toContain("batch_id=batch-001");
        return new Response(JSON.stringify({ items: [{ sourceType: "settlement", sourceId: "settlement-001", reference: "set_001", amount: 10000, currency: "INR", status: "processed", businessAt: "2026-08-26T01:00:00Z", batchId: "batch-001", reconciliationState: "matched", parseError: null, runId: "run-001", resultId: null, exceptionId: null }], total: 1, page: 1, pageSize: 200 }));
      }
      const body = typeof init?.body === "string" ? JSON.parse(init.body) as Record<string, unknown> : {};
      expect(body.question).toBe("Why is this settlement lower than captured payments?");
      expect(body.settlementId).toBe("settlement-001");
      return new Response(JSON.stringify({
        answer: "Settlement net is INR 100.00 after the persisted lines.",
        mode: "deterministicFallback",
        citations: [{ sourceType: "settlement", sourceId: "settlement-001" }],
        calculation: { expectedNet: 10000, actualNet: 10000 },
        toolTrace: [{ tool: "get_settlement_breakdown", status: "completed" }],
        errorCode: null,
      }));
    });

    renderWithProviders(
      <Routes>
        <Route path="/copilot" element={<CopilotPage />} />
      </Routes>,
      { route: "/copilot" },
    );

    expect(await screen.findByRole("heading", { name: "Copilot" })).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Explain settlement" }));

    expect(await screen.findByText(/Settlement net is INR 100.00/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /settlement settlement-001/i })).toHaveAttribute(
      "href",
      "/transactions?source=settlement&sourceId=settlement-001",
    );
    expect(screen.getByText("Rules-based answer")).toBeInTheDocument();
    expect(screen.getByText(/expectedNet/i)).toBeInTheDocument();
  });

  it("renders a safe fallback error instead of hiding a Copilot failure", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input);
      if (path.includes("reconciliation-runs")) return new Response(JSON.stringify({ items: [], total: 0, page: 1, pageSize: 25 }));
      if (path.includes("transactions")) return new Response(JSON.stringify({ items: [{ sourceType: "settlement", sourceId: "settlement-001", reference: "set_001", amount: 10000, currency: "INR", status: "processed", businessAt: null, batchId: "batch-001", reconciliationState: "unreconciled", parseError: null, runId: null, resultId: null, exceptionId: null }], total: 1, page: 1, pageSize: 200 }));
      return new Response(JSON.stringify({ detail: { code: "settlement_not_found", message: "Settlement was not found" } }), { status: 404, statusText: "Not Found" });
    });

    renderWithProviders(
      <Routes>
        <Route path="/copilot" element={<CopilotPage />} />
      </Routes>,
      { route: "/copilot" },
    );

    fireEvent.click(await screen.findByRole("button", { name: "Explain settlement" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/could not explain/i));
    expect(screen.getByRole("alert")).toHaveTextContent(/Settlement was not found/);
  });
});

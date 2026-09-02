import { screen } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { AuditPage } from "@/pages/audit";
import { renderWithProviders } from "@/test/render";

describe("audit page", () => {
  it("renders events in chronological sequence with actors and tool traces", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({
        items: [
          {
            eventId: "event-2",
            batchId: "batch-001",
            eventType: "review.approved",
            sequence: 2,
            actor: "human",
            entityType: "reconciliation_exception",
            entityId: "exception-001",
            sourceType: "settlement",
            sourceId: "settlement-001",
            occurredAt: "2026-08-26T02:00:00Z",
            summary: "Exception approved by human review",
            toolTrace: { note: "checked" },
          },
          {
            eventId: "event-1",
            batchId: "batch-001",
            eventType: "reconciliation.completed",
            sequence: 1,
            actor: "system",
            entityType: "reconciliation_run",
            entityId: "run-001",
            sourceType: null,
            sourceId: null,
            occurredAt: "2026-08-26T01:00:00Z",
            summary: "Run completed",
            toolTrace: null,
          },
        ],
        total: 2,
        page: 1,
        pageSize: 25,
      })),
    );

    renderWithProviders(
      <Routes>
        <Route path="/audit" element={<AuditPage />} />
      </Routes>,
      { route: "/audit" },
    );

    expect(await screen.findByRole("heading", { name: "Audit" })).toBeInTheDocument();
    const events = screen.getAllByRole("article");
    expect(events[0]).toHaveTextContent("#1");
    expect(events[1]).toHaveTextContent("#2");
    expect(screen.getByText("human")).toBeInTheDocument();
    expect(screen.getByText(/tool details/i)).toBeInTheDocument();
  });
});

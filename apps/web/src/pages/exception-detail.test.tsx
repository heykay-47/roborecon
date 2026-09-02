import { fireEvent, screen } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { ExceptionDetailPage } from "@/pages/exception-detail";
import { renderWithProviders } from "@/test/render";
import type { ExceptionDetail } from "@/types/api";

const detail: ExceptionDetail = {
  exceptionId: "exception-001",
  runId: "run-001",
  batchId: "batch-001",
  resultId: "result-001",
  status: "open",
  exceptionType: "amount_mismatch",
  sourceType: "ledger",
  sourceId: "ledger-001",
  amount: 12_500,
  message: "Settlement amount differs from the source record.",
  createdAt: "2026-08-26T09:00:00Z",
  aiReady: true,
  result: null,
  sourceSummaries: [],
  criterionEvidence: [],
  arithmetic: {},
  aiInvestigations: [],
  auditEvents: [],
};

const richDetail: ExceptionDetail = {
  ...detail,
  result: {
    resultId: "result-001",
    stage: "ledger_to_razorpay",
    status: "amount_mismatch",
    primarySourceType: "ledger",
    primarySourceId: "ledger-001",
    amount: 12500,
    currency: "INR",
    score: 82,
    runnerUpScore: 64,
    margin: 18,
    autonomous: false,
    selectedIds: [],
    evidence: [{ ruleCode: "amount_exact", observedValues: { ledger: 12500, provider: 13000 }, points: 0, result: "contradiction", explanation: "Amounts differ." }],
    candidates: [{ candidateId: "candidate-001", score: 82, evidence: [], contradictions: ["Amount differs"], duplicate: false, exactIdentifierChain: false, verifiedSettlementMath: false }],
  },
  sourceSummaries: [{ sourceType: "ledger", sourceId: "ledger-001", amount: 12500, reference: "ord_001" }, { sourceType: "razorpay_payment", sourceId: "candidate-001", amount: 13000, reference: "pay_001" }],
  criterionEvidence: [{ ruleCode: "amount_exact", observedValues: { ledger: 12500, provider: 13000 }, points: 0, result: "contradiction", explanation: "Amounts differ." }],
  arithmetic: { amount: 12500, currency: "INR", observations: [{ ledger: 12500, provider: 13000 }] },
  aiInvestigations: [{ investigationId: "investigation-001", exceptionId: "exception-001", runId: "run-001", batchId: "batch-001", mode: "deterministicFallback", provider: null, model: null, recommendation: "Review the amount mismatch.", confidence: 0, citations: [{ sourceType: "ledger", sourceId: "ledger-001" }], toolTrace: [{ tool: "get_exception_evidence", status: "completed" }], errorCode: "provider_unavailable", errorMessage: null }],
  auditEvents: [],
};

describe("exception detail route", () => {
  it("renders useful exception context and working evidence links", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(detail)),
    );

    renderWithProviders(
      <Routes>
        <Route path="/exceptions/:exceptionId" element={<ExceptionDetailPage />} />
      </Routes>,
      { route: "/exceptions/exception-001" },
    );

    expect(await screen.findByRole("heading", { name: /exception exception-001/i })).toBeInTheDocument();
    expect(screen.getByText(detail.message)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /run run-001/i })).toHaveAttribute(
      "href",
      "/runs/run-001",
    );
    expect(screen.getByRole("link", { name: /result result-001/i })).toHaveAttribute(
      "href",
      "/runs/run-001#result-result-001",
    );
  });

  it("renders score, criterion evidence, arithmetic, and advisory citations", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(richDetail)));

    renderWithProviders(
      <Routes><Route path="/exceptions/:exceptionId" element={<ExceptionDetailPage />} /></Routes>,
      { route: "/exceptions/exception-001" },
    );

    expect(await screen.findByText("Top score")).toBeInTheDocument();
    expect(screen.getAllByText("82")).not.toHaveLength(0);
    expect(screen.getByText("Observed: {\"ledger\":12500,\"provider\":13000}")).toBeInTheDocument();
    expect(screen.getByText("Deterministic fallback")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /ledger ledger-001/i })).toHaveAttribute(
      "href",
      "/transactions?source=ledger&sourceId=ledger-001",
    );
  });

  it("runs a bounded advisory investigation from the exception detail", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      if (init?.method === "POST") {
        return new Response(JSON.stringify({
          investigationId: "investigation-002",
          exceptionId: "exception-001",
          runId: "run-001",
          batchId: "batch-001",
          mode: "deterministicFallback",
          provider: null,
          model: null,
          recommendation: "Review persisted evidence.",
          confidence: 0,
          citations: [],
          toolTrace: [],
          errorCode: "provider_unavailable",
          errorMessage: null,
        }));
      }
      return new Response(JSON.stringify(detail));
    });

    renderWithProviders(
      <Routes><Route path="/exceptions/:exceptionId" element={<ExceptionDetailPage />} /></Routes>,
      { route: "/exceptions/exception-001" },
    );

    fireEvent.click(await screen.findByRole("button", { name: "Investigate exception" }));
    expect(await screen.findByText(/advisory investigation recorded/i)).toBeInTheDocument();
    expect(fetchSpy.mock.calls.some(([input]) => String(input).includes("/exceptions/exception-001/investigate"))).toBe(true);
  });

  it("requires terminal confirmation and surfaces a concurrent review conflict", async () => {
    let detailRequests = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      if (init?.method === "POST") {
        return new Response(JSON.stringify({ detail: "Reconciliation exception has already been reviewed" }), { status: 409, statusText: "Conflict" });
      }
      detailRequests += 1;
      return new Response(JSON.stringify(detailRequests === 1 ? richDetail : { ...richDetail, status: "approved" }));
    });

    renderWithProviders(
      <Routes><Route path="/exceptions/:exceptionId" element={<ExceptionDetailPage />} /></Routes>,
      { route: "/exceptions/exception-001" },
    );

    fireEvent.click(await screen.findByRole("button", { name: "Approve candidate" }));
    expect(screen.getByRole("region", { name: "Review confirmation" })).toHaveTextContent(/terminal/i);
    fireEvent.click(screen.getByRole("radio"));
    fireEvent.click(screen.getByRole("button", { name: "Confirm approve" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/reviewed elsewhere/i);
    fireEvent.click(screen.getByRole("button", { name: "Refresh exception" }));
    expect(await screen.findByText(/terminal review recorded/i)).toBeInTheDocument();
  });

  it("renders actionable not-found state for a missing exception", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Reconciliation exception was not found" }), {
        status: 404,
        statusText: "Not Found",
      }),
    );

    renderWithProviders(
      <Routes><Route path="/exceptions/:exceptionId" element={<ExceptionDetailPage />} /></Routes>,
      { route: "/exceptions/missing" },
    );

    expect(await screen.findByRole("heading", { name: "Exception not found" })).toBeInTheDocument();
  });
});

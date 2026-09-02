import { fireEvent, screen, waitFor } from "@testing-library/react";
import { TransactionsPage } from "@/pages/transactions";
import { renderWithProviders } from "@/test/render";
import type { PaginatedResponse, TransactionRecord } from "@/types/api";

const row: TransactionRecord = {
  sourceType: "ledger",
  sourceId: "ledger-001",
  reference: "ORD-001",
  amount: 12_500,
  currency: "INR",
  status: "payment",
  businessAt: "2026-08-26T09:00:00Z",
  batchId: "batch-001",
  reconciliationState: "matched",
  runId: "run-001",
  resultId: "result-001",
  exceptionId: null,
  parseError: null,
};

function response(data: PaginatedResponse<TransactionRecord>) {
  return Promise.resolve(new Response(JSON.stringify(data)));
}

describe("TransactionsPage", () => {
  it("sends server-side filters and page changes to the API", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      const page = url.includes("page=2") ? 2 : 1;
      return response({ items: [{ ...row, reference: `ORD-00${page}` }], total: 51, page, pageSize: 25 });
    });

    renderWithProviders(<TransactionsPage />);
    await screen.findByText("ORD-001");

    fireEvent.change(screen.getByLabelText("Record type"), { target: { value: "ledger" } });
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "payment" } });
    fireEvent.change(screen.getByLabelText("Match state"), { target: { value: "matched" } });

    await waitFor(() => {
      const requests = fetchSpy.mock.calls.map(([input]) => String(input));
      expect(requests.some((url) =>
        url.includes("source_type=ledger") &&
        url.includes("status=payment") &&
        url.includes("reconciliation_state=matched") &&
        url.includes("page=1"),
      )).toBe(true);
    });

    fireEvent.click(screen.getByRole("button", { name: /next page/i }));
    expect(await screen.findByText("ORD-002")).toBeInTheDocument();
    expect(fetchSpy.mock.calls.map(([input]) => String(input)).some((url) => url.includes("page=2"))).toBe(true);
  });

  it("renders malformed rows safely and links returned relationships", async () => {
    const malformed: TransactionRecord = {
      sourceType: "quarantine",
      sourceId: null,
      reference: null,
      amount: null,
      currency: null,
      status: "invalid",
      businessAt: null,
      batchId: "batch-001",
      reconciliationState: "unreconciled",
      runId: null,
      resultId: null,
      exceptionId: "exception-001",
      parseError: "Missing receipt",
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      response({ items: [row, malformed], total: 2, page: 1, pageSize: 50 }),
    );

    renderWithProviders(<TransactionsPage />);

    expect(await screen.findByText("This source record could not be read. Review the source data.")).toBeInTheDocument();
    expect(screen.queryByText("Missing receipt")).not.toBeInTheDocument();
    expect(screen.getByText("Invalid row")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /run-001/i })).toHaveAttribute("href", "/runs/run-001");
    expect(screen.getByRole("link", { name: /result-001/i })).toHaveAttribute("href", "/runs/run-001#result-result-001");
    expect(screen.getByRole("link", { name: /exception-001/i })).toHaveAttribute("href", "/exceptions/exception-001");
  });

  it("offers provider status values returned by the transaction contract", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      response({ items: [], total: 0, page: 1, pageSize: 25 }),
    );

    renderWithProviders(<TransactionsPage />);

    await screen.findByText("No records match these filters.");
    for (const label of [
      "Attempted",
      "Pending",
      "Initiated",
      "Reversed",
      "Partially processed",
      "Quarantined",
    ]) {
      expect(screen.getByRole("option", { name: label })).toBeInTheDocument();
    }
    expect(screen.getByRole("option", { name: "Paid" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Processed" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Partially refunded" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Refunded" })).toBeInTheDocument();
  });

  it("passes citation source type and source id to the server", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      response({
        items: [{ ...row, sourceType: "settlement_line", sourceId: "line-001" }],
        total: 1,
        page: 1,
        pageSize: 25,
      }),
    );

    renderWithProviders(<TransactionsPage />, { route: "/transactions?source=settlement_line&sourceId=line-001" });

    await screen.findByRole("heading", { name: "Transactions" });
    expect(fetchSpy.mock.calls.map(([input]) => String(input)).some((url) =>
      url.includes("source_type=settlement_line") && url.includes("source_id=line-001"),
    )).toBe(true);
  });

  it("shows a fetching indicator while replacing placeholder rows", async () => {
    let resolveNextPage: ((value: Response) => void) | undefined;
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.includes("page=2")) {
        return new Promise<Response>((resolve) => {
          resolveNextPage = resolve;
        });
      }
      return response({ items: [row], total: 51, page: 1, pageSize: 25 });
    });

    renderWithProviders(<TransactionsPage />);
    await screen.findByText("ORD-001");
    fireEvent.click(screen.getByRole("button", { name: /next page/i }));

    expect(await screen.findByRole("status", { name: "Updating records…" })).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalled();
    resolveNextPage?.(response({ items: [{ ...row, reference: "ORD-002" }], total: 51, page: 2, pageSize: 25 }));
    expect(await screen.findByText("ORD-002")).toBeInTheDocument();
  });
});

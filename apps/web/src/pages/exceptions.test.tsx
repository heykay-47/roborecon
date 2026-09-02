import { fireEvent, screen, waitFor } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { ExceptionsPage } from "@/pages/exceptions";
import { renderWithProviders } from "@/test/render";

const exception = {
  exceptionId: "exception-001",
  runId: "run-001",
  batchId: "batch-001",
  resultId: "result-001",
  status: "open",
  exceptionType: "amount_mismatch",
  sourceType: "ledger",
  sourceId: "ledger-001",
  amount: 12500,
  message: "Settlement amount differs from the source record.",
  createdAt: "",
  aiReady: true,
};

describe("exceptions queue", () => {
  it("renders operational fields and reloads when the status filter changes", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input);
      const items = path.includes("status=approved") ? [] : [exception];
      return new Response(JSON.stringify({ items, total: items.length, page: 1, pageSize: 25 }));
    });

    renderWithProviders(
      <Routes>
        <Route path="/exceptions" element={<ExceptionsPage />} />
      </Routes>,
      { route: "/exceptions" },
    );

    expect(await screen.findByRole("heading", { name: "Exceptions" })).toBeInTheDocument();
    expect(screen.getAllByText("₹125.00")).not.toHaveLength(0);
    expect(screen.getAllByText("Amount Mismatch")).not.toHaveLength(0);
    expect(screen.getAllByText("Age unavailable")).not.toHaveLength(0);
    expect(screen.getAllByText("Ready to investigate")).not.toHaveLength(0);
    expect(screen.getAllByRole("link", { name: /exception exception-001/i })[0]).toHaveAttribute(
      "href",
      "/exceptions/exception-001",
    );

    fireEvent.change(screen.getByLabelText("Exception status"), {
      target: { value: "approved" },
    });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/exceptions?page=1&page_size=25&status=approved"),
      expect.anything(),
    ));
    expect(await screen.findByText("No exceptions match these filters.")).toBeInTheDocument();
  });
});

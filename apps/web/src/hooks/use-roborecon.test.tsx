import { fireEvent, screen, waitFor } from "@testing-library/react";
import { useQuery } from "@tanstack/react-query";
import {
  useCopilot,
  useExceptions,
  useInvestigate,
  useResetDemo,
  useReviewException,
} from "@/hooks/use-roborecon";
import { createTestQueryClient, renderWithProviders } from "@/test/render";

function Probe() {
  const mutation = useResetDemo();
  return <button onClick={() => mutation.mutate()}>{mutation.isSuccess ? "Reset" : "Reset demo"}</button>;
}

function OverviewCacheProbe() {
  const overview = useQuery({
    queryKey: ["overview"],
    queryFn: async () => ({ metrics: null, latestBatch: null }),
    enabled: false,
  });
  return <span>{overview.data?.metrics ? "Stale metrics" : overview.data ? "Metrics cleared" : "No overview"}</span>;
}

describe("useResetDemo", () => {
  it("invalidates every Task 9 server-state surface after reset", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ batchId: "batch-001" })));
    const { queryClient } = renderWithProviders(<Probe />);
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    fireEvent.click(screen.getByRole("button", { name: "Reset demo" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Reset" })).toBeInTheDocument());
    const keys = invalidate.mock.calls.map(([filters]) => filters.queryKey?.[0]);
    expect(keys).toEqual(expect.arrayContaining(["overview", "batches", "runs", "transactions", "exceptions", "audit"]));
  });

  it("clears cached overview metrics immediately after reset", async () => {
    const queryClient = createTestQueryClient();
    queryClient.setQueryData(["overview"], {
      metrics: { runId: "old-run", reportVersion: 1 },
      latestBatch: { batchId: "old-batch" },
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ batchId: "new-batch", status: "completed" })),
    );
    renderWithProviders(
      <>
        <Probe />
        <OverviewCacheProbe />
      </>,
      { queryClient },
    );

    fireEvent.click(screen.getByRole("button", { name: "Reset demo" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Reset" })).toBeInTheDocument());
    expect(screen.getByText("Metrics cleared")).toBeInTheDocument();
    expect(queryClient.getQueryData(["overview"])).toEqual({
      metrics: null,
      latestBatch: { batchId: "new-batch", status: "completed" },
    });
  });
});

function HookProbe() {
  const exceptions = useExceptions({
    status: "open",
    page: 2,
    pageSize: 10,
    runId: "run-001",
    exceptionType: "duplicate",
  });
  const review = useReviewException();
  const investigate = useInvestigate();
  const copilot = useCopilot();

  return (
    <div>
      <span>{exceptions.data?.total ?? "loading"}</span>
      <button
        onClick={() =>
          review.mutate({
            exceptionId: "exception-001",
            action: "approve",
            candidateId: "candidate-001",
            note: "Reviewed against settlement evidence.",
          })
        }
      >
        Review
      </button>
      <button
        onClick={() => investigate.mutate({ exceptionId: "exception-001" })}
      >
        Investigate
      </button>
      <button
        onClick={() =>
          copilot.mutate({
            question: "Explain this settlement reconciliation.",
            runId: "run-001",
            settlementId: "settlement-001",
          })
        }
      >
        Ask
      </button>
      <span>{review.isSuccess ? "reviewed" : ""}</span>
      <span>{investigate.isSuccess ? "investigated" : ""}</span>
      <span>{copilot.isSuccess ? "answered" : ""}</span>
    </div>
  );
}

function CopilotProbe() {
  const copilot = useCopilot();
  return (
    <>
      <button onClick={() => copilot.mutate({ question: "Explain this settlement reconciliation.", runId: "run-001", settlementId: "settlement-001" })}>Ask</button>
      <span>{copilot.isSuccess ? "answered" : ""}</span>
    </>
  );
}

describe("Task 10 query hooks", () => {
  it("serializes exception filters into the typed list request", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ items: [], total: 0, page: 2, pageSize: 10 })),
    );

    renderWithProviders(<HookProbe />);

    await waitFor(() => expect(screen.getByText("0")).toBeInTheDocument());
    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/exceptions?page=2&page_size=10"),
      expect.objectContaining({ headers: { "Content-Type": "application/json" } }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining("run_id=run-001"),
      expect.anything(),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining("type=duplicate"),
      expect.anything(),
    );
  });

  it("posts review, investigation, and Copilot requests and invalidates operational surfaces", async () => {
    const responses = [
      { exceptionId: "exception-001", action: "approve", status: "approved" },
      { investigationId: "investigation-001", mode: "deterministicFallback" },
      { answer: "Grounded answer", mode: "deterministicFallback", citations: [], calculation: null, toolTrace: [], errorCode: null },
    ];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      const body = typeof init?.body === "string" ? JSON.parse(init.body) as Record<string, unknown> : null;
      if (body?.action === "approve") return new Response(JSON.stringify(responses[0]));
      if (body?.settlementId) return new Response(JSON.stringify(responses[2]));
      return new Response(JSON.stringify(responses[1]));
    });

    const { queryClient } = renderWithProviders(<HookProbe />);
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    fireEvent.click(screen.getByRole("button", { name: "Investigate" }));
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    await waitFor(() => expect(screen.getByText("reviewed")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("investigated")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("answered")).toBeInTheDocument());

    const keys = invalidate.mock.calls.map(([filters]) => filters.queryKey?.[0]);
    expect(keys).toEqual(
      expect.arrayContaining([
        "overview",
        "batches",
        "runs",
        "transactions",
        "exceptions",
        "audit",
      ]),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/exceptions/exception-001/review"),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          action: "approve",
          actor: "human",
          candidateId: "candidate-001",
          note: "Reviewed against settlement evidence.",
        }),
      }),
    );
  });

  it("sends Copilot context as typed camelCase fields", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ answer: "Grounded answer", mode: "deterministicFallback", citations: [], calculation: null, toolTrace: [], errorCode: null })),
    );

    renderWithProviders(<CopilotProbe />);
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    await waitFor(() => expect(screen.getByText("answered")).toBeInTheDocument());
    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/copilot/ask"),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          question: "Explain this settlement reconciliation.",
          runId: "run-001",
          settlementId: "settlement-001",
        }),
      }),
    );
  });
});

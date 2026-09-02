import { screen } from "@testing-library/react";
import { render } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import App from "@/App";
import { createTestQueryClient } from "@/test/render";

describe("application routes", () => {
  it.each([
    ["/exceptions", "Exceptions"],
    ["/audit", "Audit"],
    ["/copilot", "Copilot"],
    ["/settings", "Settings"],
  ])("loads the %s surface instead of a placeholder", async (path, heading) => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(JSON.stringify({ items: [], total: 0, page: 1, pageSize: 50 })));
    window.history.pushState({}, "", path);
    render(<QueryClientProvider client={createTestQueryClient()}><App /></QueryClientProvider>);

    expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
    expect(screen.queryByText(/arrive in the next task/i)).not.toBeInTheDocument();
  });

  it("keeps unknown paths in the truthful not-found state", async () => {
    window.history.pushState({}, "", "/not-a-real-route");
    render(<QueryClientProvider client={createTestQueryClient()}><App /></QueryClientProvider>);

    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
  });
});

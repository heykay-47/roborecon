import { fetchApi } from "@/lib/api";

describe("fetchApi", () => {
  it("surfaces FastAPI detail messages for failed responses", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "No completed reconciliation run found" }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(fetchApi("/metrics")).rejects.toMatchObject({
      message: "No completed reconciliation run found",
      status: 404,
    });
  });

  it("returns undefined for successful empty responses", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 204 }));

    await expect(fetchApi<undefined>("/demo/reset")).resolves.toBeUndefined();
  });

  it("returns successful non-JSON response bodies as text", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("accepted", {
        status: 200,
        headers: { "Content-Type": "text/plain" },
      }),
    );

    await expect(fetchApi<string>("/health")).resolves.toBe("accepted");
  });
});

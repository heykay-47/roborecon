import { screen } from "@testing-library/react";
import { SettingsPage } from "@/pages/settings";
import { renderWithProviders } from "@/test/render";

describe("Settings page", () => {
  it("keeps space below the matching rules list", () => {
    renderWithProviders(<SettingsPage />);

    const card = screen.getByRole("heading", { name: "How matching works" }).closest('[data-slot="card"]');
    expect(card?.querySelector('[data-slot="card-content"]')).toHaveClass("pb-4");
  });
});

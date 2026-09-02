import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Layout } from "@/components/layout";
import { THEME_STORAGE_KEY } from "@/hooks/use-theme";

describe("Layout", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.classList.remove("dark");
    delete document.documentElement.dataset.theme;
  });

  it("keeps Roborecon branding and exposes all seven destinations on mobile", () => {
    render(
      <MemoryRouter>
        <Layout />
      </MemoryRouter>,
    );

    expect(screen.getByText("Roborecon")).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Workspace navigation" })).toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: "Toggle navigation" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute(
      "href",
      "/",
    );
    expect(screen.getByRole("link", { name: "Runs" })).toHaveAttribute(
      "href",
      "/runs",
    );
    expect(screen.getByRole("link", { name: "Transactions" })).toHaveAttribute(
      "href",
      "/transactions",
    );
    expect(screen.getByRole("link", { name: "Exceptions" })).toHaveAttribute(
      "href",
      "/exceptions",
    );
    expect(screen.getByRole("link", { name: "Audit" })).toHaveAttribute(
      "href",
      "/audit",
    );
    expect(screen.getByRole("link", { name: "Copilot" })).toHaveAttribute(
      "href",
      "/copilot",
    );
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute(
      "href",
      "/settings",
    );
  });

  it("makes a closed mobile sidebar inert, supports Escape, and restores focus", async () => {
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: query.includes("max-width"),
        media: query,
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
    const { container } = render(
      <MemoryRouter>
        <Layout />
      </MemoryRouter>,
    );

    const sidebar = container.querySelector("aside");
    const toggle = screen.getByRole("button", { name: "Toggle navigation" });
    const skipLink = screen.getByRole("link", { name: "Skip to main content" });

    await waitFor(() => expect(sidebar).toHaveAttribute("aria-hidden", "true"));
    expect(sidebar).toHaveAttribute("inert");
    expect(skipLink).toHaveAttribute("href", "#main-content");

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: "Close navigation" })).toHaveFocus();
    expect(sidebar).not.toHaveAttribute("aria-hidden", "true");
    expect(sidebar).not.toHaveAttribute("inert");

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(toggle).toHaveAttribute("aria-expanded", "false"));
    expect(toggle).toHaveFocus();
  });

  it("defaults to dark mode and persists the selected theme", async () => {
    render(
      <MemoryRouter>
        <Layout />
      </MemoryRouter>,
    );

    const themeToggle = screen.getByRole("button", { name: "Switch to light mode" });
    await waitFor(() => expect(document.documentElement).toHaveClass("dark"));
    expect(themeToggle).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(themeToggle);

    await waitFor(() => expect(document.documentElement).not.toHaveClass("dark"));
    expect(screen.getByRole("button", { name: "Switch to dark mode" })).toHaveAttribute("aria-pressed", "false");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
  });

  it("restores a saved light mode", async () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "light");

    render(
      <MemoryRouter>
        <Layout />
      </MemoryRouter>,
    );

    expect(screen.getByRole("button", { name: "Switch to dark mode" })).toHaveAttribute("aria-pressed", "false");
    await waitFor(() => expect(document.documentElement).not.toHaveClass("dark"));
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});

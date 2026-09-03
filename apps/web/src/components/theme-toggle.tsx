import { IconMoon, IconSun } from "@tabler/icons-react";
import type { Theme } from "@/hooks/use-theme";

export function ThemeToggle({ theme, onToggle }: { theme: Theme; onToggle: () => void }) {
  const nextTheme = theme === "dark" ? "light" : "dark";
  const Icon = theme === "dark" ? IconSun : IconMoon;

  return (
    <button
      type="button"
      data-slot="button"
      className="inline-flex h-9 items-center gap-2 rounded-md border border-border bg-card px-2.5 text-xs font-medium text-muted-foreground shadow-xs transition-colors hover:bg-muted hover:text-foreground"
      aria-label={`Switch to ${nextTheme} mode`}
      aria-pressed={theme === "dark"}
      title={`Switch to ${nextTheme} mode`}
      onClick={onToggle}
    >
      <Icon className="size-4 text-primary" aria-hidden="true" />
      <span className="hidden sm:inline">{theme === "dark" ? "Dark" : "Light"}</span>
    </button>
  );
}

import { useEffect, useRef, useState, type ComponentType } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  IconChartBar,
  IconClipboardList,
  IconFileSearch,
  IconMenu2,
  IconRobot,
  IconSettings,
  IconTable,
  IconTimeline,
  IconX,
} from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import { useTheme } from "@/hooks/use-theme";
import { ThemeToggle } from "@/components/theme-toggle";

interface NavigationItem {
  to: string;
  label: string;
  icon: ComponentType<{ className?: string; "aria-hidden"?: boolean | "true" | "false" }>;
}

const navigationItems: NavigationItem[] = [
  { to: "/", label: "Overview", icon: IconChartBar },
  { to: "/runs", label: "Runs", icon: IconClipboardList },
  { to: "/transactions", label: "Source records", icon: IconTable },
  { to: "/exceptions", label: "Exceptions", icon: IconFileSearch },
  { to: "/audit", label: "Audit", icon: IconTimeline },
  { to: "/copilot", label: "Copilot", icon: IconRobot },
  { to: "/settings", label: "Settings", icon: IconSettings },
];

function NavigationLinks({ onNavigate }: { onNavigate: () => void }) {
  return (
    <nav aria-label="Primary navigation" className="space-y-0.5">
      {navigationItems.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          end={to === "/"}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              "group flex min-h-11 items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
              isActive
                ? "bg-sidebar-accent text-sidebar-accent-foreground ring-1 ring-sidebar-primary/25"
                : "text-muted-foreground hover:bg-sidebar-accent/70 hover:text-sidebar-foreground",
            )
          }
        >
          <Icon className="size-[1.1rem] shrink-0" aria-hidden="true" />
          <span>{label}</span>
        </NavLink>
      ))}
    </nav>
  );
}

export function Layout() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const { theme, toggleTheme } = useTheme();
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(max-width: 1023px)").matches,
  );
  const toggleRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const sidebarRef = useRef<HTMLElement>(null);
  const wasMobileOpen = useRef(false);
  const location = useLocation();
  const currentItem = navigationItems.find(({ to }) =>
    to === "/" ? location.pathname === "/" : location.pathname.startsWith(to),
  );
  const sidebarInert = isMobile && !mobileOpen;

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mediaQuery = window.matchMedia("(max-width: 1023px)");
    const updateViewport = () => setIsMobile(mediaQuery.matches);
    updateViewport();
    mediaQuery.addEventListener("change", updateViewport);
    return () => mediaQuery.removeEventListener("change", updateViewport);
  }, []);

  useEffect(() => {
    if (!mobileOpen || !isMobile) return;
    closeRef.current?.focus();
    const trapFocus = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const focusable = sidebarRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), select:not([disabled]), textarea:not([disabled]), input:not([disabled])',
      );
      if (!focusable || focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMobileOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    window.addEventListener("keydown", trapFocus);
    return () => {
      window.removeEventListener("keydown", closeOnEscape);
      window.removeEventListener("keydown", trapFocus);
    };
  }, [isMobile, mobileOpen]);

  useEffect(() => {
    if (wasMobileOpen.current && !mobileOpen) toggleRef.current?.focus();
    wasMobileOpen.current = mobileOpen;
  }, [mobileOpen]);

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <a
        href="#main-content"
        className="sr-only fixed left-4 top-4 z-50 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground focus:not-sr-only"
      >
        Skip to main content
      </a>
      <aside
        ref={sidebarRef}
        aria-label="Workspace navigation"
        className={cn(
          "fixed inset-y-0 z-40 flex w-64 flex-col border-r border-sidebar-border bg-sidebar px-3 py-4 transition-[left] lg:static lg:left-0",
          mobileOpen ? "left-0" : "-left-64",
        )}
        aria-hidden={sidebarInert ? true : undefined}
        inert={sidebarInert ? true : undefined}
      >
        <div className="flex items-center justify-between px-2 py-1">
          <div className="flex items-center gap-3">
            <img
              src="/roborecon_logo.png"
              alt=""
              aria-hidden="true"
              width="40"
              height="40"
              className="size-10 shrink-0 object-contain"
            />
            <div>
              <p className="font-semibold tracking-tight text-sidebar-foreground">Roborecon</p>
              <p className="text-[0.65rem] uppercase tracking-[0.16em] text-muted-foreground">
                Operations
              </p>
            </div>
          </div>
          <button
            type="button"
            ref={closeRef}
            className="flex size-11 items-center justify-center rounded-md text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-foreground lg:hidden"
            aria-label="Close navigation"
            onClick={() => setMobileOpen(false)}
          >
            <IconX className="size-4" aria-hidden="true" />
          </button>
        </div>

        <div className="mt-9 px-3 text-[0.65rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
          Workspace
        </div>
        <div className="mt-2">
          <NavigationLinks onNavigate={() => setMobileOpen(false)} />
        </div>

        <div className="mt-auto border-t border-sidebar-border px-3 pt-4">
          <p className="text-xs font-medium text-sidebar-foreground">Matching rules</p>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            Rules decide matches. Review anything unclear.
          </p>
        </div>
      </aside>

      {mobileOpen && (
        <button
          type="button"
         className="fixed inset-0 z-30 bg-slate-950/65 backdrop-blur-[1px] lg:hidden"
          aria-label="Dismiss navigation"
          onClick={() => setMobileOpen(false)}
        />
      )}

      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-border bg-background/95 px-4 backdrop-blur-sm sm:px-6 lg:px-8">
          <div className="flex items-center gap-3">
            <button
              type="button"
              ref={toggleRef}
               className="flex size-11 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground lg:hidden"
              aria-label="Toggle navigation"
              aria-expanded={mobileOpen}
              onClick={() => setMobileOpen((open) => !open)}
            >
               <IconMenu2 className="size-5" aria-hidden="true" />
            </button>
            <div>
              <p className="text-sm font-semibold text-foreground">
                {currentItem?.label ?? "Overview"}
              </p>
              <p className="hidden text-xs text-muted-foreground sm:block">
                Payment matching workspace
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <ThemeToggle theme={theme} onToggle={toggleTheme} />
             <span className="size-1.5 rounded-full bg-success" aria-hidden="true" />
             <span className="hidden sm:inline">Demo data</span>
          </div>
        </header>

        <main id="main-content" tabIndex={-1} className="mx-auto w-full max-w-[1600px] px-4 py-6 outline-none sm:px-6 lg:px-8 lg:py-7">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

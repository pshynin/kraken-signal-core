"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  LayoutDashboard,
  ListOrdered,
  History,
  Bell,
  Settings,
  LogOut,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { MomentumLogo } from "@/components/brand/momentum-logo";

const NAV_ITEMS = [
  { href: "/", label: "Overview", icon: LayoutDashboard, exact: true },
  { href: "/candidates", label: "Candidates", icon: ListOrdered, exact: false },
  { href: "/scans", label: "Scan History", icon: History, exact: false },
  { href: "/alerts", label: "Alert History", icon: Bell, exact: false },
  { href: "/settings", label: "Settings", icon: Settings, exact: false },
] as const;

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();

  function isActive(href: string, exact: boolean): boolean {
    return exact ? pathname === href : pathname.startsWith(href);
  }

  async function handleLogout() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.push("/login");
    router.refresh();
  }

  return (
    <aside className="flex h-screen w-60 flex-shrink-0 flex-col border-r border-border bg-card">
      {/* Brand */}
      <div className="flex h-16 items-center gap-2.5 border-b border-border px-5">
        <MomentumLogo size={22} className="text-foreground" />
        <span className="text-[0.95rem] font-semibold tracking-tight text-foreground">
          Momentum Copilot
        </span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-0.5 px-3 py-4">
        {NAV_ITEMS.map(({ href, label, icon: Icon, exact }) => {
          const active = isActive(href, exact);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "group relative flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-muted/70 text-foreground"
                  : "text-muted-foreground hover:bg-muted/40 hover:text-foreground"
              )}
            >
              {/* Active rail — restrained green accent */}
              <span
                aria-hidden
                className={cn(
                  "absolute inset-y-1.5 left-0 w-[2px] rounded-full transition-colors",
                  active ? "bg-primary" : "bg-transparent"
                )}
              />
              <Icon
                className={cn(
                  "h-4 w-4 shrink-0 transition-colors",
                  active
                    ? "text-foreground"
                    : "text-muted-foreground group-hover:text-foreground"
                )}
              />
              <span className={cn(active && "font-medium")}>{label}</span>
            </Link>
          );
        })}
      </nav>

      {/* Sign out */}
      <div className="border-t border-border px-3 py-3">
        <button
          onClick={handleLogout}
          className={cn(
            "flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-sm",
            "text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground"
          )}
        >
          <LogOut className="h-4 w-4 shrink-0" />
          Sign out
        </button>
      </div>
    </aside>
  );
}

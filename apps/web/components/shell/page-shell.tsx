import { cn } from "@/lib/utils";

interface PageShellProps {
  children: React.ReactNode;
  className?: string;
}

/**
 * Canonical app page container. Left-aligned, generous max-width, consistent
 * horizontal padding and top spacing. Every `(app)/*` page renders inside one
 * of these so titles, KPI cards, tables, and sections share a single grid line.
 */
export function PageShell({ children, className }: PageShellProps) {
  return (
    <div className={cn("px-6 py-8 lg:px-10", className)}>
      <div className="max-w-7xl space-y-8">{children}</div>
    </div>
  );
}

interface PageHeaderProps {
  title: string;
  subtitle?: React.ReactNode;
  right?: React.ReactNode;
  className?: string;
}

/** Standard page header — title + subtitle on the same grid line as content. */
export function PageHeader({
  title,
  subtitle,
  right,
  className,
}: PageHeaderProps) {
  return (
    <header
      className={cn(
        "flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between",
        className
      )}
    >
      <div className="min-w-0">
        <h1 className="text-[1.375rem] font-semibold tracking-tight text-foreground">
          {title}
        </h1>
        {subtitle && (
          <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
        )}
      </div>
      {right && <div className="shrink-0">{right}</div>}
    </header>
  );
}

import { cn } from "@/lib/utils";

interface MomentumLogoProps {
  className?: string;
  size?: number;
  title?: string;
  /** Solid colors used when the SVG is rendered outside the app theme (favicon route). */
  solid?: { surface: string; border: string; stroke: string; accent: string };
}

/**
 * Momentum Copilot brand mark.
 *
 * Compact "M" monogram fused with an ascending bar/arrow motif — meant to
 * read as both the product initial and an upward momentum signal. Uses
 * `currentColor` for the structural strokes and the design-token primary
 * (--primary) for the accent so it adapts to surface and brand colour.
 */
export function MomentumLogo({
  className,
  size = 24,
  title = "Momentum Copilot",
  solid,
}: MomentumLogoProps) {
  const surface = solid?.surface ?? "hsl(var(--card))";
  const border = solid?.border ?? "hsl(var(--border))";
  const stroke = solid?.stroke ?? "currentColor";
  const accent = solid?.accent ?? "hsl(var(--primary))";
  return (
    <svg
      role="img"
      aria-label={title}
      viewBox="0 0 32 32"
      width={size}
      height={size}
      className={cn("shrink-0", className)}
    >
      {/* Rounded container */}
      <rect
        x="1"
        y="1"
        width="30"
        height="30"
        rx="8"
        fill={surface}
        stroke={border}
        strokeWidth="1"
      />

      {/* M strokes — left peak, valley, right peak */}
      <path
        d="M7 23 L7 10 L11 10 L16 17 L21 10 L25 10 L25 23"
        fill="none"
        stroke={stroke}
        strokeWidth="2.25"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {/* Momentum accent — ascending arrow tucked under the valley */}
      <path
        d="M11 23 L16 18 L21 23"
        fill="none"
        stroke={accent}
        strokeWidth="2.25"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

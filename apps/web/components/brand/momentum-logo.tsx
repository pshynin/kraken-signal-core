import Image from "next/image";
import { cn } from "@/lib/utils";

interface MomentumLogoProps {
  className?: string;
  size?: number;
  title?: string;
}

/**
 * Momentum Copilot brand mark. Renders the canonical PNG from
 * `public/momentum-icon.png` — the same source the Next metadata
 * route `app/icon.png` uses for the browser-tab favicon.
 */
export function MomentumLogo({
  className,
  size = 24,
  title = "Momentum Copilot",
}: MomentumLogoProps) {
  return (
    <Image
      src="/momentum-icon.png"
      alt={title}
      width={size}
      height={size}
      priority
      unoptimized
      className={cn("shrink-0", className)}
    />
  );
}

import Image from "next/image";
import { cn } from "@/lib/utils";

interface MomentumLogoProps {
  className?: string;
  size?: number;
  title?: string;
}

/**
 * Momentum Copilot brand mark. Renders the canonical PNG from
 * `public/icon.png` — the same source declared as the favicon
 * via `metadata.icons` in `app/layout.tsx`.
 */
export function MomentumLogo({
  className,
  size = 24,
  title = "Momentum Copilot",
}: MomentumLogoProps) {
  return (
    <Image
      src="/icon.png"
      alt={title}
      width={size}
      height={size}
      priority
      className={cn("shrink-0", className)}
    />
  );
}

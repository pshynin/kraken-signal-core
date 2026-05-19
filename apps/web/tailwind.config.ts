import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Design token: premium dark fintech palette
        border: "hsl(var(--border))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
          elevated: "hsl(var(--surface-elevated))",
        },
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        // Semantic colors for trade UI
        bull: "hsl(142 71% 45%)",   // green — clean candidates, profit
        bear: "hsl(0 84% 60%)",     // red  — invalidations, stop hits
        caution: "hsl(38 92% 50%)", // amber — ugly candidates, warnings
        info: "hsl(210 90% 60%)",   // blue — informational
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
        xl: "calc(var(--radius) + 4px)",
      },
      fontFamily: {
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      boxShadow: {
        card: "0 1px 0 0 hsl(0 0% 100% / 0.03) inset, 0 1px 2px 0 hsl(0 0% 0% / 0.4)",
        elevated:
          "0 1px 0 0 hsl(0 0% 100% / 0.04) inset, 0 8px 24px -8px hsl(0 0% 0% / 0.6)",
      },
    },
  },
  plugins: [],
};

export default config;

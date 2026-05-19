import { ImageResponse } from "next/og";

export const size = { width: 32, height: 32 };
export const contentType = "image/png";

// Mirrors components/brand/momentum-logo.tsx — keep visually in sync if it changes.
export default function Icon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#0a0f1a",
          borderRadius: 8,
        }}
      >
        <svg
          viewBox="0 0 32 32"
          width="32"
          height="32"
          xmlns="http://www.w3.org/2000/svg"
        >
          <rect
            x="1"
            y="1"
            width="30"
            height="30"
            rx="8"
            fill="#0a0f1a"
            stroke="#1c2433"
            strokeWidth="1"
          />
          <path
            d="M7 23 L7 10 L11 10 L16 17 L21 10 L25 10 L25 23"
            fill="none"
            stroke="#e5edf5"
            strokeWidth="2.25"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M11 23 L16 18 L21 23"
            fill="none"
            stroke="#22c55e"
            strokeWidth="2.25"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </div>
    ),
    { ...size }
  );
}

/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "Roboto", "sans-serif"],
      },
      colors: {
        canvas: {
          DEFAULT: "#FAF9F6",
          subtle: "#F3F2EE",
          card: "#FFFFFF",
        },
        ink: {
          DEFAULT: "#0F172A",
          secondary: "#334155",
          muted: "#64748B",
          subtle: "#94A3B8",
        },
        border: {
          DEFAULT: "#E2E8F0",
          strong: "#CBD5E1",
        },
        brand: {
          50: "#F0FDFA",
          100: "#CCFBF1",
          200: "#99F6E4",
          500: "#14B8A6",
          600: "#0D9488",
          700: "#0F766E",
          800: "#115E59",
          900: "#134E4A",
          DEFAULT: "#0F766E",
          hover: "#115E59",
          light: "#F0FDFA",
        },
        feedback: {
          success: "#15803D",
          successBg: "#F0FDF4",
          warning: "#B45309",
          warningBg: "#FFFBEB",
          danger: "#B91C1C",
          dangerBg: "#FEF2F2",
        },
      },
      spacing: {
        "grid-1": "8px",
        "grid-2": "16px",
        "grid-3": "24px",
        "grid-4": "32px",
        "grid-5": "40px",
        "grid-6": "48px",
        "grid-8": "64px",
      },
      borderRadius: {
        card: "12px",
        xl: "12px",
        lg: "10px",
        md: "8px",
      },
      boxShadow: {
        soft: "0 2px 12px -2px rgba(15, 23, 42, 0.06), 0 1px 4px -1px rgba(15, 23, 42, 0.04)",
        card: "0 4px 20px -4px rgba(15, 23, 42, 0.07), 0 2px 6px -1px rgba(15, 23, 42, 0.04)",
        popover: "0 12px 32px -4px rgba(15, 23, 42, 0.12), 0 4px 12px -2px rgba(15, 23, 42, 0.06)",
      },
      fontSize: {
        "display": ["2.25rem", { lineHeight: "2.75rem", letterSpacing: "-0.02em", fontWeight: "700" }],
        "h1": ["1.75rem", { lineHeight: "2.25rem", letterSpacing: "-0.015em", fontWeight: "600" }],
        "h2": ["1.25rem", { lineHeight: "1.75rem", letterSpacing: "-0.01em", fontWeight: "600" }],
        "body": ["1rem", { lineHeight: "1.5rem", fontWeight: "400" }],
        "caption": ["0.875rem", { lineHeight: "1.25rem", fontWeight: "400" }],
      },
    },
  },
  plugins: [],
};

import tailwindcssAnimate from "tailwindcss-animate";

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--tw-border) / <alpha-value>)",
        background: "hsl(var(--tw-background) / <alpha-value>)",
        foreground: "hsl(var(--tw-foreground) / <alpha-value>)",
        primary: {
          DEFAULT: "hsl(var(--tw-primary) / <alpha-value>)",
          foreground: "hsl(var(--tw-primary-foreground) / <alpha-value>)",
        },
        muted: {
          DEFAULT: "hsl(var(--tw-muted) / <alpha-value>)",
          foreground: "hsl(var(--tw-muted-foreground) / <alpha-value>)",
        },
        accent: {
          DEFAULT: "hsl(var(--tw-accent) / <alpha-value>)",
          foreground: "hsl(var(--tw-accent-foreground) / <alpha-value>)",
        },
        card: {
          DEFAULT: "hsl(var(--tw-card) / <alpha-value>)",
          foreground: "hsl(var(--tw-card-foreground) / <alpha-value>)",
        },
        neon: {
          cyan: "hsl(var(--neon-cyan) / <alpha-value>)",
          violet: "hsl(var(--neon-violet) / <alpha-value>)",
        },
      },
      borderRadius: {
        lg: "var(--radius-lg)",
        md: "var(--radius-md)",
        sm: "var(--radius-sm)",
      },
      fontFamily: {
        sans: ["var(--font-ui)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [tailwindcssAnimate],
};

/** @type {import('tailwindcss').Config} */

// Cool Ink theme: maps Tailwind color tokens to CSS variables in index.css so
// the theme can be tuned in one place. Light only.
function rgb(v: string) {
  return `rgb(${v} / <alpha-value>)`;
}

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: rgb("var(--color-canvas)"),
        surface: rgb("var(--color-surface)"),
        "surface-2": rgb("var(--color-surface-2)"),
        ink: rgb("var(--color-ink)"),
        muted: rgb("var(--color-muted)"),
        border: rgb("var(--color-border)"),
        "border-strong": rgb("var(--color-border-strong)"),
        primary: {
          DEFAULT: rgb("var(--color-primary)"),
          hover: rgb("var(--color-primary-hover)"),
        },
        accent: {
          DEFAULT: rgb("var(--color-accent)"),
          soft: rgb("var(--color-accent-soft)"),
        },
        danger: {
          DEFAULT: rgb("var(--color-danger)"),
          soft: rgb("var(--color-danger-soft)"),
        },
        warning: {
          DEFAULT: rgb("var(--color-warning)"),
          soft: rgb("var(--color-warning-soft)"),
        },
        success: {
          DEFAULT: rgb("var(--color-success)"),
          soft: rgb("var(--color-success-soft)"),
        },
        // Severity-only palette (reserved for severity; never brand/selection).
        sev: {
          critical: rgb("var(--color-sev-critical)"),
          "critical-soft": rgb("var(--color-sev-critical-soft)"),
          high: rgb("var(--color-sev-high)"),
          "high-soft": rgb("var(--color-sev-high-soft)"),
          medium: rgb("var(--color-sev-medium)"),
          "medium-soft": rgb("var(--color-sev-medium-soft)"),
          low: rgb("var(--color-sev-low)"),
          "low-soft": rgb("var(--color-sev-low-soft)"),
        },
      },
      borderRadius: {
        sm: "var(--radius-sm)",
        md: "var(--radius-md)",
        lg: "var(--radius-lg)",
        xl: "var(--radius-xl)",
      },
      boxShadow: {
        card: "var(--shadow-card)",
        pop: "var(--shadow-pop)",
      },
      fontFamily: {
        sans: ['"Instrument Sans"', '"DM Sans"', "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

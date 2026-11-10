/** Design tokens for the HomeAI Cloud safety console (light only).
 *
 * Brand color (deep blue) is reserved for primary actions + selection.
 * Severity colors are reserved for severity only — never brand/selection.
 * Tailwind handles the bulk of styling; these tokens cover the semantic
 * mappings (severity, status) that Tailwind classes alone can't.
 */

export type Severity = "critical" | "high" | "medium" | "low" | "info";
// C2's alert statuses are open | acknowledged | resolved | false_positive (contract §3);
// "new" is kept for existing callers.
export type AlertStatus = "open" | "new" | "acknowledged" | "resolved" | "false_positive";
export type ClipStatus = "uploaded" | "classifying" | "classified" | "failed";

export const SEVERITY_LABEL: Record<Severity, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
  info: "Info",
};

/** Severity-only palette (reserved for severity; never brand/selection). */
export const SEVERITY_CLASSES: Record<Severity, string> = {
  critical: "bg-sev-critical-soft text-sev-critical border-sev-critical/30",
  high: "bg-sev-high-soft text-sev-high border-sev-high/30",
  medium: "bg-sev-medium-soft text-sev-medium border-sev-medium/30",
  low: "bg-sev-low-soft text-sev-low border-sev-low/30",
  info: "bg-surface-2 text-muted border-border",
};

/** Edge-bar fill for a severity (used on alert rows / timeline ticks). */
export const SEVERITY_BAR: Record<Severity, string> = {
  critical: "bg-sev-critical",
  high: "bg-sev-high",
  medium: "bg-sev-medium",
  low: "bg-sev-low",
  info: "bg-border-strong",
};

/** Raw severity hex (for inline styles, e.g. SVG ticks). */
export const SEVERITY_HEX: Record<Severity, string> = {
  critical: "#C0262D",
  high: "#D9730D",
  medium: "#B58A00",
  low: "#5B7A99",
  info: "#94A3B8",
};

export const STATUS_LABEL: Record<AlertStatus, string> = {
  open: "Open",
  new: "New",
  acknowledged: "Acknowledged",
  resolved: "Resolved",
  false_positive: "False Positive",
};

/** Status chips stay neutral/muted — not brand blue. Only resolved leans success. */
export const STATUS_CLASSES: Record<AlertStatus, string> = {
  open: "bg-surface-2 text-ink border-border-strong",
  new: "bg-surface-2 text-ink border-border-strong",
  acknowledged: "bg-warning-soft text-warning border-warning/30",
  resolved: "bg-success-soft text-success border-success/30",
  false_positive: "bg-surface-2 text-muted border-border",
};

export const CLIP_STATUS_LABEL: Record<ClipStatus, string> = {
  uploaded: "Uploaded",
  classifying: "Classifying",
  classified: "Classified",
  failed: "Failed",
};

export const CLIP_STATUS_CLASSES: Record<ClipStatus, string> = {
  uploaded: "bg-surface-2 text-muted border-border",
  classifying: "bg-surface-2 text-ink border-border-strong",
  classified: "bg-success-soft text-success border-success/30",
  failed: "bg-danger-soft text-danger border-danger/30",
};

/**
 * Shared class fragments. Use these instead of one-off hard-coded classes
 * so the safety-console theme stays consistent across pages.
 */
export const COLORS = {
  border: "border-border",
  surface: "bg-surface",
  surface2: "bg-surface-2",
  muted: "text-muted",
  text: "text-ink",
  primary: "bg-primary text-white",
  primaryHover: "hover:bg-primary-hover",
  accent: "bg-accent text-white",
  accentSoft: "bg-accent-soft text-accent",
} as const;

/** Standard surface card: white panel on the canvas background. */
export const CARD = "rounded-xl border border-border bg-surface shadow-card";

/** Input control baseline — pairs with the global focus-visible ring. */
export const INPUT =
  "rounded-md border border-border-strong bg-surface px-3 py-2 text-sm text-ink placeholder:text-muted";

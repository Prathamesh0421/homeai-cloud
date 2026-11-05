/** Design tokens for the HomeAI Cloud UI kit.
 *
 * Centralises colours, severity, and status maps so chips/badges/KPI tiles
 * stay consistent across feature pages. Tailwind handles the bulk of styling;
 * these tokens cover the semantic mappings that Tailwind classes alone can't.
 */

export type Severity = "critical" | "high" | "medium" | "low" | "info";
export type AlertStatus = "new" | "acknowledged" | "resolved" | "false_positive";
export type ClipStatus = "uploaded" | "classifying" | "classified" | "failed";

export const SEVERITY_LABEL: Record<Severity, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
  info: "Info",
};

/** Tailwind class fragments for each severity badge. */
export const SEVERITY_CLASSES: Record<Severity, string> = {
  critical: "bg-red-100 text-red-800 border-red-200",
  high: "bg-orange-100 text-orange-800 border-orange-200",
  medium: "bg-amber-100 text-amber-800 border-amber-200",
  low: "bg-sky-100 text-sky-800 border-sky-200",
  info: "bg-slate-100 text-slate-700 border-slate-200",
};

export const STATUS_LABEL: Record<AlertStatus, string> = {
  new: "New",
  acknowledged: "Acknowledged",
  resolved: "Resolved",
  false_positive: "False Positive",
};

export const STATUS_CLASSES: Record<AlertStatus, string> = {
  new: "bg-blue-100 text-blue-800 border-blue-200",
  acknowledged: "bg-violet-100 text-violet-800 border-violet-200",
  resolved: "bg-emerald-100 text-emerald-800 border-emerald-200",
  false_positive: "bg-slate-100 text-slate-600 border-slate-200",
};

export const CLIP_STATUS_LABEL: Record<ClipStatus, string> = {
  uploaded: "Uploaded",
  classifying: "Classifying",
  classified: "Classified",
  failed: "Failed",
};

export const CLIP_STATUS_CLASSES: Record<ClipStatus, string> = {
  uploaded: "bg-slate-100 text-slate-700 border-slate-200",
  classifying: "bg-blue-100 text-blue-800 border-blue-200",
  classified: "bg-emerald-100 text-emerald-800 border-emerald-200",
  failed: "bg-red-100 text-red-800 border-red-200",
};

export const COLORS = {
  border: "border-slate-200",
  surface: "bg-white",
  muted: "text-slate-500",
  text: "text-slate-800",
  primary: "bg-slate-900 text-white",
  primaryHover: "hover:bg-slate-700",
} as const;

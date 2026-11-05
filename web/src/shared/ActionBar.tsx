/** ActionBar: row of buttons (e.g. Create / Cancel). */

import type { ReactNode } from "react";

export function ActionBar({ children }: { children: ReactNode }) {
  return <div className="flex items-center gap-2">{children}</div>;
}

export interface ButtonProps {
  children: ReactNode;
  onClick?: () => void;
  type?: "button" | "submit" | "reset";
  variant?: "primary" | "secondary" | "danger" | "ghost";
  disabled?: boolean;
}

const VARIANTS: Record<NonNullable<ButtonProps["variant"]>, string> = {
  primary: "bg-slate-900 text-white hover:bg-slate-700 disabled:opacity-50",
  secondary: "border border-slate-300 text-slate-700 hover:bg-slate-50 disabled:opacity-50",
  danger: "bg-red-600 text-white hover:bg-red-500 disabled:opacity-50",
  ghost: "text-slate-600 hover:bg-slate-100 disabled:opacity-50",
};

export function Button({ children, onClick, type = "button", variant = "primary", disabled }: ButtonProps) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`rounded px-3 py-1.5 text-sm font-medium ${VARIANTS[variant]}`}
    >
      {children}
    </button>
  );
}

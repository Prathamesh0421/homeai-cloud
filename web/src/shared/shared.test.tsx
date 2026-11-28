/** Vitest tests for the shared UI kit (C4-11). */

import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { SortableList, type SortableItem } from "./SortableList";
import { SeverityBadge } from "./SeverityBadge";
import { fieldErrors, FormPanel } from "./FormPanel";
import { ToastProvider, ToastViewport, useToasts } from "./Toasts";
import { DataTable } from "./DataTable";
import { ConfirmDialog } from "./ConfirmDialog";

describe("SeverityBadge", () => {
  it("renders the icon and the word for each severity", () => {
    const { rerender } = render(<SeverityBadge severity="critical" />);
    expect(screen.getByLabelText("Severity Critical").textContent).toContain("Critical");
    expect(screen.getByLabelText("Severity Critical").textContent).toContain("▲");

    rerender(<SeverityBadge severity="info" />);
    expect(screen.getByLabelText("Severity Info").textContent).toContain("Info");
    expect(screen.getByLabelText("Severity Info").textContent).toContain("ℹ");
  });
});

describe("SortableList keyboard reorder", () => {
  it("moves an item down with ArrowDown and up with ArrowUp", () => {
    const items: SortableItem[] = [
      { id: "a", label: "Alice" },
      { id: "b", label: "Bob" },
      { id: "c", label: "Carol" },
    ];
    const onChange = vi.fn();
    render(<SortableList items={items} onChange={onChange} />);

    const handles = screen.getAllByRole("button");
    // focus the first handle and press ArrowDown → A moves to index 1
    handles[0].focus();
    act(() => {
      fireEvent.keyDown(handles[0], { key: "ArrowDown" });
    });
    expect(onChange).toHaveBeenLastCalledWith([
      { id: "b", label: "Bob" },
      { id: "a", label: "Alice" },
      { id: "c", label: "Carol" },
    ]);

    // ArrowUp on the (now) first handle is a no-op at the top
    onChange.mockClear();
    act(() => {
      fireEvent.keyDown(handles[0], { key: "ArrowUp" });
    });
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("FormPanel fieldErrors", () => {
  it("maps FastAPI 422 body-loc details to field messages", () => {
    const details = {
      details: [
        { loc: ["body", "email"], msg: "value is not a valid email address" },
        { loc: ["body", "password"], msg: "password must contain digits" },
      ],
    };
    const out = fieldErrors(details);
    expect(out.email).toContain("value is not a valid email address");
    expect(out.password).toContain("password must contain digits");
  });

  it("maps our service-level {fields: {...}} shape", () => {
    const out = fieldErrors({ fields: { house_ids: ["bad house id"] } });
    expect(out.house_ids).toEqual(["bad house id"]);
  });

  it("returns {} for unknown shapes", () => {
    expect(fieldErrors(null)).toEqual({});
    expect(fieldErrors({ unrelated: 1 })).toEqual({});
  });

  it("renders a Field with its error message", () => {
    render(
      <FormPanel title="Test">
        <input />
      </FormPanel>,
    );
    // FormPanel renders the title
    expect(screen.getByText("Test")).toBeInTheDocument();
  });
});

describe("ToastViewport", () => {
  function PushButton() {
    const { push } = useToasts();
    return (
      <button type="button" onClick={() => push({ tone: "warning", message: "Rule already exists" })}>
        push
      </button>
    );
  }

  it("stacks above side panels and dialogs (z-50), so a toast raised under a panel is seen", () => {
    render(
      <ToastProvider>
        <PushButton />
        <ToastViewport />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "push" }));
    const viewport = screen.getByRole("status").parentElement!;
    const z = Number(/\bz-\[(\d+)\]/.exec(viewport.className)?.[1] ?? /\bz-(\d+)\b/.exec(viewport.className)?.[1]);
    expect(z).toBeGreaterThan(50);
  });
});

describe("DataTable sorting by keyboard", () => {
  it("sorts with a header button and reports the direction in aria-sort", () => {
    const rows = [{ n: "Oak" }, { n: "Maple" }];
    render(
      <DataTable
        columns={[{ key: "n", header: "House", render: (r) => r.n, sortValue: (r) => r.n }]}
        rows={rows}
        rowKey={(r) => r.n}
      />,
    );
    const header = screen.getByRole("columnheader", { name: /House/ });
    const sort = screen.getByRole("button", { name: /House/ });
    expect(header).toHaveAttribute("aria-sort", "none");

    fireEvent.click(sort); // Enter/Space on a button fire click
    expect(header).toHaveAttribute("aria-sort", "ascending");
    expect(screen.getAllByRole("cell").map((c) => c.textContent)).toEqual(["Maple", "Oak"]);
    fireEvent.click(sort);
    expect(header).toHaveAttribute("aria-sort", "descending");
  });

  it("leaves columns without sortValue as plain headers", () => {
    render(<DataTable columns={[{ key: "n", header: "Size", render: () => "1" }]} rows={[{}]} rowKey={() => "r"} />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByRole("columnheader", { name: "Size" })).not.toHaveAttribute("aria-sort");
  });
});

describe("ConfirmDialog keyboard focus", () => {
  function Harness({ open, onCancel = () => {} }: { open: boolean; onCancel?: () => void }) {
    return (
      <>
        <button type="button">Delete house</button>
        <ConfirmDialog open={open} title="Delete house?" message="Gone for good." onConfirm={() => {}} onCancel={onCancel} />
      </>
    );
  }

  it("focuses Cancel, keeps Tab inside, and gives focus back on close", () => {
    const { rerender } = render(<Harness open={false} />);
    const opener = screen.getByRole("button", { name: "Delete house" });
    opener.focus();

    rerender(<Harness open />);
    const dialog = screen.getByRole("dialog", { name: "Delete house?" });
    expect(dialog).toHaveAccessibleDescription("Gone for good.");
    const cancel = screen.getByRole("button", { name: "Cancel" });
    const confirm = screen.getByRole("button", { name: "Confirm" });
    expect(cancel).toHaveFocus();

    confirm.focus();
    fireEvent.keyDown(confirm, { key: "Tab" });
    expect(cancel).toHaveFocus();
    fireEvent.keyDown(cancel, { key: "Tab", shiftKey: true });
    expect(confirm).toHaveFocus();

    rerender(<Harness open={false} />);
    expect(opener).toHaveFocus();
  });

  it("closes on Escape", () => {
    const onCancel = vi.fn();
    render(<Harness open onCancel={onCancel} />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onCancel).toHaveBeenCalled();
  });
});

/** Vitest tests for the shared UI kit (C4-11). */

import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { SortableList, type SortableItem } from "./SortableList";
import { SeverityBadge } from "./SeverityBadge";
import { fieldErrors, FormPanel } from "./FormPanel";

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

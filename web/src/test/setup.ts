import "@testing-library/jest-dom/vitest";

// Radix UI (Select, Popover, etc.) calls these in jsdom; provide no-op stubs.
window.HTMLElement.prototype.hasPointerCapture = () => true;
window.HTMLElement.prototype.releasePointerCapture = () => {};
window.HTMLElement.prototype.setPointerCapture = () => {};
window.HTMLElement.prototype.scrollIntoView = () => {};

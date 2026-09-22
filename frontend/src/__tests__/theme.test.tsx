import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { THEME_STORAGE_KEY, ThemeProvider, ThemeToggle } from "../theme";

beforeEach(() => { localStorage.clear(); delete document.documentElement.dataset.theme; });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const mount = () => render(<ThemeProvider><ThemeToggle /></ThemeProvider>);

it("defaults to light and persists an explicit dark selection across remounts", () => {
  const first = mount();
  expect(document.documentElement.dataset.theme).toBe("light");
  expect(document.documentElement.style.colorScheme).toBe("light");
  fireEvent.click(screen.getByRole("button", { name: "切换到深色模式" }));
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
  first.unmount();
  mount();
  expect(screen.getByRole("button", { name: "切换到浅色模式" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "切换到浅色模式" }));
  expect(document.documentElement.dataset.theme).toBe("light");
});

it("synchronizes a preference changed in another tab", () => {
  localStorage.setItem(THEME_STORAGE_KEY, "dark");
  mount();
  localStorage.setItem(THEME_STORAGE_KEY, "light");
  act(() => window.dispatchEvent(new StorageEvent("storage", { key: THEME_STORAGE_KEY, newValue: "light" })));
  expect(document.documentElement.dataset.theme).toBe("light");
});

it("allows switching when storage is unavailable", () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
  mount();
  expect(document.documentElement.dataset.theme).toBe("light");
  fireEvent.click(screen.getByRole("button", { name: "切换到深色模式" }));
  expect(document.documentElement.dataset.theme).toBe("dark");
});

it("ignores invalid stored preferences", () => {
  localStorage.setItem(THEME_STORAGE_KEY, "invalid");
  mount();
  expect(document.documentElement.dataset.theme).toBe("light");
});

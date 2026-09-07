import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { THEME_STORAGE_KEY, ThemeProvider, ThemeToggle } from "../theme";

beforeEach(() => { localStorage.clear(); delete document.documentElement.dataset.theme; });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const mount = () => render(<ThemeProvider><ThemeToggle /></ThemeProvider>);

it("keeps the existing dark default and persists a light selection across remounts", () => {
  const first = mount();
  expect(document.documentElement.dataset.theme).toBe("dark");
  fireEvent.click(screen.getByRole("button", { name: "切换到浅色模式" }));
  expect(document.documentElement.dataset.theme).toBe("light");
  expect(document.documentElement.style.colorScheme).toBe("light");
  expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
  first.unmount();
  mount();
  expect(screen.getByRole("button", { name: "切换到深色模式" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "切换到深色模式" }));
  expect(document.documentElement.dataset.theme).toBe("dark");
});

it("synchronizes a preference changed in another tab", () => {
  mount();
  localStorage.setItem(THEME_STORAGE_KEY, "light");
  act(() => window.dispatchEvent(new StorageEvent("storage", { key: THEME_STORAGE_KEY, newValue: "light" })));
  expect(document.documentElement.dataset.theme).toBe("light");
});

it("allows switching when storage is unavailable", () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
  mount();
  fireEvent.click(screen.getByRole("button", { name: "切换到浅色模式" }));
  expect(document.documentElement.dataset.theme).toBe("light");
});

it("ignores invalid stored preferences", () => {
  localStorage.setItem(THEME_STORAGE_KEY, "invalid");
  mount();
  expect(document.documentElement.dataset.theme).toBe("dark");
});

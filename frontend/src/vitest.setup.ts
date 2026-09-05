import * as matchers from "@testing-library/jest-dom/matchers";
import { expect } from "vitest";

expect.extend(matchers);

// jsdom does not implement layout-dependent APIs; stub for components that
// auto-scroll (e.g. chat panes calling scrollIntoView on new messages).
if (typeof window !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}

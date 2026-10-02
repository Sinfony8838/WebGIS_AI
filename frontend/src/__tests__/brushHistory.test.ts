import { describe, expect, it } from "vitest";
import { BrushHistory } from "../lib/brushHistory";

describe("PPT brush history", () => {
  it("keeps each page's strokes and lets clear be undone without changing another page", () => {
    const history = new BrushHistory();
    history.commit("1", "stroke A");
    history.commit("1", "strokes A+B");
    history.commit("2", "stroke C");
    expect(history.undo("1")).toBe(true);
    expect(history.image("1")).toBe("stroke A");
    expect(history.image("2")).toBe("stroke C");
    history.commit("1", null);
    expect(history.canUndo("1")).toBe(true);
    history.undo("1");
    expect(history.image("1")).toBe("stroke A");
    history.undo("1");
    expect(history.image("1")).toBeNull();
    expect(history.undo("1")).toBe(false);
    expect(history.image("2")).toBe("stroke C");
  });

  it("shares a bounded undo budget across pages and never erases a page with no retained undo", () => {
    const history = new BrushHistory(30);
    for (let page = 0; page < 40; page++) history.commit(String(page), `ink ${page}`);
    expect(history.retainedSteps).toBe(30);
    expect(history.canUndo("0")).toBe(false);
    expect(history.undo("0")).toBe(false);
    expect(history.image("0")).toBe("ink 0");
    history.undo("39");
    expect(history.image("39")).toBeNull();
    expect(history.retainedSteps).toBe(29);
    history.replace("38", "imported");
    expect(history.canUndo("38")).toBe(false);
    expect(history.retainedSteps).toBe(28);
    history.undo("38");
    expect(history.image("38")).toBe("imported");
  });
});

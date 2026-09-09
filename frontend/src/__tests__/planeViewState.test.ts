import { expect, it, vi } from "vitest";
import View from "ol/View";
import { fromLonLat, transformExtent } from "ol/proj";
import { observePlaneView } from "../lib/planeViewState";

it("tracks real view initialization, Shanghai positioning, and world fitting", () => {
  const view = new View({ center: fromLonLat([104, 35]), zoom: 4 });
  const publish = vi.fn();
  const stop = observePlaneView(view, publish);
  expect(publish.mock.lastCall?.[0].lon).toBeCloseTo(104);
  view.setCenter(fromLonLat([121.5, 31.24]));
  view.setZoom(13.7);
  expect(publish.mock.lastCall?.[0].zoom).toBeCloseTo(13.7);
  expect(publish.mock.lastCall?.[0].lat).toBeCloseTo(31.24);
  view.fit(transformExtent([-170, -55, 170, 75], "EPSG:4326", "EPSG:3857"), { size: [1000, 700] });
  expect(publish.mock.lastCall?.[0].lon).toBeCloseTo(0);
  expect(publish.mock.lastCall?.[0].zoom).toBeLessThan(4);
  stop();
});

it("detaches an old map view and immediately tracks its replacement", () => {
  const oldView = new View({ center: fromLonLat([121.5, 31.24]), zoom: 13.7 });
  const publish = vi.fn();
  const stopOld = observePlaneView(oldView, publish);
  stopOld();
  const currentView = new View({ center: fromLonLat([15, 20]), zoom: 2 });
  const stopCurrent = observePlaneView(currentView, publish);
  const count = publish.mock.calls.length;
  oldView.setZoom(8);
  expect(publish).toHaveBeenCalledTimes(count);
  expect(publish.mock.lastCall?.[0].lon).toBeCloseTo(15);
  currentView.setZoom(3);
  expect(publish.mock.lastCall?.[0].zoom).toBe(3);
  stopCurrent();
  currentView.setZoom(5);
  expect(publish.mock.lastCall?.[0].zoom).toBe(3);
});

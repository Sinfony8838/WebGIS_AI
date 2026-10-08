import { describe, expect, it, vi } from "vitest";
import * as Cesium from "cesium";
import type { LayerRecord } from "../types";
import { GlobeProjectLayers } from "../lib/globeProjectLayers";
import { applyCesiumVectorStyle } from "../lib/vectorStyle";

function layer(patch: Partial<LayerRecord> = {}): LayerRecord {
  return { layer_id: "one", name: "synthetic", kind: "vector", source: "upload", geometry_type: "LineString",
    visible: true, opacity: 1, z_index: 1, style: {}, metadata: {}, data_rev: 1,
    data: { type: "FeatureCollection", features: [{ type: "Feature", properties: { name: "line" },
      geometry: { type: "LineString", coordinates: [[0, 0], [1, 1]] } }] }, ...patch };
}
function source(name = "one") {
  const result = new Cesium.GeoJsonDataSource(name);
  result.entities.add({ id: name, point: {}, properties: { name, __fillColor: "#ff0000" } });
  return result;
}
function deferred<T>() {
  let resolve!: (value: T) => void; let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
async function flush() { for (let i = 0; i < 12; i++) await Promise.resolve(); }
function setup(loader = vi.fn(async (_data: Record<string, unknown>) => source())) {
  let destroyed = false;
  const dataSources = new Cesium.DataSourceCollection();
  const errors = vi.fn(); const apply = vi.fn(applyCesiumVectorStyle);
  const host = { dataSources, scene: { requestRender: vi.fn() } as unknown as Cesium.Scene, isDestroyed: () => destroyed };
  const manager = new GlobeProjectLayers(host, errors, loader, apply);
  return { manager, loader, apply, dataSources, errors, host, destroyHost: () => { destroyed = true; dataSources.destroy(); } };
}

describe("project vector revision reconciliation", () => {
  it("parses once across ten fresh snapshots and keeps the actual Cesium source", async () => {
    const t = setup(); t.manager.sync("A", [layer()], true); await flush();
    const original = t.dataSources.get(0);
    for (let i = 0; i < 10; i++) { t.manager.sync("A", [JSON.parse(JSON.stringify(layer()))], true); await flush(); }
    expect(t.loader).toHaveBeenCalledTimes(1); expect(t.apply).toHaveBeenCalledTimes(1);
    expect(t.dataSources.length).toBe(1); expect(t.dataSources.get(0)).toBe(original);
  });
  it("updates style/opacity/zero in place without parsing", async () => {
    const t = setup(); t.manager.sync("A", [layer()], true); await flush();
    const original = t.dataSources.get(0) as Cesium.GeoJsonDataSource;
    t.manager.sync("A", [layer({ style: { radius: 0, fillOpacity: 0, strokeWidth: 0 }, opacity: 0 })], true); await flush();
    expect(t.loader).toHaveBeenCalledTimes(1); expect(t.dataSources.get(0)).toBe(original);
    const point = original.entities.getById("one")!.point!;
    expect(point.pixelSize!.getValue()).toBe(0); expect(point.color!.getValue().alpha).toBe(0);
    expect(point.outlineWidth!.getValue()).toBe(0);
  });
  it("updates catalog-dependent styles without parsing", async () => {
    const t = setup(); t.manager.sync("A", [layer()], true); await flush();
    t.manager.sync("A", [layer({ metadata: { catalog_id: "shanghai_population_density" } })], true); await flush();
    expect(t.loader).toHaveBeenCalledTimes(1); expect(t.apply).toHaveBeenCalledTimes(2);
  });
  it("retains source identity across layer visibility toggles", async () => {
    const t = setup(); t.manager.sync("A", [layer()], true); await flush();
    const original = t.dataSources.get(0);
    t.manager.sync("A", [layer({ visible: false })], true); await flush(); expect(original.show).toBe(false);
    t.manager.sync("A", [layer()], true); await flush();
    expect(original.show).toBe(true); expect(t.loader).toHaveBeenCalledTimes(1);
  });
  it("defers initially disabled layers", async () => {
    const t = setup(); t.manager.sync("A", [layer({ visible: false })], true); await flush();
    expect(t.loader).not.toHaveBeenCalled();
    t.manager.sync("A", [layer()], true); await flush(); expect(t.loader).toHaveBeenCalledTimes(1);
  });
  it("replaces only changed geometry revisions and releases the old entities", async () => {
    const t = setup(vi.fn(async data => source(String(data.tag || "one"))));
    const two = layer({ layer_id: "two", data: { tag: "two" } });
    t.manager.sync("A", [layer(), two], true); await flush();
    const old = t.dataSources.get(0) as Cesium.GeoJsonDataSource; const unchanged = t.dataSources.get(1);
    t.manager.sync("A", [layer({ data_rev: 2 }), two], true); await flush();
    expect(t.loader).toHaveBeenCalledTimes(3); expect(old.entities.values).toHaveLength(0);
    expect(t.dataSources.contains(unchanged)).toBe(true); expect(t.dataSources.length).toBe(2);
  });
  it("detects changed legacy data without revision", async () => {
    const t = setup(); t.manager.sync("A", [layer({ data_rev: undefined })], true); await flush();
    t.manager.sync("A", [layer({ data_rev: undefined })], true); await flush();
    expect(t.loader).toHaveBeenCalledTimes(1);
    t.manager.sync("A", [layer({ data_rev: undefined, data: { features: [] } })], true); await flush();
    expect(t.loader).toHaveBeenCalledTimes(2);
  });
  it("does not serialize revisioned geometry to compare snapshots", async () => {
    const t = setup(); const stringify = vi.fn(() => { throw new Error("must not serialize geometry"); });
    const data = { ...layer().data, toJSON: stringify };
    t.manager.sync("A", [layer({ data })], true); await flush();
    t.manager.sync("A", [layer({ data: { ...data } })], true); await flush();
    expect(stringify).not.toHaveBeenCalled(); expect(t.loader).toHaveBeenCalledTimes(1);
  });
  it("coalesces ten hidden updates and loads only the latest on re-show", async () => {
    const t = setup();
    for (let i = 1; i <= 10; i++) t.manager.sync("A", [layer({ data_rev: i, data: { revision: i } })], false);
    await flush(); expect(t.loader).not.toHaveBeenCalled(); expect(t.apply).not.toHaveBeenCalled();
    t.manager.sync("A", [layer({ data_rev: 10, data: { revision: 10 } })], true); await flush();
    expect(t.loader.mock.calls).toEqual([[{ revision: 10 }]]); expect(t.dataSources.length).toBe(1);
  });
  it("keeps warm geometry and postpones hidden style work", async () => {
    const t = setup(); t.manager.sync("A", [layer()], true); await flush();
    const old = t.dataSources.get(0);
    t.manager.sync("A", [layer({ style: { radius: 20 } })], false); await flush();
    expect(old.show).toBe(false); expect(t.apply).toHaveBeenCalledTimes(1);
    t.manager.sync("A", [layer({ style: { radius: 20 } })], true); await flush();
    expect(t.dataSources.get(0)).toBe(old); expect(t.loader).toHaveBeenCalledTimes(1);
    expect(t.apply).toHaveBeenCalledTimes(2); expect(old.show).toBe(true);
  });
  it("never starts a scheduled load after hide", async () => {
    const t = setup(); t.manager.sync("A", [layer()], true); t.manager.sync("A", [layer()], false); await flush();
    expect(t.loader).not.toHaveBeenCalled();
    t.manager.sync("A", [layer()], true); await flush(); expect(t.loader).toHaveBeenCalledTimes(1);
  });
  it("holds an in-flight parse unattached while hidden and reuses it with latest style", async () => {
    const wait = deferred<Cesium.GeoJsonDataSource>(); const t = setup(vi.fn(() => wait.promise));
    t.manager.sync("A", [layer()], true); await flush();
    t.manager.sync("A", [layer({ style: { radius: 22 } })], false);
    const result = source(); wait.resolve(result); await flush();
    expect(t.dataSources.length).toBe(0); expect(t.apply).not.toHaveBeenCalled();
    t.manager.sync("A", [layer({ style: { radius: 22 } })], true); await flush();
    expect(t.loader).toHaveBeenCalledTimes(1); expect(t.dataSources.get(0)).toBe(result);
    expect(result.entities.getById("one")!.point!.pixelSize!.getValue()).toBe(44);
  });
  it("discards a completed hidden parse superseded by new geometry", async () => {
    const wait = deferred<Cesium.GeoJsonDataSource>();
    const t = setup(vi.fn().mockImplementationOnce(() => wait.promise).mockImplementation(async () => source("new")));
    t.manager.sync("A", [layer()], true); await flush(); t.manager.sync("A", [layer({ data_rev: 2 })], false);
    const old = source(); wait.resolve(old); await flush();
    t.manager.sync("A", [layer({ data_rev: 2 })], true); await flush();
    expect(old.entities.values).toHaveLength(0); expect(t.loader).toHaveBeenCalledTimes(2); expect(t.dataSources.length).toBe(1);
  });
  it.each(["actor-A/project-B", "actor-B/project-A"])("isolates repeated IDs/revisions across %s", async scope => {
    const t = setup(); t.manager.sync("actor-A/project-A", [layer()], true); await flush();
    const old = t.dataSources.get(0) as Cesium.GeoJsonDataSource;
    t.manager.sync(scope, [layer()], true); await flush();
    expect(t.loader).toHaveBeenCalledTimes(2); expect(t.dataSources.contains(old)).toBe(false); expect(old.entities.values).toHaveLength(0);
  });
  it("rejects a late parse after A → B → A", async () => {
    const wait = deferred<Cesium.GeoJsonDataSource>();
    const t = setup(vi.fn().mockImplementationOnce(() => wait.promise).mockImplementation(async () => source("current")));
    t.manager.sync("A", [layer()], true); await flush(); t.manager.sync("B", [], true);
    t.manager.sync("A", [layer()], true); await flush();
    const old = source("old"); wait.resolve(old); await flush();
    expect(t.dataSources.contains(old)).toBe(false); expect(old.entities.values).toHaveLength(0); expect(t.dataSources.length).toBe(1);
  });
  it("uses latest styles after a slow parse", async () => {
    const wait = deferred<Cesium.GeoJsonDataSource>(); const t = setup(vi.fn(() => wait.promise));
    t.manager.sync("A", [layer()], true); await flush(); t.manager.sync("A", [layer({ style: { radius: 30 } })], true);
    const result = source(); wait.resolve(result); await flush();
    expect(result.entities.getById("one")!.point!.pixelSize!.getValue()).toBe(60);
  });
  it.each(["remove", "hide", "destroy"])("guards asynchronous Cesium add during %s", async action => {
    const t = setup(); const add = t.dataSources.add.bind(t.dataSources); const wait = deferred<void>();
    vi.spyOn(t.dataSources, "add").mockImplementation(async data => { await wait.promise; return add(data); });
    t.manager.sync("A", [layer()], true); await flush();
    if (action === "destroy") t.manager.destroy();
    else t.manager.sync("A", action === "remove" ? [] : [layer()], action !== "hide");
    wait.resolve(); await flush();
    if (action === "hide") {
      expect(t.dataSources.get(0).show).toBe(false);
      t.manager.sync("A", [layer()], true); await flush(); expect(t.dataSources.get(0).show).toBe(true);
    } else expect(t.dataSources.length).toBe(0);
    expect(t.loader).toHaveBeenCalledTimes(1);
  });
  it("preserves urban/thematic sources on removal and teardown", async () => {
    const t = setup(); const external = source("external"); await t.dataSources.add(external);
    t.manager.sync("A", [layer()], true); await flush(); t.manager.sync("A", [], true);
    expect(t.dataSources.length).toBe(1);
    t.manager.sync("A", [layer()], true); await flush(); t.manager.destroy(); t.manager.destroy();
    expect(t.dataSources.length).toBe(1); expect(t.dataSources.get(0)).toBe(external); expect(external.entities.values).toHaveLength(1);
  });
  it("reconciles z-index without parsing", async () => {
    const t = setup(vi.fn(async data => source(String(data.tag))));
    const one = layer({ data: { tag: "one" }, z_index: 1 }); const two = layer({ layer_id: "two", data: { tag: "two" }, z_index: 2 });
    t.manager.sync("A", [one, two], true); await flush(); expect(t.dataSources.get(1).name).toBe("two");
    t.manager.sync("A", [{ ...one, z_index: 3 }, two], true); await flush();
    expect(t.dataSources.get(1).name).toBe("one"); expect(t.loader).toHaveBeenCalledTimes(2);
  });
  it("removes records no longer in the imported/output vector scope", async () => {
    const t = setup(); t.manager.sync("A", [layer()], true); await flush();
    t.manager.sync("A", [layer({ source: "template" })], true); await flush();
    expect(t.dataSources.length).toBe(0); expect(t.loader).toHaveBeenCalledTimes(1);
  });
  it.each(["load", "style", "add"])("cleans up %s failures and retries only on a later snapshot", async failure => {
    const t = setup();
    if (failure === "load") t.loader.mockRejectedValueOnce(new Error("synthetic parse"));
    if (failure === "style") t.apply.mockImplementationOnce(() => { throw new Error("synthetic style"); });
    if (failure === "add") vi.spyOn(t.dataSources, "add").mockRejectedValueOnce(new Error("synthetic add"));
    t.manager.sync("A", [layer()], true); await flush();
    expect(t.errors).toHaveBeenCalledTimes(1); expect(t.dataSources.length).toBe(0); expect(t.loader).toHaveBeenCalledTimes(1);
    t.manager.sync("A", [layer()], true); await flush(); expect(t.dataSources.length).toBe(1); expect(t.loader).toHaveBeenCalledTimes(2);
  });
  it("suppresses hidden and stale errors", async () => {
    const wait = deferred<Cesium.GeoJsonDataSource>(); const t = setup(vi.fn(() => wait.promise));
    t.manager.sync("A", [layer()], true); await flush(); t.manager.sync("A", [layer()], false);
    wait.reject(new Error("hidden")); await flush(); expect(t.errors).not.toHaveBeenCalled();
    const old = deferred<Cesium.GeoJsonDataSource>(); t.loader.mockImplementationOnce(() => old.promise);
    t.manager.sync("A", [layer()], true); await flush(); t.manager.sync("B", [], true);
    old.reject(new Error("stale")); await flush(); expect(t.errors).not.toHaveBeenCalled();
  });
  it("releases late parsing after manager and viewer teardown", async () => {
    const wait = deferred<Cesium.GeoJsonDataSource>(); const t = setup(vi.fn(() => wait.promise));
    t.manager.sync("A", [layer()], true); await flush(); t.manager.destroy(); t.destroyHost();
    const old = source(); wait.resolve(old); await flush(); expect(old.entities.values).toHaveLength(0); expect(t.errors).not.toHaveBeenCalled();
    t.manager.sync("A", [layer()], true); expect(t.loader).toHaveBeenCalledTimes(1);
  });
  it("runs the real Cesium parser and retains EPSG:4979 coordinates without editing input", async () => {
    const dataSources = new Cesium.DataSourceCollection(); const errors = vi.fn();
    const manager = new GlobeProjectLayers({ dataSources, isDestroyed: () => false, scene: { requestRender() {} } as unknown as Cesium.Scene }, errors);
    const original = layer(); original.data = { ...original.data, crs: { properties: { name: "EPSG:4979" } } };
    manager.sync("synthetic", [original], true); await vi.waitFor(() => expect(dataSources.length).toBe(1));
    const positions = (dataSources.get(0) as Cesium.GeoJsonDataSource).entities.values[0].polyline!.positions!.getValue();
    expect(positions).toHaveLength(2); expect(Cesium.Cartesian3.equalsEpsilon(positions[1], Cesium.Cartesian3.fromDegrees(1, 1), 1e-10)).toBe(true);
    expect(original.data.crs).toEqual({ properties: { name: "EPSG:4979" } }); expect(errors).not.toHaveBeenCalled(); manager.destroy();
  });
});

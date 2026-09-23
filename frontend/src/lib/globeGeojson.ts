/** Cesium treats WGS84 3D coordinates as ordinary lon/lat/height but rejects QGIS's EPSG:4979 URN. */
export function normalizeGlobeGeoJson(data: Record<string, unknown>): Record<string, unknown> {
  const crs = data.crs as { properties?: { name?: unknown } } | undefined;
  const name = crs?.properties?.name;
  if (typeof name !== "string" || !/^(?:urn:ogc:def:crs:EPSG::4979|EPSG:4979)$/i.test(name)) return data;
  const normalized = { ...data };
  delete normalized.crs;
  return normalized;
}

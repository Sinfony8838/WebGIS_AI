import Feature from "ol/Feature";
import LineString from "ol/geom/LineString";
import VectorSource from "ol/source/Vector";
import {fromLonLat} from "ol/proj";
import {Style, Stroke, Text, Fill} from "ol/style";
import type {MeasurementRecord} from "../types";

/** One command for manual Draw completion and acknowledged assistant actions. */
export function applyMeasurement(source: VectorSource, record: MeasurementRecord, drawnFeature?: Feature) {
  const existing = source.getFeatures().find(f => f.get("measure_record_id") === record.id);
  const feature = existing || drawnFeature || new Feature(new LineString((record.displayCoordinates || record.coordinates).map(p => fromLonLat(p))));
  feature.set("measure_record_id", record.id);
  feature.setStyle(new Style({stroke: new Stroke({color: record.color, width: 3}),
    text: new Text({text: `${record.name} · ${record.totalKm.toFixed(2)} km`, placement: "line", font: "13px sans-serif",
      fill: new Fill({color: "#17304c"}), stroke: new Stroke({color: "white", width: 4})})}));
  if (!existing && !drawnFeature) source.addFeature(feature);
  return feature;
}

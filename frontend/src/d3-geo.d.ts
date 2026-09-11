declare module "d3-geo" {
  export interface GeoProjection {
    translate(point: [number, number]): GeoProjection;
    scale(value: number): GeoProjection;
    clipAngle(value: number): GeoProjection;
    precision(value: number): GeoProjection;
    rotate(angles: [number, number, number]): GeoProjection;
  }

  export interface GeoPathGenerator {
    (object: unknown): string | null;
  }

  export interface GeoGraticuleGenerator {
    (): unknown;
    step(value: [number, number]): GeoGraticuleGenerator;
  }

  export function geoOrthographic(): GeoProjection;
  export function geoPath(projection: GeoProjection): GeoPathGenerator;
  export function geoGraticule(): GeoGraticuleGenerator;
}

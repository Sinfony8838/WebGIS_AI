# One-map data and cartographic quality policy

## Rendering gate

A catalog item is renderable only when all of the following are present:

- `status: ready`;
- source name, source URL, source year, and licence;
- a valid local source file.

The backend enforces this rule for both direct catalog loading and the 3D
globe. Items retained for future acquisition remain searchable in the catalog,
but cannot be turned into a classroom layer.

## Current approved layers

| Theme | Geometry | Attribute source | Cartographic rule |
| --- | --- | --- | --- |
| China province population / density | Province polygons | 2020 Seventh National Population Census; Taiwan, Hong Kong and Macao benchmark statistics | Density uses fixed thresholds: 10, 100, 400, 800 persons/km². |
| Shanghai district population / density | District polygons | DataV boundary plus 2020 census benchmark table | Use density as a polygon choropleth, not as a bubble map. |
| World countries, population, cities, ports | Natural Earth vectors | Natural Earth public-domain data | Use at the data's small-scale resolution only. |
| Hu Huanyong line | Conceptual line between Heihe and Tengchong | Historical geography teaching reference | Explain it as a demographic concept line, never an administrative boundary. |

## Deliberately unavailable until sourced

- Provincial climate polygons: the bundled 9-zone file is a provincial-scale
  estimate and must not represent a climate boundary. Replace with a cited
  raster/derived vector (for example WorldClim 2.1 or a documented
  Köppen-Geiger product), record period, resolution, projection and method.
- Population migration arcs: the bundled four arrows are a schematic, not an
  origin-destination matrix. Replace with a published census flow table and
  geocoded origins/destinations before rendering flow width or totals.
- GDP layers without a source URL: retain as an acquisition lead only until
  the licence, statistical year, administrative unit and boundary source are
  recorded.
- Scanned textbook images: do not overlay them on a geographic canvas without
  projection, datum, control points, source and licence. Keep them as reading
  material instead.

## Display requirements

Every thematic layer should show its source/year in metadata and tooltip or
legend text, use units in the legend, avoid mixing counts with rates, and use
an explicitly stated classification method.  Three-dimensional height views
are exploratory displays; the corresponding 2D choropleth is the reference
for quantitative comparison.

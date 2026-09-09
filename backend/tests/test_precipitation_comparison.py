import json
import unittest
from pathlib import Path


class PrecipitationCatalogTest(unittest.TestCase):
    def test_comparison_preserves_view_and_resets_with_the_next_lesson_scene(self):
        from tests.test_lessons import LessonServiceTest
        runtime, store, project_id = LessonServiceTest.build_runtime(self)
        store.set_view(project_id, {'center': [121.5, 31.2], 'zoom': 12, 'extent': [121.4, 31.1, 121.6, 31.3]})
        runtime.classroom.apply_lesson_scene(project_id, 'lesson_builtin_population_shanghai_world', 'china_explain')
        self.assertNotIn('extent', store.get_project(project_id).view)
        store.set_view(project_id, {'center': [108.5, 38.0], 'zoom': 5.25})
        before = dict(store.get_project(project_id).view)
        response = runtime.add_catalog_dataset_layer(project_id, 'china_precipitation_400mm', preserve_view=True)
        self.assertEqual(response['view'], before)
        self.assertEqual(store.get_project(project_id).view, before)
        self.assertTrue(next(l for l in store.get_project(project_id).layers if l.layer_id == 'generated_hu_line').visible)
        layer = response['layer']
        self.assertEqual(layer['metadata']['source_year'], '1991-2020')
        self.assertEqual(layer['metadata']['style_field'], '')
        self.assertTrue(all(f['properties']['annual_precip_mm'] == 400 for f in layer['data']['features']))
        runtime.classroom.apply_lesson_scene(project_id, 'lesson_builtin_population_shanghai_world', 'world_inquiry')
        self.assertFalse(next(l for l in store.get_project(project_id).layers if l.layer_id == layer['layer_id']).visible)
        # Ordinary catalog loading retains the existing locate-to-layer behavior.
        response = runtime.add_catalog_dataset_layer(project_id, 'china_precipitation_400mm')
        self.assertNotEqual(response['view'], before)

    def test_bundled_contours_have_provenance_and_finite_regional_coordinates(self):
        path = Path(__file__).resolve().parents[1] / 'app/data/builtin/one_map/climate/china_precipitation_400mm.geojson'
        data = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(data['metadata']['resolution_degrees'], 0.25)
        self.assertEqual(data['metadata']['source_md5'], 'd701c717e08ce6ad457c9f4004984d65')
        self.assertGreater(len(data['features']), 1)  # Local branches must not be forced into one line.
        for feature in data['features']:
            self.assertEqual(feature['geometry']['type'], 'LineString')
            for lon, lat in feature['geometry']['coordinates']:
                self.assertTrue(73 <= lon <= 136 and 18 <= lat <= 55)


class PrecipitationGenerationTest(unittest.TestCase):
    def setUp(self):
        # Data-build dependencies are separate from the app runtime requirements.
        try:
            from scripts.build_precipitation_comparison import annual_total, contour_lines
            import numpy as np
        except ImportError:
            self.skipTest('Install scripts/requirements-geodata.txt to verify the offline data builder')
        self.annual_total, self.contour_lines, self.np = annual_total, contour_lines, np

    def test_annual_total_requires_all_months_and_never_fills_missing_cells(self):
        np = self.np
        monthly = np.full((12, 3, 3), 50.0)
        monthly[0, 0, 0] = -99999.99
        monthly[3, 0, 1] = np.nan
        annual = self.annual_total(monthly)
        self.assertEqual(annual[1, 1], 600)
        self.assertTrue(annual.mask[0, 0] and annual.mask[0, 1])
        with self.assertRaises(ValueError):
            self.annual_total(monthly[:11])

    def test_contour_uses_longitude_latitude_and_does_not_bridge_missing_cells(self):
        np = self.np
        lon, lat = np.array([100., 101., 102.]), np.array([40., 39., 38., 37.])
        values = np.ma.array(np.tile([200., 600., 1000.], (4, 1)), mask=False)
        lines = self.contour_lines(lon, lat, values)
        self.assertTrue(lines)
        self.assertTrue(all(abs(x - 100.5) < 1e-9 for line in lines for x, _ in line))
        self.assertEqual(sorted(y for line in lines for _, y in line), [37., 38., 39., 40.])
        values.mask[1, :] = True
        lines = self.contour_lines(lon, lat, values)
        self.assertTrue(all(y <= 38 for line in lines for _, y in line))

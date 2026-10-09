import unittest

from glymorph.font import Cursor, Glyph
from glymorph.transforms import Options, transform_glyph
from tests.parameter_sweep import sweep


class SweepTests(unittest.TestCase):
    def test_zero_baseline_and_combined_match_production_float32(self):
        original = Glyph('木', (((0., 0.), (100., 0.)), ((50., -50.), (50., 50.))))
        data = sweep(original, seed=42, count=2, levels=(0., .15))
        for variant in data['cases'][0]['variants']:
            self.assertEqual(variant['strokes'], original.strokes)
            self.assertTrue(variant['difference']['same_coordinates'])
        combined = data['cases'][3]
        for i, variant in enumerate(combined['variants']):
            expected, _ = transform_glyph(original, Options(**combined['options']), 42, i)
            rounded = Glyph.read(Cursor(expected.encode()))
            self.assertEqual(variant['strokes'], rounded.strokes)

    def test_amplitude_comparison_reuses_same_random_draw_per_path(self):
        original = Glyph('二', (((0., 0.), (100., 0.)), ((0., 200.), (100., 200.))))
        data = sweep(original, seed=42, count=4, levels=(0., .05, .15))
        low, high = data['cases'][3], data['cases'][6]
        for a, b in zip(low['variants'], high['variants']):
            for first, second in zip(a['difference']['path_length_ratios'], b['difference']['path_length_ratios']):
                self.assertAlmostEqual((first-1)/.05, (second-1)/.15, places=5)
        self.assertNotEqual(low['variants'][0]['strokes'], low['variants'][1]['strokes'])


if __name__ == '__main__':
    unittest.main()

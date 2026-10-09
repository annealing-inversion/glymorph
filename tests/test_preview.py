import unittest
from xml.etree import ElementTree as ET

from glymorph.font import Glyph
from glymorph.preview import comparison_svg, glyph_difference


class PreviewTests(unittest.TestCase):
    def test_densification_is_not_geometric_displacement(self):
        original = Glyph('一', (((0., 0.), (100., 0.)),))
        dense = original.with_strokes((tuple((float(i), 0.) for i in range(101)),))
        self.assertNotEqual(original.encode(), dense.encode())
        result = glyph_difference(original, dense)
        self.assertFalse(result['same_coordinates'])
        self.assertAlmostEqual(result['max_sampled_displacement'], 0.)
        self.assertEqual(result['path_length_ratios'], [1.])

    def test_displacement_and_lengths_include_path_interiors(self):
        original = Glyph('二', (((0., 0.), (100., 0.)), ((0., 30.), (100., 30.))))
        variant = original.with_strokes((((-5., 0.), (105., 0.)),
                                         ((0., 30.), (50., 40.), (100., 30.))))
        result = glyph_difference(original, variant)
        self.assertAlmostEqual(result['max_sampled_displacement'], 10.)
        self.assertAlmostEqual(result['max_sampled_displacement_percent'], 10.)
        self.assertAlmostEqual(result['path_length_ratios'][0], 1.1)
        self.assertAlmostEqual(result['path_length_ratios'][1], (1.04)**.5)

    def test_degenerate_and_identity_glyphs(self):
        for original in (Glyph(' ', ()), Glyph('点', (((1., 2.),),))):
            result = glyph_difference(original, original)
            self.assertTrue(result['same_coordinates'])
            self.assertEqual(result['max_sampled_displacement'], 0.)
            self.assertIsNone(result['max_sampled_displacement_percent'])
        dot = Glyph('点', (((1., 2.),),))
        moved = dot.with_strokes((((4., 6.),),))
        self.assertEqual(glyph_difference(dot, moved)['max_sampled_displacement'], 5.)
        self.assertEqual(glyph_difference(dot, moved)['path_length_ratios'], [None])
        with self.assertRaises(ValueError):
            glyph_difference(dot, Glyph('点', ()))

    def test_overlay_uses_shared_coordinates_including_for_global_scaling(self):
        original = Glyph('&', (((0., 0.), (100., 0.)),))
        larger = original.with_strokes((((-10., 0.), (110., 0.)),))
        svg = comparison_svg({'&': original}, [{'&': larger}], '&')
        tree = ET.fromstring(svg)
        paths = {node.attrib['class']: node for node in tree.iter('{http://www.w3.org/2000/svg}polyline')}
        points = lambda kind: [tuple(map(float, p.split(','))) for p in paths[kind].attrib['points'].split()]
        source, reference, variant = points('source'), points('reference'), points('variant')
        for a, b in zip(source, reference):
            self.assertAlmostEqual(b[0]-a[0], 240.)  # Only a column offset.
            self.assertEqual(a[1], b[1])
        self.assertLess(variant[0][0], reference[0][0])
        self.assertGreater(variant[-1][0], reference[-1][0])
        self.assertIn('采样最大位移 10.000%', svg)
        self.assertIn('path 长度比 1.200', svg)
        same = comparison_svg({'&': original}, [{'&': original}], '&')
        self.assertIn('坐标完全相同', same)
        ET.fromstring(comparison_svg({'&': original}, [], '&'))


if __name__ == '__main__':
    unittest.main()

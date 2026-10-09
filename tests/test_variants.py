from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
import math
from pathlib import Path
import random
import struct
import tempfile
import unittest
import zipfile

from glymorph import generate_variants
from glymorph.cli import main
from glymorph.font import Cursor, Font, FontError, Glyph, encode_string
from glymorph.geometry import contact_interval, length
from glymorph.preview import glyph_difference
from glymorph.transforms import Options, plan_length, scale_glyph, transform_glyph


def glyph(char='一', strokes=(((0., 0.), (50., 0.), (100., 0.)),)):
    return Glyph(char, tuple(tuple(s) for s in strokes))


def font_bytes(glyphs, *, name='测试字体', units=600, preview_count=None):
    preview_count = len(glyphs) if preview_count is None else preview_count
    metadata = (struct.pack('>I', 6) + encode_string('xiongzai') + struct.pack('>I', 2)
                + encode_string(name) + encode_string('作者') + encode_string('说明')
                + struct.pack('>III', units, len(glyphs), preview_count))
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.comment = b'preserve me'
        for g in glyphs:
            info = zipfile.ZipInfo(g.char, (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, g.encode())
    return metadata + b''.join(g.encode() for g in glyphs[:preview_count]) + archive_bytes.getvalue()


class FontTests(unittest.TestCase):
    def test_roundtrip_header_metadata_preview_and_coordinates(self):
        g = glyph(strokes=(((0., -0.), (2.25, -8.5)), ((4., 6.),)))
        font = Font.decode(font_bytes([g]))
        decoded = Font.decode(font.encode())
        self.assertEqual(font.header, decoded.header)
        self.assertEqual(decoded.glyphs['一'].encode(), g.encode())
        self.assertEqual(decoded.zip_comment, b'preserve me')
        changed = g.with_strokes((((0., 0.), (25., -30.)), ((8., 6.),)))
        exported = Font.decode(font.encode({'一': changed}, '新字体😀'))
        self.assertEqual(exported.name, '新字体😀')
        self.assertEqual(exported.glyphs['一'].encode(), changed.encode())
        # decode validates inline previews against ZIP, including changed points.
        self.assertEqual(exported.previews, ('一',))
        self.assertEqual(exported.entries[0].date_time, font.entries[0].date_time)

    def test_modified_utf8(self):
        text = '汉字\0😀'
        self.assertEqual(Cursor(encode_string(text)).string(), text)

    def test_unsupported_dialect_and_truncation(self):
        raw = font_bytes([glyph()])
        with self.assertRaises(FontError):
            Font.decode(struct.pack('>I', 5) + raw[4:])
        for size in (0, 3, 14, len(raw)-10):
            with self.subTest(size=size), self.assertRaises(FontError):
                Font.decode(raw[:size])

    def test_reject_nan_unknown_commands_and_missing_characters(self):
        with self.assertRaises(FontError):
            glyph(strokes=(((math.nan, 0.),),)).encode()
        blob = glyph().encode()
        with self.assertRaises(FontError):
            Glyph.read(Cursor(blob[:-3] + bytes((1, 1, 1))))
        with self.assertRaises(FontError):
            Font.decode(font_bytes([glyph()])).encode({})


class GeometryTests(unittest.TestCase):
    def test_capsule_intersections_crossing_near_parallel_and_degenerate(self):
        self.assertEqual(contact_interval((0, 0), (10, 0), (5, -1), (5, 1), 0), (.5, .5))
        interval = contact_interval((0, 0), (10, 0), (5, -1), (5, 1), 1)
        self.assertAlmostEqual(interval[0], .4)
        self.assertAlmostEqual(interval[1], .6)
        self.assertIsNone(contact_interval((0, 0), (10, 0), (0, 2), (10, 2), 1))
        interval = contact_interval((0, 0), (10, 0), (5, 0), (5, 0), 1)
        self.assertAlmostEqual(interval[0], .4)
        self.assertAlmostEqual(interval[1], .6)
        self.assertEqual(contact_interval((0, 0), (0, 0), (-1, 0), (1, 0), 0), (0., 1.))


class LengthTests(unittest.TestCase):
    def run_length(self, g, factor, **kwargs):
        options = Options(length=True, length_min=factor, length_max=factor, **kwargs)
        options.validate()
        return transform_glyph(g, options, 11, 0)

    def test_extension_and_shortening_have_exact_arclength_on_free_path(self):
        g = glyph(strokes=(((0., 0.), (0., 30.), (40., 30.)),))
        for factor in (.8, 1.2):
            out, _ = self.run_length(g, factor)
            self.assertAlmostEqual(length(out.strokes[0]), 70*factor)
            self.assertIn((0., 30.), out.strokes[0])  # Interior corner is unchanged.

    def test_start_and_end_are_independently_selectable(self):
        for option, first, last in [('start', (-10., 0.), (100., 0.)),
                                    ('end', (0., 0.), (110., 0.))]:
            out, _ = self.run_length(glyph(), 1.1, length_ends=option)
            self.assertAlmostEqual(out.strokes[0][0][0], first[0])
            self.assertAlmostEqual(out.strokes[0][-1][0], last[0])

    def test_split_vertical_stroke_does_not_open_at_cross(self):
        g = glyph('十', (((-50., 0.), (50., 0.)), ((0., -50.), (0., 0.)), ((0., 0.), (0., 50.))))
        for factor in (.8, 1.2):
            out, _ = self.run_length(g, factor)
            self.assertEqual(out.strokes[1][-1], (0., 0.))
            self.assertEqual(out.strokes[2][0], (0., 0.))
            self.assertEqual(len(out.strokes), 3)
            self.assertNotEqual(out.strokes[1][0], g.strokes[1][0])

    def test_shrink_cannot_trim_past_interior_contact(self):
        g = glyph('丁', (((0., 0.), (100., 0.)), ((90., 0.), (90., 50.))))
        out, stats = self.run_length(g, .1)
        self.assertGreater(out.strokes[0][-1][0], 90.)
        self.assertEqual(out.strokes[1][0], (90., 0.))
        self.assertGreater(stats['paths_limited'], 0)

    def test_extension_stops_before_another_path(self):
        g = glyph('丁', (((0., 0.), (100., 0.)), ((105., -20.), (105., 20.))))
        out, stats = self.run_length(g, 1.5)
        self.assertLess(out.strokes[0][-1][0], 105.)
        self.assertGreater(stats['paths_limited'], 0)

    def test_two_growing_paths_do_not_meet_in_previously_empty_space(self):
        g = glyph('二', (((0., 0.), (100., 0.)), ((110., 0.), (210., 0.))))
        out, _ = self.run_length(g, 1.5)
        self.assertLess(out.strokes[0][-1][0], out.strokes[1][0][0])

    def test_near_join_closed_and_single_point_are_protected(self):
        g = glyph('口', (((0., 0.), (100., 0.), (100., 100.), (0., 100.), (0., 0.)),))
        out, stats = self.run_length(g, 1.2)
        self.assertEqual(out, g)
        self.assertEqual(stats['paths_unchanged'], 1)
        single = glyph(strokes=(((1., 2.),),))
        self.assertEqual(self.run_length(single, 1.2)[0], single)
        near = glyph('十', (((0., -10.), (0., 0.)), ((.001, 0.), (.001, 10.))))
        out, _ = self.run_length(near, 1.2)
        self.assertEqual(out.strokes[0][-1], near.strokes[0][-1])
        self.assertEqual(out.strokes[1][0], near.strokes[1][0])


class ScalingTests(unittest.TestCase):
    def test_global_has_only_uniform_scale_about_center(self):
        g = glyph(strokes=(((0., 0.), (4., 0.), (4., 2.)),))
        options = Options(scale=True, scale_mode='global', scale_min=2., scale_max=2., scale_center='center')
        out = scale_glyph(g, options, random.Random(0))
        self.assertEqual(out.strokes[0], ((-2., -1.), (6., -1.), (6., 3.)))

    def test_local_matches_radial_formula_and_keeps_center(self):
        g = glyph(strokes=(((-100., 0.), (0., 0.), (100., 0.)),))
        options = Options(scale=True, scale_min=1.2, scale_max=1.2,
                          scale_center='center', scale_radius=.5)
        out = scale_glyph(g, options, random.Random(0))
        expected = 100 * (1+.2*math.exp(-.5))
        self.assertAlmostEqual(out.strokes[0][-1][0], expected)
        self.assertIn((0., 0.), out.strokes[0])
        self.assertTrue(all(y == 0 for _, y in out.strokes[0]))

    def test_identity_parameters_preserve_exact_payload(self):
        g = glyph(strokes=(((0., -0.), (7.75, 20.25)), ((2., 3.),)))
        options = Options(length=True, length_min=1, length_max=1,
                          scale=True, scale_min=1, scale_max=1)
        self.assertEqual(transform_glyph(g, options, 2, 0)[0].encode(), g.encode())

    def test_stacking_equals_explicit_sequence_and_seeds_are_reproducible(self):
        g = glyph()
        options = Options(length=True, scale=True)
        a, _ = transform_glyph(g, options, 8, 0)
        b, _ = transform_glyph(g, options, 8, 0)
        c, _ = transform_glyph(g, options, 9, 0)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        first, _ = transform_glyph(g, replace(options, scale=False), 8, 0)
        second, _ = transform_glyph(first, replace(options, length=False), 8, 0)
        self.assertEqual(a, second)

    def test_invalid_parameters(self):
        for options in [Options(), Options(scale=True, scale_min=0),
                        Options(scale=True, scale_min=2, scale_max=1),
                        Options(length=True, length_max=math.inf),
                        Options(length=True, junction_tolerance=-1),
                        Options(scale=True, scale_radius=0),
                        Options(scale=True, scale_step=0),
                        Options(scale=True, scale_max=4)]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                options.validate()


class CLITests(unittest.TestCase):
    def run_cli(self, args):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return main([str(a) for a in args])

    def test_generate_roundtrip_reproducibility_selection_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'input.gfont'
            raw = font_bytes([glyph(), glyph('人', (((0., 0.), (10., 20.), (30., 40.)),))])
            source.write_bytes(raw)
            common = ['generate', source, '--count', '2', '--seed', '123', '--scale',
                      '--scale-mode', 'global', '--scale-min', '1.1', '--scale-max', '1.2']
            for name in ('a', 'b'):
                self.assertEqual(self.run_cli(common + ['--output', root/name]), 0)
            for index in (1, 2):
                file = f'variant_{index:03}.gfont'
                self.assertEqual((root/'a'/file).read_bytes(), (root/'b'/file).read_bytes())
                exported = Font.load(root/'a'/file)
                self.assertEqual(set(exported.glyphs), {'一', '人'})
                self.assertNotEqual(exported.name, '测试字体')
            manifest = json.loads((root/'a'/'manifest.json').read_text())
            self.assertEqual(manifest['operation_order'], ['scale'])
            self.assertFalse(manifest['options']['length'])
            self.assertTrue((root/'a'/'preview.svg').is_file())
            self.assertTrue((root/'a'/'preview.html').is_file())
            original = Font.load(source)
            for index, differences in enumerate(manifest['preview_differences'], 1):
                loaded = Font.load(root/'a'/f'variant_{index:03}.gfont')
                self.assertEqual(differences, {
                    ch: glyph_difference(original.glyphs[ch], loaded.glyphs[ch])
                    for ch in manifest['preview_chars']})
            before = (root/'a'/'variant_001.gfont').read_bytes()
            self.assertEqual(self.run_cli(common + ['--output', root/'a']), 2)
            self.assertEqual((root/'a'/'variant_001.gfont').read_bytes(), before)
            self.assertEqual(source.read_bytes(), raw)

    def test_no_action_disabled_parameters_and_invalid_ranges_create_no_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'input.gfont'
            source.write_bytes(font_bytes([glyph()]))
            for flags in [[], ['--length', '--scale-min', '1.1'],
                          ['--scale', '--length-max', '1.1'],
                          ['--scale', '--scale-min', 'nan'],
                          ['--scale', '--scale-mode', 'global', '--scale-radius', '.5']]:
                with self.subTest(flags=flags):
                    self.assertEqual(self.run_cli(['generate', source, '--output', root/'out']+flags), 2)
                    self.assertFalse((root/'out').exists())


class PublicAPITests(unittest.TestCase):
    def test_different_user_fonts_and_charsets_require_no_repository_font(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = [
                ('英文名字', 'AZ09', 1000, 0),
                ('Another name', '天地人', 256, 1),
                ('符号与空白', '+- ', 2048, 3),
            ]
            for index, (name, charset, units, previews) in enumerate(cases):
                with self.subTest(name=name):
                    source = root / f'用户字体 {index}.gfont'
                    glyphs = [glyph(ch, (((0., 0.), (float(units), 0.)),)) for ch in charset]
                    raw = font_bytes(glyphs, name=name, units=units, preview_count=previews)
                    source.write_bytes(raw)
                    destination = root / f'用户输出 {index}'
                    with redirect_stdout(io.StringIO()) as output:
                        result = generate_variants(source, destination, count=2, seed=3,
                                                   options=Options(length=True, scale=True))
                    self.assertEqual(output.getvalue(), '')
                    self.assertEqual(result, destination.resolve())
                    manifest = json.loads((result/'manifest.json').read_text())
                    self.assertEqual(manifest['source_font_name'], name)
                    self.assertEqual(manifest['glyph_count'], len(charset))
                    self.assertTrue(manifest['preview_chars'])
                    self.assertTrue(set(manifest['preview_chars']) <= set(charset))
                    self.assertNotIn(' ', manifest['preview_chars'])
                    exported = Font.load(result/'variant_001.gfont')
                    self.assertEqual(set(exported.glyphs), set(charset))
                    self.assertEqual(len(exported.previews), previews)
                    self.assertEqual(exported.units, units)
                    self.assertEqual(source.read_bytes(), raw)

    def test_api_and_cli_share_generation_parameters_and_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'arbitrary-name.gfont'
            source.write_bytes(font_bytes([glyph('A'), glyph('Z')], name='Latin'))
            generate_variants(source, root/'api', options=Options(scale=True), count=1, seed=7)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(['generate', str(source), '--output', str(root/'cli'),
                                       '--scale', '--count', '1', '--seed', '7']), 0)
            self.assertEqual((root/'api'/'variant_001.gfont').read_bytes(),
                             (root/'cli'/'variant_001.gfont').read_bytes())
            manifest = json.loads((root/'cli'/'manifest.json').read_text())
            self.assertEqual(manifest['preview_chars'], 'AZ')

    def test_invalid_preview_and_non_integer_count_do_not_write_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'latin.gfont'
            source.write_bytes(font_bytes([glyph('A')]))
            for kwargs in [dict(preview_chars='永'), dict(count=1.5), dict(count=True),
                           dict(preview_count=-1), dict(seed='42')]:
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    generate_variants(source, root/'out', options=Options(scale=True), **kwargs)
                self.assertFalse((root/'out').exists())


if __name__ == '__main__':
    unittest.main()

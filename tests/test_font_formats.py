import io
import struct
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

from glymorph import Options, generate_variants
from glymorph.font import Cursor, Font, FontError, Glyph, encode_string
from glymorph.metadata import _block, decrypt_metadata, encrypt_metadata
from tests.test_variants import glyph


def encrypted_font(version, *, extra=b'', duplicate=False):
    # The extended v7 record can occur among otherwise ordinary glyphs.
    glyphs = [glyph('7'), glyph('木')]
    if version == 7:
        glyphs.append(Glyph('・', (((1., 2.), (4., 6.)),), b'\xbf\x80\x00\x00'))
    metadata = (encode_string('test-creator') + struct.pack('>I', 3)
                + encode_string('合成字体\0😀') + encode_string('作者-id')
                + encode_string('description') + struct.pack('>II', 800, len(glyphs))
                + encode_string('extra-n') + encode_string('extra-o'))
    if version == 7:
        metadata += encode_string('preserved-v7-id')
    ciphertext = encrypt_metadata(metadata + extra)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
        output.comment = b'keep archive comment'
        for g in glyphs:
            output.writestr(str(ord(g.char)), g.encode())
        if duplicate:
            output.writestr(glyphs[0].char, glyphs[0].encode())
    return (struct.pack('>II', version, len(ciphertext)) + ciphertext
            + struct.pack('>I', len(glyphs)) + b''.join(g.encode() for g in glyphs)
            + archive.getvalue())


class MetadataTests(unittest.TestCase):
    def test_all_padding_lengths_and_determinism(self):
        for length in range(65):
            body = bytes(range(length))
            encrypted = encrypt_metadata(body)
            self.assertEqual(len(encrypted) % 8, 0)
            self.assertEqual(_block(encrypted[:8], True)[0] & 0xf8, 0x20)
            self.assertEqual(encrypt_metadata(body), encrypted)
            self.assertEqual(decrypt_metadata(encrypted), body)

    def test_bad_length_and_footer_are_rejected(self):
        original = encrypt_metadata(b'metadata')
        for bad in (b'', b'12345678', original[:-1], original[:-1] + bytes((original[-1] ^ 1,))):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                decrypt_metadata(bad)


class EncryptedFontTests(unittest.TestCase):
    def test_duplicate_zip_name_cannot_alias_two_different_characters(self):
        source = Font.decode(encrypted_font(6))
        glyphs = [glyph('7'), glyph('\x07')]
        archive = io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(archive, 'w') as output:
                for g in glyphs:
                    output.writestr('7', g.encode())
        raw = source.header + b''.join(g.encode() for g in glyphs) + archive.getvalue()
        with self.assertRaisesRegex(FontError, 'ZIP 字形名称'):
            Font.decode(raw)

    def test_versions_preserve_metadata_previews_names_and_extended_fields(self):
        for version in (5, 6, 7):
            with self.subTest(version=version):
                source = Font.decode(encrypted_font(version))
                same = Font.decode(source.encode())
                self.assertEqual(same.header, source.header)
                changed = Font.decode(source.encode(name='新名字😀'))
                self.assertEqual(changed.name, '新名字😀')
                self.assertEqual(changed.version, version)
                self.assertEqual(changed.glyphs, source.glyphs)
                self.assertEqual(changed.previews, source.previews)
                self.assertEqual(changed.zip_comment, source.zip_comment)
                self.assertEqual(changed.entry_chars, source.entry_chars)
                self.assertEqual([i.filename for i in changed.entries], [i.filename for i in source.entries])
                a, b = source.name_span
                c, d = changed.name_span
                self.assertEqual(source.metadata[:a]+source.metadata[b:], changed.metadata[:c]+changed.metadata[d:])

    def test_generation_rewrites_encrypted_name_and_preserves_extended_glyph(self):
        for version in (5, 6, 7):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source_path = root / 'input.gfont'
                source_path.write_bytes(encrypted_font(version))
                source = Font.load(source_path)
                generate_variants(source_path, root/'output', count=2, seed=42,
                                  options=Options(length=True, scale=True))
                names = set()
                for path in sorted((root/'output').glob('*.gfont')):
                    result = Font.load(path)
                    names.add(result.name)
                    self.assertNotEqual(result.name, source.name)
                    self.assertEqual(result.metadata_encoding, 'tea')
                    self.assertEqual(result.glyphs.keys(), source.glyphs.keys())
                    self.assertNotEqual(result.glyphs['木'].encode(), source.glyphs['木'].encode())
                    if version == 7:
                        self.assertEqual(result.glyphs['・'].extended_metadata, b'\xbf\x80\x00\x00')
                self.assertEqual(len(names), 2)

    def test_corrupt_metadata_truncation_and_duplicate_alias_are_rejected(self):
        for version in (5, 6, 7):
            valid = encrypted_font(version)
            bad_metadata = bytearray(valid)
            body_size = struct.unpack_from('>I', valid, 4)[0]
            bad_metadata[8+body_size-1] ^= 1
            for bad in (valid[:-1], valid[:12], bytes(bad_metadata),
                        encrypted_font(version, extra=b'unknown'),
                        encrypted_font(version, duplicate=True)):
                with self.subTest(version=version), self.assertRaises(FontError):
                    Font.decode(bad)

    def test_extended_glyph_requires_supported_layout_and_preserves_raw_field(self):
        g = Glyph('・', (((1., -2.), (3., 4.)),), b'\xbf\x80\x00\x00')
        raw = g.encode()
        with self.assertRaises(FontError):
            Glyph.read(Cursor(raw))
        self.assertEqual(Glyph.read(Cursor(raw), allow_extended=True).encode(), raw)
        for bad in (raw[:4], raw[:-1], encode_string('ab')+raw[5:]):
            with self.subTest(bad=bad), self.assertRaises(FontError):
                Glyph.read(Cursor(bad), allow_extended=True)


if __name__ == '__main__':
    unittest.main()

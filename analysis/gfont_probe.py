#!/usr/bin/env python3
"""Inspect the supplied xiongzai v6 dialect; make a geometry-only feasibility plot.

Usage: python analysis/gfont_probe.py FONT.gfont
This is a sample-specific probe, not a general gfont reader or font exporter.
The input is never modified. Only the standard library is required for JSON/SVG;
Pillow, if available, adds a PNG of the same plotted polylines.
"""

import argparse
from collections import Counter
import hashlib
import html
import io
import json
import math
from pathlib import Path
import random
import struct
import zipfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_glyph(data, offset=0):
    start = offset
    cp, count = struct.unpack_from('>HI', data, offset)
    require(count % 2 == 0 and count <= (len(data) - offset - 10) // 4,
            'Invalid coordinate count')
    offset += 6
    coords = struct.unpack_from(f'>{count}f', data, offset)
    offset += 4 * count
    size, = struct.unpack_from('>I', data, offset)
    offset += 4
    require(size == count // 2 and offset + size <= len(data), 'Invalid commands')
    commands = data[offset:offset + size]
    offset += size
    require(all(math.isfinite(v) for v in coords), 'Nonfinite coordinate')
    require(set(commands) <= {0, 1}, 'Unknown command')
    require(not commands or commands[0] == 0, 'Missing initial move')
    encoded = (struct.pack('>HI', cp, count) + struct.pack(f'>{count}f', *coords)
               + struct.pack('>I', size) + commands)
    require(encoded == data[start:offset], 'Glyph round trip differs')
    strokes = []
    for x, y, command in zip(coords[::2], coords[1::2], commands):
        if command == 0:
            strokes.append([])
        strokes[-1].append((x, y))
    return {'char': chr(cp), 'strokes': strokes, 'points': size}, offset


def inspect(path):
    data = path.read_bytes()
    offset = 0

    def integer():
        nonlocal offset
        value, = struct.unpack_from('>I', data, offset)
        offset += 4
        return value

    def string():
        nonlocal offset
        size, = struct.unpack_from('>H', data, offset)
        offset += 2
        # This sample uses ordinary UTF-8 characters; general Java modified UTF-8
        # needs separate handling for NUL/surrogates in other fonts.
        value = data[offset:offset + size].decode('utf-8')
        offset += size
        return value

    version = integer()
    require(version == 6, 'This probe only covers the supplied v6 dialect')
    metadata = {'version': version, 'creator_marker': string(),
                'unknown_enum': integer(), 'font_name': string(),
                'author_or_id': string(), 'description': string(),
                'nominal_size_candidate': integer(), 'declared_glyphs': integer()}
    require(metadata['creator_marker'] == 'xiongzai', 'Unsupported dialect')
    preview_count = integer()
    require(preview_count <= metadata['declared_glyphs'], 'Invalid preview count')
    previews = []
    for _ in range(preview_count):
        start = offset
        glyph, offset = read_glyph(data, offset)
        previews.append((glyph['char'], data[start:offset]))
    require(data[offset:offset + 4] == b'PK\x03\x04', 'Unexpected container layout')
    glyphs = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        require(archive.testzip() is None, 'ZIP CRC failure')
        require(len(set(archive.namelist())) == len(archive.namelist()), 'Duplicate entries')
        for name in archive.namelist():
            raw = archive.read(name)
            glyph, end = read_glyph(raw)
            require(end == len(raw) and name == glyph['char'], 'Unexpected glyph record')
            glyphs[name] = glyph
        require(all(raw == archive.read(ch) for ch, raw in previews), 'Preview mismatch')
    require(len(glyphs) == metadata['declared_glyphs'], 'Glyph count mismatch')
    points = [p for g in glyphs.values() for s in g['strokes'] for p in s]
    summary = {
        'source': path.name, 'sha256': hashlib.sha256(data).hexdigest(),
        'bytes': len(data), 'metadata': metadata,
        'zip_offset': offset, 'preview_count': preview_count,
        'glyph_count': len(glyphs),
        'cjk_unified_count': sum(0x4e00 <= ord(ch) <= 0x9fff for ch in glyphs),
        'point_count': len(points),
        'pen_down_path_count': sum(len(g['strokes']) for g in glyphs.values()),
        'path_point_count_histogram': dict(sorted(Counter(
            len(s) for g in glyphs.values() for s in g['strokes']).items())),
        'coordinate_bounds': [min(p[0] for p in points), min(p[1] for p in points),
                              max(p[0] for p in points), max(p[1] for p in points)],
        'checks': {'zip_crc': True, 'all_glyph_payloads_byte_roundtrip': True,
                   'all_preview_payloads_match_zip': True,
                   'all_coordinates_finite': True, 'only_move_line_commands': True},
        'sample_path_counts': {ch: len(glyphs[ch]['strokes']) for ch in '一二三十口木永的好'},
        'limitations': ['Verified only on this input file; not a universal gfont specification.',
                       'Metadata field meanings partly inferred from this one sample.',
                       'Pen-down paths are not necessarily semantic Chinese strokes.',
                       'No font exported or tested in KenjoyDraw or on hardware.',
                       'Preview deformation is illustrative; no perceptual quality claim.'],
    }
    return glyphs, summary


def resample(stroke, step=10):
    result = stroke[:1]
    for a, b in zip(stroke, stroke[1:]):
        n = max(1, math.ceil(math.dist(a, b) / step))
        result.extend((a[0] + (b[0] - a[0]) * i / n,
                       a[1] + (b[1] - a[1]) * i / n) for i in range(1, n + 1))
    return result


def deform(strokes, seed, local):
    rng = random.Random(seed)
    angle = math.radians(rng.uniform(-1.5, 1.5))
    sx, sy = rng.uniform(.97, 1.03), rng.uniform(.97, 1.03)
    cx, cy = rng.uniform(-100, 100), rng.uniform(-300, -100)
    centers = [(rng.uniform(-200, 200), rng.uniform(-380, 20),
                rng.uniform(100, 220), rng.uniform(-.12, .12)) for _ in range(4)]

    def transform(point):
        x, y = point
        dx, dy = (x - cx) * sx, (y - cy) * sy
        xx = cx + dx * math.cos(angle) - dy * math.sin(angle)
        yy = cy + dx * math.sin(angle) + dy * math.cos(angle)
        if local:
            # One common smooth field for the whole glyph. Independent per-point
            # noise and independent path translations would open junctions.
            for px, py, radius, amplitude in centers:
                weight = amplitude * math.exp(-((x-px)**2 + (y-py)**2) / (2*radius**2))
                xx += weight * (x - px)
                yy += weight * (y - py)
        return xx, yy

    return [[transform(p) for p in resample(s)] for s in strokes]


def preview(glyphs, output):
    chars = '十口木永的好'
    labels = ['Original', 'Pen-down paths', 'Global only', 'Local field A',
              'Local field B', 'Local field C']
    width, height = 1160, 1070
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
           '<rect width="100%" height="100%" fill="#fafaf8"/>']
    try:
        from PIL import Image, ImageDraw, ImageFont
        scale = 2
        raster = Image.new('RGB', (width*scale, height*scale), '#fafaf8')
        draw = ImageDraw.Draw(raster)
        font = ImageFont.truetype('DejaVuSans.ttf', 14*scale)
    except (ImportError, OSError):
        raster = None

    def text(x, y, value, size=14):
        svg.append(f'<text x="{x}" y="{y}" fill="#334155" font-family="sans-serif" font-size="{size}">{html.escape(value)}</text>')
        if raster is not None:
            draw.text((x*scale, (y-14)*scale), value, font=font, fill='#334155')

    text(25, 32, 'Actual gfont trajectories: original and illustrative geometric variants', 20)
    text(25, 58, 'Shared coordinates and scale in every column. Colors show recorded pen lifts, not semantic strokes.')
    palette = ['#2563eb', '#dc2626', '#059669', '#9333ea', '#d97706', '#0891b2']
    for col, label in enumerate(labels):
        text(124 + col*172, 92, label)
    for row, ch in enumerate(chars):
        original = glyphs[ch]['strokes']
        text(12, 155 + row*151, f'U+{ord(ch):04X}')
        text(12, 177 + row*151, f'{len(original)} paths')
        for col in range(6):
            strokes = original if col < 2 else deform(original, ord(ch)*100+col, col >= 3)
            for index, stroke in enumerate(strokes):
                pts = [(124 + col*172 + (x+300)*.25,
                        109 + row*151 + (y+450)*.25) for x, y in stroke]
                color = palette[index % len(palette)] if col == 1 else '#172033'
                coords = ' '.join(f'{x:.3f},{y:.3f}' for x, y in pts)
                svg.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round"/>')
                if raster is not None and len(pts) > 1:
                    draw.line([(round(x*scale), round(y*scale)) for x, y in pts], fill=color, width=3, joint='curve')
    text(25, 1041, 'Geometry demonstration only. No semantic stroke editing, font export, or physical plotter validation.')
    svg.append('</svg>')
    (output / 'glyph_comparison.svg').write_text('\n'.join(svg), encoding='utf-8')
    if raster is not None:
        raster.save(output / 'glyph_comparison.png')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('font', type=Path)
    parser.add_argument('--output', type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    glyphs, summary = inspect(args.font)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'font_inspection.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    preview(glyphs, args.output)
    print(json.dumps({k: summary[k] for k in ['glyph_count', 'point_count',
          'pen_down_path_count', 'checks', 'sample_path_counts']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

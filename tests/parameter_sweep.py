"""Single-character parameter experiment, with paired random draws across levels.

python -m tests.parameter_sweep FONT --char 木 --output NEW_DIRECTORY
No complete font is exported; previews use encoded-and-reread glyph records.
"""

import argparse
from dataclasses import asdict
import hashlib
from html import escape
import json
from pathlib import Path
import statistics

from glymorph import __version__
from glymorph.font import Cursor, Font, Glyph
from glymorph.preview import glyph_difference
from glymorph.transforms import Options, transform_glyph


LEVELS = (0., .05, .10, .15, .20, .25, .30, .40)


def sweep(glyph, seed=42, count=6, levels=LEVELS):
    """Keep the same (seed, variant, character) at every amplitude pair."""
    if count < 1:
        raise ValueError('变体数必须为正整数')
    cases = []
    for li, length_amount in enumerate(levels):
        for si, scale_amount in enumerate(levels):
            options = Options(length=True, length_min=1-length_amount, length_max=1+length_amount,
                              scale=True, scale_min=1-scale_amount, scale_max=1+scale_amount)
            options.validate()
            variants = []
            for index in range(count):
                changed, stats = transform_glyph(glyph, options, seed, index)
                payload = changed.encode()
                cursor = Cursor(payload)
                reread = Glyph.read(cursor, allow_extended=glyph.extended_metadata is not None)
                if cursor.pos != len(payload) or reread.encode() != payload:
                    raise ValueError('字形记录读回失败')
                variants.append({'strokes': reread.strokes,
                                 'difference': glyph_difference(glyph, reread),
                                 'length_statistics': stats})
            maxima = [v['difference']['max_sampled_displacement_percent'] for v in variants]
            cases.append({'length_index': li, 'scale_index': si, 'options': asdict(options),
                          'variants': variants,
                          'median_max_displacement_percent': statistics.median(maxima)})
    all_points = [p for case in cases for v in case['variants'] for s in v['strokes'] for p in s]
    all_points.extend(glyph.points)
    x0, y0, x1, y1 = glyph.bounds()
    size = max(x1-x0, y1-y0)
    return {'char': glyph.char, 'seed': seed, 'count': count, 'levels': levels,
            'source_strokes': glyph.strokes, 'source_size': size,
            'bounds': [min(p[0] for p in all_points), min(p[1] for p in all_points),
                       max(p[0] for p in all_points), max(p[1] for p in all_points)],
            'cases': cases}


def matrix_svg(data, mode):
    """An exportable matrix; ALL modes/levels share one coordinate transform."""
    titles = {'length': '只调整笔画长短', 'scale': '只做局部缩放', 'combined': '长短与局部缩放：相同幅度叠加'}
    levels, count = data['levels'], data['count']
    cell_w, cell_h, left, top = 190, 205, 85, 135
    width, height = left+cell_w*len(levels)+20, top+cell_h*count+30
    bounds = data['bounds']
    cx, cy = (bounds[0]+bounds[2])/2, (bounds[1]+bounds[3])/2
    factor = 138/max(bounds[2]-bounds[0], bounds[3]-bounds[1])
    pieces = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
              '<rect width="100%" height="100%" fill="#fafaf8"/>',
              '<g font-family="Microsoft YaHei, Noto Sans CJK SC, sans-serif" fill="#172d42">']

    def label(x, y, text, size=15, anchor='start'):
        return f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}">{escape(text)}</text>'

    pieces += [label(24, 34, f'{data["char"]} · {titles[mode]}', 24),
               label(24, 65, '同一行复用相同随机序列；所有格子共用坐标与比例。灰色虚线为原字，蓝色为变体。'),
               label(24, 88, '±15% 表示在 0.85～1.15 中抽样，实际变化可能更小。下方位移为采样值，占原字最大边长的百分比。')]
    for col, delta in enumerate(levels):
        pieces.append(label(left+(col+.5)*cell_w, 119, '原字' if delta == 0 else f'±{delta:.0%}', 18, 'middle'))
        li, si = (col, 0) if mode == 'length' else (0, col) if mode == 'scale' else (col, col)
        case = data['cases'][li*len(levels)+si]
        for row, variant in enumerate(case['variants']):
            if col == 0:
                pieces.append(label(12, top+row*cell_h+90, f'样本 {row+1}', 15))
            origin_x, origin_y = left+(col+.5)*cell_w, top+row*cell_h+86
            layers = [(data['source_strokes'], '#a5b0bf', ' stroke-dasharray="4 3"'),
                      (variant['strokes'], '#086bca' if col else '#172d42', '')]
            for strokes, color, dash in layers:
                for stroke in strokes:
                    pts = ' '.join(f'{origin_x+(x-cx)*factor:.4f},{origin_y+(y-cy)*factor:.4f}' for x, y in stroke)
                    pieces.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.3"{dash}/>')
            maximum = variant['difference']['max_sampled_displacement_percent']
            pieces.append(label(origin_x, top+row*cell_h+181, f'位移 {maximum:.2f}%', 14, 'middle'))
    pieces.append('</g></svg>')
    return '\n'.join(pieces)


def experiment_html(data):
    template = Path(__file__).with_name('parameter_sweep.html').read_text(encoding='utf-8')
    # Embed JSON safely for local, standalone use (no fetch or external dependencies).
    serialized = json.dumps(data, ensure_ascii=True, separators=(',', ':')).replace('<', '\\u003c')
    return template.replace('/*EXPERIMENT_DATA*/', serialized)


def main():
    parser = argparse.ArgumentParser(description='对单个字进行可复现的参数幅度预实验')
    parser.add_argument('font', type=Path)
    parser.add_argument('--char', default='木')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--count', type=int, default=6)
    args = parser.parse_args()
    if len(args.char) != 1 or args.count < 1:
        parser.error('char 必须为一个字符，count 必须为正整数')
    if args.output.exists():
        parser.error('输出目录已存在，请选择新目录')
    raw = args.font.read_bytes()
    source = Font.decode(raw)
    if args.char not in source.glyphs:
        parser.error('字体中没有所选字符')
    glyph = source.glyphs[args.char]
    x0, y0, x1, y1 = glyph.bounds()
    if max(x1-x0, y1-y0) == 0:
        parser.error('请选择具有非零尺寸的字形')
    data = sweep(glyph, args.seed, args.count)
    data.update(tool_version=__version__, source_file=args.font.name, source_font=source.name,
                source_sha256=hashlib.sha256(raw).hexdigest(),
                validation='Single glyph records encoded and reread as float32; no complete fonts exported.',
                scope='One font and character; paired random draws, no perceptual study or hardware validation.')
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/'report.json').write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (args.output/'index.html').write_text(experiment_html(data), encoding='utf-8')
    for mode in ('length', 'scale', 'combined'):
        (args.output/f'{mode}.svg').write_text(matrix_svg(data, mode), encoding='utf-8')
    if hashlib.sha256(args.font.read_bytes()).hexdigest() != data['source_sha256']:
        raise ValueError('源字体在实验期间发生变化')
    print(f'完成：{len(data["cases"])} 组参数 × {args.count} 个变体；{args.output / "index.html"}')


if __name__ == '__main__':
    main()

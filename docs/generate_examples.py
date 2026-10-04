"""Regenerate README diagrams: python -m docs.generate_examples.

Uses an original schematic glyph and the real Glymorph transformations. No user
font, third-party graphics dependency, or font export is needed. All panels use
the same coordinates and display scale; there is no per-panel normalization.
"""

from html import escape
from pathlib import Path

from glymorph.font import Glyph
from glymorph.geometry import length
from glymorph.transforms import Options, transform_glyph


DEMO = Glyph('木', (
    ((18., 43.), (35., 43.), (50., 42.), (68., 40.), (83., 40.)),
    ((50., 12.), (50., 42.), (50., 68.), (51., 92.)),
    ((50., 42.), (41., 57.), (27., 72.), (11., 81.)),
    ((50., 42.), (61., 58.), (77., 74.), (93., 82.)),
))
INK, BLUE, GRAY, ORANGE = '#172d42', '#086bca', '#b9c4cf', '#bf640b'
WIDTH, CELL_WIDTH, SCALE = 1040, 312, 2.0
PATH_COLORS = ('#086bca', '#13816e', '#be610d', '#8748bd')
PATH_LABELS = ('横 P1', '竖 P2', '撇 P3', '捺 P4')
LENGTH_OPTIONS = Options(length=True, length_min=.75, length_max=1.25)
LENGTH_SEED = 42


def text(x, y, value, *, size=18, color=INK, anchor='start'):
    return (f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" '
            f'text-anchor="{anchor}">{escape(value)}</text>')


def start(height, title, description, *, legend=None):
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        f'viewBox="0 0 {WIDTH} {height}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{escape(title)}</title>',
        f'<desc id="desc">{escape(description)}</desc>',
        '<rect width="100%" height="100%" rx="20" fill="#f3f6fa"/>',
        '<g font-family="Microsoft YaHei, Noto Sans CJK SC, sans-serif">',
        text(32, 46, title, size=27),
        text(32, 79, legend or '灰色虚线：原字参照    蓝色：变形结果    所有字使用相同坐标与显示比例', size=17, color='#526579'),
    ]


def point(x, y, col, top):
    return 32 + col*332 + CELL_WIDTH/2 + (x-52)*SCALE, top + 174 + (y-52)*SCALE


def draw_glyph(glyph, col, top, color, *, reference=False, colors=None):
    lines = []
    for index, stroke in enumerate(glyph.strokes):
        coords = ' '.join(f'{x:.3f},{y:.3f}' for x, y in
                          (point(x, y, col, top) for x, y in stroke))
        dash = ' stroke-dasharray="5 5"' if reference else ''
        stroke_color = colors[index] if colors is not None else color
        lines.append(f'<polyline points="{coords}" fill="none" stroke="{stroke_color}" '
                     f'stroke-width="{2 if reference else 3}" stroke-linecap="round" '
                     f'stroke-linejoin="round"{dash}/>')
    return lines


def panel(col, top, title, note, glyph, *, center=False):
    left = 32 + col*332
    parts = [f'<rect x="{left}" y="{top}" width="{CELL_WIDTH}" height="324" '
             'rx="12" fill="#ffffff" stroke="#dce4ed"/>',
             text(left+CELL_WIDTH/2, top+34, title, size=21, anchor='middle')]
    if glyph is not DEMO:
        parts += draw_glyph(DEMO, col, top, GRAY, reference=True)
    parts += draw_glyph(glyph, col, top, INK if glyph is DEMO else BLUE)
    if center:
        x, y = point(52, 52, col, top)
        parts.append(f'<circle cx="{x}" cy="{y}" r="5" fill="{ORANGE}" stroke="white" stroke-width="2"/>')
    parts.append(text(left+CELL_WIDTH/2, top+305, note, size=16, color='#526579', anchor='middle'))
    return parts


def changed(options):
    options.validate()
    glyph, _ = transform_glyph(DEMO, options, seed=42, variant=0)
    assert len(glyph.strokes) == len(DEMO.strokes)
    return glyph


def length_examples():
    """Use production per-path sampling; labels measure the resulting geometry."""
    LENGTH_OPTIONS.validate()
    variants = [transform_glyph(DEMO, LENGTH_OPTIONS, LENGTH_SEED, variant)[0]
                for variant in range(2)]
    return [('原字', DEMO), ('随机变体 A', variants[0]), ('随机变体 B', variants[1])]


def length_panel(col, title, glyph):
    left, top = 32 + col*332, 105
    parts = [f'<rect x="{left}" y="{top}" width="{CELL_WIDTH}" height="508" '
             'rx="12" fill="#ffffff" stroke="#dce4ed"/>',
             text(left+CELL_WIDTH/2, top+34, title, size=21, anchor='middle'),
             text(left+CELL_WIDTH/2, top+62, '同一字形中的 4 条 path' if col == 0 else '每条 path 独立抽取倍数',
                  size=16, color='#526579', anchor='middle')]
    if glyph is not DEMO:
        parts += draw_glyph(DEMO, col, top, GRAY, reference=True)
    parts += draw_glyph(glyph, col, top, INK, colors=PATH_COLORS)
    parts.append(f'<line x1="{left+20}" x2="{left+CELL_WIDTH-20}" y1="{top+307}" '
                 f'y2="{top+307}" stroke="#dce4ed"/>')
    parts.append(text(left+20, top+332, 'path', size=16, color='#526579'))
    parts.append(text(left+CELL_WIDTH-20, top+332, '实际长度倍数 / 变化', size=16,
                      color='#526579', anchor='end'))
    for index, (before, after, label, color) in enumerate(zip(DEMO.strokes, glyph.strokes, PATH_LABELS, PATH_COLORS)):
        ratio = length(after) / length(before)
        change = '原长' if glyph is DEMO else f'{"延长" if ratio > 1 else "缩短"} {abs(ratio-1)*100:.1f}%'
        y = top + 366 + index*36
        parts.append(f'<line x1="{left+20}" x2="{left+36}" y1="{y-6}" y2="{y-6}" '
                     f'stroke="{color}" stroke-width="3" stroke-linecap="round"/>')
        parts.append(text(left+46, y, label, size=17, color=color))
        parts.append(text(left+CELL_WIDTH-20, y, f'×{ratio:.3f} · {change}', size=17, anchor='end'))
    return parts


def length_diagram():
    parts = start(700, '01  笔画延长 / 缩短：每条 path 独立变化',
                  '同一个示意木字，依次显示原字和两个随机变体。横、竖、撇、捺使用不同颜色；'
                  '每条 path 独立抽取长度倍数，同一字内同时出现延长与缩短。下方列出各 path 的实际长度比。',
                  legend='颜色区分四条 path；灰色虚线为原字参照。三列使用相同坐标与显示比例。')
    for col, (title, glyph) in enumerate(length_examples()):
        parts += length_panel(col, title, glyph)
    parts += [text(32, 650, '抽样范围 0.75～1.25，随机种子 42。同一字中各条 path 的变化幅度可以不同。', size=18),
              text(32, 682, '数值按变形前后路径长度计算；交接处仍受保护。演示幅度刻意放大，便于观察。', size=17, color='#526579'), '</g></svg>']
    return '\n'.join(parts)+'\n'


def scale_diagram():
    parts = start(946, '02  缩放：整字与局部', '上排为整字缩放，下排为局部缩放，每排依次为原字、0.65 倍和 1.35 倍。橙点是固定的字形框中心。局部缩放的影响随距离逐渐减弱。')
    parts.append(text(32, 119, '整字缩放：各处按同一倍数变化', size=20))
    parts.append(text(32, 508, '局部缩放：中心附近变化较强，远处逐渐减弱', size=20))
    for mode, top in (('global', 138), ('local', 528)):
        parts += panel(0, top, '原字', '橙点：缩放中心', DEMO, center=True)
        for col, factor in ((1, .65), (2, 1.35)):
            options = Options(scale=True, scale_mode=mode, scale_min=factor,
                              scale_max=factor, scale_center='center', scale_radius=.4)
            title = ('缩小' if col == 1 else '放大') if mode == 'global' else ('局部收缩' if col == 1 else '局部扩张')
            parts += panel(col, top, title, f'缩放倍数 {factor:.2f}（固定值）', changed(options), center=True)
    parts += [text(32, 888, '局部模式的倍数描述中心附近的缩放强度，不代表整个字的宽高倍数。', size=18),
              text(32, 921, '演示固定中心、局部半径 0.40；实际生成时也可随机选择中心和倍数。', size=17, color='#526579'), '</g></svg>']
    return '\n'.join(parts)+'\n'


def main():
    destination = Path(__file__).resolve().parent / 'images'
    destination.mkdir(parents=True, exist_ok=True)
    for filename, svg in (('length.svg', length_diagram()), ('scale.svg', scale_diagram())):
        (destination / filename).write_text(svg, encoding='utf-8')
        print(f'Wrote {filename}')


if __name__ == '__main__':
    main()

"""Overlay previews and measured differences from exported float32 trajectories."""

from html import escape
import math

from .geometry import length, lerp


def _samples(stroke, count=33):
    """Corresponding normalized-arc-length samples, independent of point count."""
    if not stroke:
        return ()
    segments = [math.dist(a, b) for a, b in zip(stroke, stroke[1:])]
    total = sum(segments)
    if total == 0:
        return (stroke[0],)*count
    index, travelled = 0, 0.
    result = []
    for i in range(count):
        target = total*i/(count-1)
        while index < len(segments)-1 and travelled+segments[index] < target:
            travelled += segments[index]
            index += 1
        t = (target-travelled)/segments[index] if segments[index] else 0.
        result.append(lerp(stroke[index], stroke[index+1], max(0., min(1., t))))
    return tuple(result)


def glyph_difference(original, variant):
    """A sampled displacement diagnostic, not a bound or a perceptual score."""
    if len(original.strokes) != len(variant.strokes):
        raise ValueError('预览字形的落笔段数不一致')
    distances, ratios = [], []
    for before, after in zip(original.strokes, variant.strokes):
        distances.extend(math.dist(a, b) for a, b in zip(_samples(before), _samples(after)))
        old_length = length(before)
        ratios.append(length(after)/old_length if old_length else None)
    x0, y0, x1, y1 = original.bounds()
    size = max(x1-x0, y1-y0)
    maximum = max(distances, default=0.)
    return {'same_coordinates': original.strokes == variant.strokes,
            'max_sampled_displacement': maximum,
            'max_sampled_displacement_percent': 100*maximum/size if size else None,
            'path_length_ratios': ratios}


def comparison_svg(original, variants, chars):
    chars = list(dict.fromkeys(ch for ch in chars if ch in original))
    columns = [('原字', original)] + [(f'变体 {i+1:03}', font) for i, font in enumerate(variants)]
    cell, row_height, left, top = 240, 285, 115, 140
    width = max(650, left + cell*len(columns) + 20)
    height = top + row_height*len(chars) + 30
    result = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
              '<rect width="100%" height="100%" fill="#fafaf8"/>',
              '<style>text{font-family:system-ui,sans-serif;fill:#334155;font-size:14px}</style>',
              '<text x="20" y="30" style="font-size:21px">实际导出字形：原字叠加对比</text>',
              '<text x="20" y="58">灰色虚线：原字参照；蓝色：变体。每行共用坐标与比例。</text>',
              '<text x="20" y="83">位移按各 path 的弧长对应采样计算；百分比相对于原字最大边长。</text>',
              '<text x="20" y="105">数值用于观察变化幅度，不代表肉眼可见性或实机验证结果。</text>']
    for col, (title, _) in enumerate(columns):
        result.append(f'<text x="{left+col*cell+cell/2}" y="130" text-anchor="middle">{title}</text>')
    for row, char in enumerate(chars):
        bounds = [glyphs[char].bounds() for _, glyphs in columns]
        x0, y0 = min(b[0] for b in bounds), min(b[1] for b in bounds)
        x1, y1 = max(b[2] for b in bounds), max(b[3] for b in bounds)
        scale = 175 / max(x1-x0, y1-y0, 1)
        cx, cy = (x0+x1)/2, (y0+y1)/2
        result.append(f'<text x="16" y="{top+row*row_height+115}">{escape(char)} U+{ord(char):04X}</text>')
        for col, (_, glyphs) in enumerate(columns):
            origin_x, origin_y = left+col*cell, top+row*row_height
            result.append('<g>')
            layers = [('source', original[char], '#172033', '')] if col == 0 else [
                ('reference', original[char], '#a5b0bf', ' stroke-dasharray="4 3"'),
                ('variant', glyphs[char], '#086bca', '')]
            for kind, glyph, color, dash in layers:
                for stroke in glyph.strokes:
                    pts = [(origin_x+cell/2+(x-cx)*scale, origin_y+112+(y-cy)*scale) for x, y in stroke]
                    coords = ' '.join(f'{x:.4f},{y:.4f}' for x, y in pts)
                    result.append(f'<polyline class="{kind}" points="{coords}" fill="none" stroke="{color}" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"{dash}/>')
            if col:
                stats = glyph_difference(original[char], glyphs[char])
                percentage = stats['max_sampled_displacement_percent']
                value = f'{percentage:.3f}%' if percentage is not None else f'{stats["max_sampled_displacement"]:.4g} 字体单位'
                label = '坐标完全相同' if stats['same_coordinates'] else f'采样最大位移 {value}'
                result.append(f'<text class="difference-label" x="{origin_x+8}" y="{origin_y+230}">{label}</text>')
                ratios = [r for r in stats['path_length_ratios'] if r is not None]
                if ratios:
                    result.append(f'<text x="{origin_x+8}" y="{origin_y+252}">path 长度比 {min(ratios):.3f}～{max(ratios):.3f}</text>')
                result.append(f'<title>{escape(char)} 变体 {col:03}：{escape(label)}；逐 path 长度比 '
                              + ', '.join('无长度' if r is None else f'{r:.6f}' for r in stats['path_length_ratios'])+'</title>')
            result.append('</g>')
        result.append(f'<line x1="20" x2="{width-20}" y1="{top+(row+1)*row_height-8}" y2="{top+(row+1)*row_height-8}" stroke="#e2e8f0"/>')
    result.append('</svg>')
    return '\n'.join(result)


def comparison_html(svg, options=None):
    summary = []
    if options:
        if options.get('length'):
            summary.append(f'长短范围 {options["length_min"]}～{options["length_max"]}')
        if options.get('scale'):
            mode = '局部' if options['scale_mode'] == 'local' else '整字'
            summary.append(f'{mode}缩放 {options["scale_min"]}～{options["scale_max"]}')
    return '''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Glymorph 实际导出对比</title><style>
body{font:16px system-ui,sans-serif;margin:24px;color:#172d42;background:#fff}
h1{font-size:24px}p{max-width:960px;line-height:1.6}
#toolbar{display:flex;gap:16px;flex-wrap:wrap;align-items:center;margin:16px 0}
select,button{font:inherit;padding:6px}#viewport{overflow:auto;max-height:78vh;border:1px solid #ccd5df}
#drawing svg{display:block;height:auto;max-width:none}
#drawing[data-mode="variant"] .reference{display:none}
#drawing[data-mode="original"] .variant{display:none}
#drawing[data-mode="original"] .reference{stroke:#172033;stroke-dasharray:none}
</style></head><body><h1>实际导出字形对比</h1><p>''' + escape('；'.join(summary)) + '''</p>
<p>细小变化可能被线宽掩盖。可以放大、叠加，或交替查看同一位置的原字与变体。
这些操作只改变显示方式，图形来自实际导出文件，不会放大变形幅度。</p>
<div id="toolbar"><label>显示 <select id="mode"><option value="overlay">原字与变体叠加</option>
<option value="variant">只看变体</option><option value="original">只看原字参照</option></select></label>
<label>显示大小 <select id="zoom"><option value="1">100%</option><option value="2" selected>200%</option>
<option value="4">400%</option></select></label><button id="blink" type="button" aria-pressed="false">交替查看</button>
<a href="preview.svg">打开静态图</a></div>
<p>位移百分比采用每条 path 的 33 个等弧长位置对应比较，属于抽样指标；
仅增加同一直线上的采样点，不会产生可观的位移。path 长度比是各条路径实际长度比的范围。
“坐标完全相同”表示轨迹点完全一致；倍数为 1 的对照组应当如此。</p>
<div id="viewport"><div id="drawing" data-mode="overlay">''' + svg + '''</div></div>
<script>
const drawing = document.getElementById('drawing');
const mode = document.getElementById('mode');
const zoom = document.getElementById('zoom');
const button = document.getElementById('blink');
const svg = drawing.querySelector('svg');
const width = Number(svg.getAttribute('width'));
let timer = null;
function stop() {
  if (timer !== null) clearInterval(timer);
  timer = null;
  drawing.dataset.mode = mode.value;
  button.textContent = '交替查看';
  button.setAttribute('aria-pressed', 'false');
}
function resize() { svg.style.width = width * Number(zoom.value) + 'px'; }
mode.addEventListener('change', stop);
zoom.addEventListener('change', resize);
button.addEventListener('click', () => {
  if (timer !== null) { stop(); return; }
  drawing.dataset.mode = 'original';
  button.textContent = '停止交替';
  button.setAttribute('aria-pressed', 'true');
  timer = setInterval(() => {
    drawing.dataset.mode = drawing.dataset.mode === 'original' ? 'variant' : 'original';
  }, 700);
});
document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });
resize();
</script></body></html>
'''

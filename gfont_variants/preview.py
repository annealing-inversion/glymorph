"""SVG comparison using the actual, float32-rounded exported trajectories."""

from html import escape


def comparison_svg(original, variants, chars):
    chars = list(dict.fromkeys(ch for ch in chars if ch in original))
    columns = [('原字', original)] + [(f'变体 {i+1:03}', font) for i, font in enumerate(variants)]
    cell, left, top = 170, 105, 100
    width, height = left + cell*len(columns) + 20, top + cell*len(chars) + 35
    result = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
              '<rect width="100%" height="100%" fill="#fafaf8"/>',
              '<style>text{font-family:system-ui,sans-serif;fill:#334155;font-size:15px}</style>',
              '<text x="20" y="30" style="font-size:20px">实际导出字形对比</text>',
              '<text x="20" y="55">每行使用相同坐标与比例；本图为软件预览，尚未进行奎享导入或实机验证。</text>']
    for col, (title, _) in enumerate(columns):
        result.append(f'<text x="{left+col*cell+48}" y="84">{title}</text>')
    for row, char in enumerate(chars):
        bounds = [glyphs[char].bounds() for _, glyphs in columns]
        x0, y0 = min(b[0] for b in bounds), min(b[1] for b in bounds)
        x1, y1 = max(b[2] for b in bounds), max(b[3] for b in bounds)
        scale = 125 / max(x1-x0, y1-y0, 1)
        cx, cy = (x0+x1)/2, (y0+y1)/2
        result.append(f'<text x="20" y="{top+row*cell+80}">{escape(char)} U+{ord(char):04X}</text>')
        for col, (_, glyphs) in enumerate(columns):
            for stroke in glyphs[char].strokes:
                pts = [(left+col*cell+cell/2+(x-cx)*scale,
                        top+row*cell+cell/2+(y-cy)*scale) for x, y in stroke]
                coords = ' '.join(f'{x:.4f},{y:.4f}' for x, y in pts)
                result.append(f'<polyline points="{coords}" fill="none" stroke="#172033" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>')
    result.append('</svg>')
    return '\n'.join(result)

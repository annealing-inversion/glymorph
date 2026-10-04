"""Reusable file-to-variants pipeline shared by the CLI and Python callers."""

from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import secrets
import shutil
import tempfile
from typing import Callable

from . import __version__
from .font import Font
from .preview import comparison_svg
from .transforms import Options, plan_length, transform_glyph


def select_preview_chars(font: Font, requested: str | None) -> str:
    if requested is not None:
        missing = ''.join(dict.fromkeys(ch for ch in requested if ch not in font.glyphs))
        if missing:
            raise ValueError(f'输入字体缺少指定预览字符：{missing}；省略预览字符参数可自动选择')
        return ''.join(dict.fromkeys(requested))
    available = sorted(ch for ch, glyph in font.glyphs.items()
                       if ch.isprintable() and not ch.isspace() and glyph.points)
    count = min(8, len(available))
    if count < 2:
        return ''.join(available)
    return ''.join(available[i*(len(available)-1)//(count-1)] for i in range(count))


def validate_export(source, expected, blob):
    loaded = Font.decode(blob)
    if loaded.glyphs.keys() != source.glyphs.keys() or loaded.previews != source.previews:
        raise ValueError('导出丢失了字符或预览字形')
    for char, glyph in loaded.glyphs.items():
        if glyph.encode() != expected[char].encode():
            raise ValueError(f'导出坐标不一致：{char}')
        if len(glyph.strokes) != len(source.glyphs[char].strokes):
            raise ValueError(f'导出改变了落笔段数量：{char}')
    return loaded


def generate_variants(
    input_font: str | Path,
    output_dir: str | Path,
    *,
    options: Options,
    count: int = 16,
    seed: int | None = None,
    preview_chars: str | None = None,
    preview_count: int = 4,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Read the caller's font and write a new output directory; return its path.

    No working-directory discovery or bundled font is used. Source files are
    read-only. Raises ValueError/FontError for invalid settings/format, and
    OSError for filesystem errors. The Python API is quiet unless a progress
    callback is provided. Preview characters default to the input's charset.
    """
    options.validate()
    if type(count) is not int or count < 1:
        raise ValueError('count 必须为正整数')
    if type(preview_count) is not int or preview_count < 0:
        raise ValueError('preview_count 必须为非负整数')
    if seed is not None and type(seed) is not int:
        raise ValueError('seed 必须为整数或 None')
    source_path, destination = Path(input_font), Path(output_dir).resolve()
    if destination.exists():
        raise ValueError(f'输出目录已存在，请换一个目录：{destination}')
    raw = source_path.read_bytes()
    source = Font.decode(raw)
    preview_chars = select_preview_chars(source, preview_chars)
    source_hash = hashlib.sha256(raw).hexdigest()
    seed = secrets.randbits(64) if seed is None else seed
    recipe = json.dumps({'source': source_hash, 'seed': seed, 'options': asdict(options),
                         'version': __version__}, sort_keys=True).encode()
    batch_id = hashlib.sha256(recipe).hexdigest()[:10]
    report = progress if progress is not None else lambda message: None
    report(f'输入 {len(source.glyphs)} 个字形；种子 {seed}；操作：'
           + ' + '.join(name for enabled, name in [(options.length, '长短'), (options.scale, '缩放')] if enabled))
    plans = {}
    if options.length:
        report('计算交接保护与笔端可调整范围……')
        plans = {ch: plan_length(g, options) for ch, g in source.glyphs.items()}
    original_payloads = {ch: g.encode() for ch, g in source.glyphs.items()}
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.glymorph-', dir=destination.parent))
    records, previews = [], []
    try:
        for variant in range(count):
            transformed, stats = {}, Counter()
            for ch, glyph in source.glyphs.items():
                transformed[ch], current = transform_glyph(glyph, options, seed, variant, plans.get(ch))
                stats.update(current)
            name = f'{source.name}_v{variant+1:03}_{batch_id}'
            blob = source.encode(transformed, name)
            exported = validate_export(source, transformed, blob)
            filename = f'variant_{variant+1:03}.gfont'
            (stage / filename).write_bytes(blob)
            changed = sum(g.encode() != original_payloads[ch] for ch, g in exported.glyphs.items())
            records.append({'file': filename, 'font_name': name, 'bytes': len(blob),
                            'sha256': hashlib.sha256(blob).hexdigest(),
                            'changed_glyphs': changed, 'length_statistics': dict(stats)})
            if variant < preview_count:
                previews.append({ch: exported.glyphs[ch] for ch in preview_chars})
            report(f'[{variant+1}/{count}] {filename}，{changed} 个字形变化，读回校验通过')
        manifest = {
            'tool_version': __version__, 'format': 'xiongzai-v6', 'batch_id': batch_id,
            'source_file': source_path.name, 'source_sha256': source_hash,
            'source_font_name': source.name, 'glyph_count': len(source.glyphs),
            'seed': seed, 'count': count, 'options': asdict(options),
            'preview_chars': preview_chars, 'preview_count': min(preview_count, count),
            'operation_order': [key for key in ('length', 'scale') if getattr(options, key)],
            'validation': 'All glyphs and inline previews reread; CRC, finite float32 coordinates, charset and path counts checked.',
            'kenjoy_import_tested': False, 'hardware_tested': False,
            'files': records,
        }
        (stage / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        (stage / 'preview.svg').write_text(comparison_svg(source.glyphs, previews, preview_chars), encoding='utf-8')
        if destination.exists():
            raise ValueError('生成期间输出目录已被创建，未覆盖该目录')
        stage.rename(destination)
    except BaseException:
        shutil.rmtree(stage)
        raise
    report(f'完成：{destination}')
    return destination

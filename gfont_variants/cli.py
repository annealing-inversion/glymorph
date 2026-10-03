import argparse
from collections import Counter
from dataclasses import asdict, fields
import hashlib
import json
from pathlib import Path
import secrets
import shutil
import sys
import tempfile

from . import __version__
from .font import Font
from .preview import comparison_svg
from .transforms import Options, plan_length, transform_glyph


def parser():
    cli = argparse.ArgumentParser(description='生成可叠加选择的 gfont 长短与缩放变体；两项默认均关闭。')
    cli.add_argument('--version', action='version', version=__version__)
    sub = cli.add_subparsers(dest='command', required=True)
    inspect = sub.add_parser('inspect', help='读取并校验字体，输出基本信息')
    inspect.add_argument('font', type=Path)
    gen = sub.add_parser('generate', help='生成多套字体、参数记录和 SVG 对比图')
    gen.add_argument('font', type=Path)
    gen.add_argument('--output', required=True, type=Path, help='新的输出目录；拒绝覆盖已有目录')
    gen.add_argument('--count', type=int, default=16, help='变体字体数量，默认 16')
    gen.add_argument('--seed', type=int, help='随机种子；省略则生成并记录一个随机种子')
    gen.add_argument('--preview-chars', default='十口木永的好我中', help='SVG 对比图中的字符')
    gen.add_argument('--preview-count', type=int, default=4, help='SVG 展示前几个变体，默认 4')
    group = gen.add_argument_group('笔画延长/缩短：只修改允许调整的笔端')
    group.add_argument('--length', action='store_true', help='启用长短调整，默认关闭')
    group.add_argument('--length-min', type=float, help='路径长度倍数下限，默认 0.95（缩短 5%%）')
    group.add_argument('--length-max', type=float, help='路径长度倍数上限，默认 1.05（延长 5%%）')
    group.add_argument('--length-ends', choices=['both', 'start', 'end'], help='允许调整的端点，默认 both')
    group.add_argument('--junction-tolerance', type=float, help='交接保护距离/字形最大边长，默认 0.002')
    group = gen.add_argument_group('缩放：围绕选定中心等比例缩放')
    group.add_argument('--scale', action='store_true', help='启用缩放，默认关闭')
    group.add_argument('--scale-mode', choices=['local', 'global'], help='局部或整字缩放，默认 local')
    group.add_argument('--scale-min', type=float, help='缩放倍数下限，默认 0.95')
    group.add_argument('--scale-max', type=float, help='缩放倍数上限，默认 1.05')
    group.add_argument('--scale-center', choices=['random', 'center'], help='字形框内随机中心或框中心，默认 random')
    group.add_argument('--scale-radius', type=float, help='局部缩放半径/字形最大边长，默认 0.35')
    group.add_argument('--scale-step', type=float, help='局部缩放折线采样间隔/字形最大边长，默认 0.01')
    return cli


def options_from_args(args):
    for field in fields(Options):
        if field.name in ('length', 'scale'):
            continue
        belongs_to_length = field.name.startswith('length_') or field.name == 'junction_tolerance'
        enabled = args.length if belongs_to_length else args.scale
        if getattr(args, field.name) is not None and not enabled:
            raise ValueError(f'--{field.name.replace("_", "-")} 需要同时启用 '
                             + ('--length' if belongs_to_length else '--scale'))
    options = Options(**{field.name: getattr(args, field.name) for field in fields(Options)
                         if getattr(args, field.name) is not None})
    options.validate()
    if options.scale_mode == 'global' and (args.scale_radius is not None or args.scale_step is not None):
        raise ValueError('--scale-radius 和 --scale-step 只适用于 --scale-mode local')
    return options


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


def generate(args):
    options = options_from_args(args)
    if args.count < 1 or args.preview_count < 0:
        raise ValueError('--count 必须大于 0；--preview-count 不能小于 0')
    destination = args.output.resolve()
    if destination.exists():
        raise ValueError(f'输出目录已存在，请换一个目录：{destination}')
    raw = args.font.read_bytes()
    source = Font.decode(raw)
    source_hash = hashlib.sha256(raw).hexdigest()
    seed = secrets.randbits(64) if args.seed is None else args.seed
    recipe = json.dumps({'source': source_hash, 'seed': seed, 'options': asdict(options),
                         'version': __version__}, sort_keys=True).encode()
    batch_id = hashlib.sha256(recipe).hexdigest()[:10]
    print(f'输入 {len(source.glyphs)} 个字形；种子 {seed}；操作：'
          + ' + '.join(name for enabled, name in [(options.length, '长短'), (options.scale, '缩放')] if enabled), flush=True)
    plans = {}
    if options.length:
        print('计算交接保护与笔端可调整范围……', flush=True)
        plans = {ch: plan_length(g, options) for ch, g in source.glyphs.items()}
    original_payloads = {ch: g.encode() for ch, g in source.glyphs.items()}
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.gfont-variants-', dir=destination.parent))
    records, previews = [], []
    try:
        for variant in range(args.count):
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
            if variant < args.preview_count:
                previews.append({ch: exported.glyphs[ch] for ch in args.preview_chars if ch in exported.glyphs})
            print(f'[{variant+1}/{args.count}] {filename}，{changed} 个字形变化，读回校验通过', flush=True)
        manifest = {
            'tool_version': __version__, 'format': 'xiongzai-v6', 'batch_id': batch_id,
            'source_file': args.font.name, 'source_sha256': source_hash,
            'source_font_name': source.name, 'glyph_count': len(source.glyphs),
            'seed': seed, 'count': args.count, 'options': asdict(options),
            'operation_order': [key for key in ('length', 'scale') if getattr(options, key)],
            'validation': 'All glyphs and inline previews reread; CRC, finite float32 coordinates, charset and path counts checked.',
            'kenjoy_import_tested': False, 'hardware_tested': False,
            'files': records,
        }
        (stage / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        (stage / 'preview.svg').write_text(comparison_svg(source.glyphs, previews, args.preview_chars), encoding='utf-8')
        if destination.exists():
            raise ValueError('生成期间输出目录已被创建，未覆盖该目录')
        stage.rename(destination)
    except BaseException:
        shutil.rmtree(stage)
        raise
    print(f'完成：{destination}', flush=True)
    return 0


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == 'inspect':
            font = Font.load(args.font)
            print(json.dumps({'format': 'xiongzai-v6', 'font_name': font.name,
                              'glyph_count': len(font.glyphs), 'preview_count': len(font.previews),
                              'points': sum(len(g.points) for g in font.glyphs.values()),
                              'paths': sum(len(g.strokes) for g in font.glyphs.values())},
                             ensure_ascii=False, indent=2))
            return 0
        return generate(args)
    except (OSError, ValueError) as exc:
        print(f'错误：{exc}', file=sys.stderr)
        return 2

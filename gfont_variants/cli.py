import argparse
from dataclasses import fields
import json
from pathlib import Path
import sys

from . import __version__
from .font import Font
from .pipeline import generate_variants
from .transforms import Options


def parser():
    cli = argparse.ArgumentParser(description='读取用户指定的字体文件，生成长短/缩放变体；两项默认均关闭。')
    cli.add_argument('--version', action='version', version=__version__)
    sub = cli.add_subparsers(dest='command', required=True)
    inspect = sub.add_parser('inspect', help='读取并校验字体，输出基本信息')
    inspect.add_argument('font', type=Path, metavar='INPUT_FONT', help='用户提供的输入字体路径，可位于仓库之外')
    gen = sub.add_parser('generate', help='生成多套字体、参数记录和 SVG 对比图')
    gen.add_argument('font', type=Path, metavar='INPUT_FONT', help='用户提供的输入字体路径，可位于仓库之外')
    gen.add_argument('--output', required=True, type=Path, help='新的输出目录；拒绝覆盖已有目录')
    gen.add_argument('--count', type=int, default=16, help='变体字体数量，默认 16')
    gen.add_argument('--seed', type=int, help='随机种子；省略则生成并记录一个随机种子')
    gen.add_argument('--preview-chars', help='SVG 对比图中的字符；默认从输入字体自动选择最多 8 个')
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


def generate(args):
    generate_variants(
        args.font, args.output,
        options=options_from_args(args), count=args.count, seed=args.seed,
        preview_chars=args.preview_chars, preview_count=args.preview_count,
        progress=lambda message: print(message, flush=True),
    )
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

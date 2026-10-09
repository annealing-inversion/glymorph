"""Opt-in integration checks for user-supplied fonts; never part of test discovery.

python -m tests.validate_fonts FONT [FONT ...] --output NEW_DIRECTORY
"""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
import hashlib
from html import escape
import json
from pathlib import Path
import time
from urllib.parse import quote

from glymorph import Options, __version__, generate_variants
from glymorph.font import Font
from glymorph.geometry import length
from glymorph.preview import glyph_difference


CASES = {
    'length-shrink': Options(length=True, length_min=.90, length_max=.98),
    'length-grow': Options(length=True, length_min=1.02, length_max=1.10),
    'scale-global': Options(scale=True, scale_mode='global'),
    'scale-local': Options(scale=True),
    'combined': Options(length=True, scale=True),
    'identity': Options(length=True, length_min=1., length_max=1.,
                        scale=True, scale_min=1., scale_max=1.),
}
TITLES = {'length-shrink': '只缩短', 'length-grow': '只延长',
          'scale-global': '整字缩放', 'scale-local': '局部缩放',
          'combined': '长短与局部缩放叠加', 'identity': '倍数为 1（不变形）'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def check(condition, message):
    if not condition:
        raise ValueError(message)


def metadata_without_name(font):
    raw = font.header if font.metadata is None else font.metadata
    start, end = font.name_span
    return raw[:start]+raw[end:]


def validate_case(source, directory, mode, original_hash, count):
    manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    check(manifest['source_sha256'] == original_hash, 'Source hash mismatch')
    check(len(manifest['files']) == count, 'Missing output files')
    check((directory/'preview.svg').is_file(), 'Missing preview')
    check((directory/'preview.html').is_file(), 'Missing interactive preview')
    names, signatures = set(), set()
    changed_counts, output_sizes = [], []
    for index, record in enumerate(manifest['files']):
        blob = (directory/record['file']).read_bytes()
        check(digest(blob) == record['sha256'], 'Output hash mismatch')
        output = Font.decode(blob)  # Includes CRC, float32 and inline-preview checks.
        if index < manifest['preview_count']:
            check(manifest['preview_differences'][index] == {
                ch: glyph_difference(source.glyphs[ch], output.glyphs[ch])
                for ch in manifest['preview_chars']}, 'Preview difference metrics mismatch')
        check(output.name == record['font_name'] and output.name != source.name, 'Wrong font name')
        names.add(output.name)
        check(output.version == source.version and output.metadata_encoding == source.metadata_encoding,
              'Format layout changed')
        check(output.units == source.units and output.zip_comment == source.zip_comment, 'Metadata changed')
        check(metadata_without_name(output) == metadata_without_name(source), 'Non-name metadata changed')
        check(output.previews == source.previews and output.entry_chars == source.entry_chars, 'Order changed')
        check([e.filename for e in output.entries] == [e.filename for e in source.entries], 'ZIP names changed')
        check(output.glyphs.keys() == source.glyphs.keys(), 'Characters changed')
        changed = 0
        signature = hashlib.sha256()
        for char, original in source.glyphs.items():
            result = output.glyphs[char]
            encoded = result.encode()
            signature.update(encoded)
            changed += encoded != original.encode()
            check(len(result.strokes) == len(original.strokes), 'Pen-down path count changed')
            check(result.extended_metadata == original.extended_metadata, 'Extended glyph field changed')
            if mode.startswith('length-'):
                for before, after in zip(original.strokes, result.strokes):
                    old, new = length(before), length(after)
                    tolerance = max(1., old)*1e-5
                    if mode == 'length-shrink':
                        check(.9*old-tolerance <= new <= old+tolerance, 'Shortening outside allowed range')
                    else:
                        check(old-tolerance <= new <= 1.1*old+tolerance, 'Extension outside allowed range')
            if mode == 'scale-global':
                check(len(result.points) == len(original.points), 'Global scale added or removed points')
        check(changed == record['changed_glyphs'], 'Changed-glyph report mismatch')
        check(changed == 0 if mode == 'identity' else changed > 0, 'Unexpected unchanged/changed output')
        signatures.add(signature.hexdigest())
        changed_counts.append(changed)
        output_sizes.append(len(blob))
    check(len(names) == count, 'Variant names are not unique')
    if count > 1 and mode != 'identity':
        check(len(signatures) > 1, 'Variants have identical trajectories')
    return {'changed_glyphs': changed_counts, 'bytes': output_sizes,
            'font_sha256': [entry['sha256'] for entry in manifest['files']]}


def validate_font(path, directory, count, seed):
    started = time.monotonic()
    original_hash = digest(path.read_bytes())
    record = {'source': path.name, 'source_sha256': original_hash, 'directory': directory.name,
              'status': 'running', 'cases': {}}
    directory.mkdir()
    try:
        source = Font.load(path)
        record.update(font_name=source.name, glyph_count=len(source.glyphs),
                      format_version=source.version, metadata_encoding=source.metadata_encoding)
        preview = ''.join(ch for ch in '十口木永的好' if ch in source.glyphs) or None
        for mode, options in CASES.items():
            print(f'{path.name}: {mode} started', flush=True)
            case_start = time.monotonic()
            number = 1 if mode == 'identity' else count
            generate_variants(path, directory/mode, options=options, count=number, seed=seed,
                              preview_chars=preview, preview_count=min(number, 2))
            result = validate_case(source, directory/mode, mode, original_hash, number)
            result.update(options=asdict(options), seconds=round(time.monotonic()-case_start, 3))
            record['cases'][mode] = result
            print(f'{path.name}: {mode} passed ({result["seconds"]} s)', flush=True)
        generate_variants(path, directory/'repeat-combined', options=CASES['combined'], count=1,
                          seed=seed, preview_chars=preview, preview_count=1)
        repeated = validate_case(source, directory/'repeat-combined', 'combined', original_hash, 1)
        check(repeated['font_sha256'][0] == record['cases']['combined']['font_sha256'][0],
              'Fixed-seed generation is not reproducible')
        record['reproducible'] = True
        record['status'] = 'passed'
    except Exception as exc:
        record.update(status='failed', error=f'{type(exc).__name__}: {exc}')
    record['source_unchanged'] = digest(path.read_bytes()) == original_hash
    if not record['source_unchanged']:
        record.update(status='failed', error='Input font was modified')
    record['seconds'] = round(time.monotonic()-started, 3)
    (directory/'report.json').write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return record


def write_index(destination, records):
    html = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8">',
            '<title>Glymorph 字体验证结果</title>',
            '<style>body{font:16px system-ui;max-width:1200px;margin:40px auto;padding:0 20px;color:#172d42} '
            'img{max-width:100%;border:1px solid #ccd5df} details{margin:20px 0} summary{cursor:pointer} '
            'h2{margin-top:48px} code{overflow-wrap:anywhere}</style>',
            '<h1>Glymorph 字体验证结果</h1><p>软件导出与读回测试；尚未在奎享客户端或实机验证。</p>',
            '<p>灰色虚线为原字，蓝色为实际导出的变体。部分局部缩放的变化较小，'
            '请打开“放大 / 叠加 / 交替对比”查看。字形记录有变化不等于肉眼能分辨；'
            '倍数为 1 的测试用于检查不变形时的结果。</p>']
    for record in records:
        html.append(f'<h2>{escape(record["source"])}</h2><p>{escape(record["status"])} '
                    f'· {record.get("glyph_count", "?")} 个字形</p>')
        if 'error' in record:
            html.append(f'<p>{escape(record["error"])}</p>')
        for mode in record['cases']:
            href = quote(f'{record["directory"]}/{mode}', safe='/')
            html.append(f'<details><summary>{TITLES[mode]}</summary><p><a href="{href}/preview.html">放大 / 叠加 / 交替对比</a> '
                        f'· <a href="{href}/preview.svg">静态对比图</a> '
                        f'· <a href="{href}/manifest.json">参数与输出记录</a></p>'
                        f'<img src="{href}/preview.svg" alt="{TITLES[mode]}实际导出对比"></details>')
    html.append('</html>')
    (destination/'index.html').write_text('\n'.join(html), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description='对用户指定的字体进行完整导出与变形验证')
    parser.add_argument('fonts', nargs='+', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--count', type=int, default=2, help='每种非恒等模式生成的变体数，至少 2')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    if args.count < 2 or args.workers < 1:
        parser.error('count 至少为 2，workers 至少为 1')
    sources = [p.resolve(strict=True) for p in args.fonts]
    destination = args.output.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    records = []
    started = time.monotonic()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(validate_font, path, destination/f'{i:02d}-{path.stem}', args.count, args.seed)
                   for i, path in enumerate(sources, 1)]
        for future in as_completed(futures):
            records.append(future.result())
            print(f'{records[-1]["source"]}: {records[-1]["status"]}', flush=True)
    records.sort(key=lambda r: r['directory'])
    report = {'tool_version': __version__, 'seed': args.seed, 'count': args.count,
              'seconds': round(time.monotonic()-started, 3), 'fonts': records,
              'kenjoy_import_tested': False, 'hardware_tested': False}
    (destination/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    write_index(destination, records)
    print(f'Report: {destination / "report.json"}', flush=True)
    return 0 if all(r['status'] == 'passed' for r in records) else 1


if __name__ == '__main__':
    raise SystemExit(main())

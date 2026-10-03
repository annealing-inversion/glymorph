"""Strict reader/writer for the supplied xiongzai v6 dialect, not generic gfont.

Unchanged header fields are preserved as bytes. ZIP glyphs and inline previews
are regenerated together. No third-party implementation is imported.
"""

from copy import copy
from dataclasses import dataclass, replace
import io
import math
from pathlib import Path
import struct
import zipfile

Point = tuple[float, float]
Stroke = tuple[Point, ...]


class FontError(ValueError):
    pass


class Cursor:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def take(self, count: int) -> bytes:
        if count < 0 or count > len(self.data) - self.pos:
            raise FontError(f"数据在偏移 {self.pos} 处截断")
        result = self.data[self.pos:self.pos + count]
        self.pos += count
        return result

    def number(self, fmt: str):
        return struct.unpack('>' + fmt, self.take(struct.calcsize('>' + fmt)))[0]

    def string(self):
        raw = self.take(self.number('H'))
        # Java modified UTF-8: NUL uses C0 80; supplementary codepoints are
        # encoded as UTF-16 surrogate pairs, each with its own UTF-8 encoding.
        try:
            text = raw.replace(b'\xc0\x80', b'\0').decode('utf-8', 'surrogatepass')
            return text.encode('utf-16-be', 'surrogatepass').decode('utf-16-be')
        except UnicodeError as exc:
            raise FontError('无效的元数据字符串') from exc


def encode_string(value: str) -> bytes:
    units = value.encode('utf-16-be')
    text = ''.join(chr(int.from_bytes(units[i:i + 2], 'big'))
                   for i in range(0, len(units), 2))
    raw = text.encode('utf-8', 'surrogatepass').replace(b'\0', b'\xc0\x80')
    if len(raw) > 65535:
        raise FontError('字体名称过长')
    return struct.pack('>H', len(raw)) + raw


@dataclass(frozen=True)
class Glyph:
    char: str
    strokes: tuple[Stroke, ...]

    @property
    def points(self):
        return tuple(p for stroke in self.strokes for p in stroke)

    def bounds(self):
        pts = self.points
        if not pts:
            return 0., 0., 0., 0.
        return min(x for x, _ in pts), min(y for _, y in pts), max(x for x, _ in pts), max(y for _, y in pts)

    def with_strokes(self, strokes):
        return replace(self, strokes=tuple(tuple(s) for s in strokes))

    def encode(self):
        if len(self.char) != 1 or ord(self.char) > 0xffff:
            raise FontError('该格式只支持单个 BMP 字符')
        coords, commands = [], bytearray()
        for stroke in self.strokes:
            if not stroke:
                raise FontError('字形包含空轨迹段')
            for index, (x, y) in enumerate(stroke):
                if not math.isfinite(x) or not math.isfinite(y):
                    raise FontError('字形含非有限坐标')
                coords.extend((x, y))
                commands.append(0 if index == 0 else 1)
        try:
            return (struct.pack('>HI', ord(self.char), len(coords))
                    + struct.pack(f'>{len(coords)}f', *coords)
                    + struct.pack('>I', len(commands)) + commands)
        except (struct.error, OverflowError) as exc:
            raise FontError('变换后的坐标超出文件格式范围') from exc

    @classmethod
    def read(cls, cursor):
        cp, count = cursor.number('H'), cursor.number('I')
        if count % 2 or count > (len(cursor.data) - cursor.pos) // 4:
            raise FontError('无效的坐标数量')
        coords = struct.unpack(f'>{count}f', cursor.take(count * 4))
        size = cursor.number('I')
        if size != count // 2:
            raise FontError('指令数与坐标数不匹配')
        commands = cursor.take(size)
        if set(commands) - {0, 1} or (commands and commands[0] != 0):
            raise FontError('字形包含未知指令或缺少起始移动指令')
        if not all(math.isfinite(v) for v in coords):
            raise FontError('字形包含非有限坐标')
        strokes = []
        for x, y, command in zip(coords[::2], coords[1::2], commands):
            if command == 0:
                strokes.append([])
            strokes[-1].append((x, y))
        return cls(chr(cp), tuple(tuple(s) for s in strokes))


@dataclass
class Font:
    name: str
    units: int
    glyphs: dict[str, Glyph]
    previews: tuple[str, ...]
    header: bytes
    name_span: tuple[int, int]
    entries: tuple[zipfile.ZipInfo, ...]
    zip_comment: bytes = b''

    @classmethod
    def load(cls, path: str | Path):
        return cls.decode(Path(path).read_bytes())

    @classmethod
    def decode(cls, data: bytes):
        cursor = Cursor(data)
        if cursor.number('I') != 6 or cursor.string() != 'xiongzai':
            raise FontError('目前只支持已经验证的 xiongzai v6 格式')
        cursor.number('I')  # Unknown enum: preserve without interpreting.
        name_start = cursor.pos
        name = cursor.string()
        name_end = cursor.pos
        cursor.string()  # Author/id: preserve verbatim, not a proven identity field.
        cursor.string()  # Description.
        units, declared = cursor.number('I'), cursor.number('I')
        preview_count = cursor.number('I')
        header = data[:cursor.pos]
        if declared > len(data) // 10 or preview_count > declared:
            raise FontError('无效的字形数量')
        previews = []
        preview_data = {}
        for _ in range(preview_count):
            start = cursor.pos
            glyph = Glyph.read(cursor)
            if glyph.char in preview_data:
                raise FontError('重复的预览字形')
            previews.append(glyph.char)
            preview_data[glyph.char] = data[start:cursor.pos]
        if data[cursor.pos:cursor.pos + 4] != b'PK\x03\x04':
            raise FontError('未在预览字形之后找到 ZIP 字形库')
        # zipfile accepts a truncated archive comment. Require a complete EOCD
        # record, since this writer must not silently accept a damaged source.
        end = data.rfind(b'PK\x05\x06', max(cursor.pos, len(data)-65557))
        while end >= cursor.pos:
            if end + 22 <= len(data):
                comment_size = struct.unpack_from('<H', data, end+20)[0]
                if end + 22 + comment_size == len(data):
                    break
            end = data.rfind(b'PK\x05\x06', cursor.pos, end)
        if end < cursor.pos:
            raise FontError('ZIP 尾部缺失、截断或有未知附加数据')
        glyphs = {}
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                if len(entries) != declared:
                    raise FontError('声明的字数与 ZIP 条目数不一致')
                for entry in entries:
                    if entry.filename in glyphs or len(entry.filename) != 1:
                        raise FontError('重复或未知的 ZIP 字形名称')
                    raw = archive.read(entry)  # Also verifies the entry CRC.
                    sub = Cursor(raw)
                    glyph = Glyph.read(sub)
                    if sub.pos != len(raw) or glyph.char != entry.filename:
                        raise FontError('未知的字形记录布局')
                    if glyph.encode() != raw:
                        raise FontError('字形序列化不能无损往返')
                    glyphs[glyph.char] = glyph
                for char, raw in preview_data.items():
                    if char not in glyphs or glyphs[char].encode() != raw:
                        raise FontError('预览字形与字形库不一致')
                comment = archive.comment
        except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as exc:
            raise FontError(f'无法读取 ZIP 字形库：{exc}') from exc
        return cls(name, units, glyphs, tuple(previews), header,
                   (name_start, name_end), tuple(entries), comment)

    def encode(self, glyphs=None, name=None):
        glyphs = self.glyphs if glyphs is None else glyphs
        if glyphs.keys() != self.glyphs.keys():
            raise FontError('导出必须保留完整字符集合')
        payloads = {}
        for ch, glyph in glyphs.items():
            if ch != glyph.char:
                raise FontError('字形键与字符不一致')
            payloads[ch] = glyph.encode()
        prefix = self.header
        if name is not None:
            start, end = self.name_span
            prefix = prefix[:start] + encode_string(name) + prefix[end:]
        prefix += b''.join(payloads[ch] for ch in self.previews)
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, 'w') as archive:
            archive.comment = self.zip_comment
            for info in self.entries:
                archive.writestr(copy(info), payloads[info.filename])
        return prefix + archive_bytes.getvalue()

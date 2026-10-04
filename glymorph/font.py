"""Strict reader/writer for the verified plain/encrypted .gfont layouts.

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

from .metadata import decrypt_metadata, encrypt_metadata

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
    extended_metadata: bytes | None = None

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
            if self.extended_metadata is None:
                prefix = struct.pack('>H', ord(self.char))
            else:
                if len(self.extended_metadata) != 4:
                    raise FontError('未知的扩展字形字段长度')
                prefix = encode_string(self.char) + self.extended_metadata
            return (prefix + struct.pack('>I', len(coords))
                    + struct.pack(f'>{len(coords)}f', *coords)
                    + struct.pack('>I', len(commands)) + commands)
        except (struct.error, OverflowError) as exc:
            raise FontError('变换后的坐标超出文件格式范围') from exc

    @classmethod
    def read(cls, cursor, *, allow_extended=False):
        start = cursor.pos
        try:
            return cls._read(cursor, extended=False)
        except FontError:
            if not allow_extended:
                raise
            cursor.pos = start
            return cls._read(cursor, extended=True)

    @classmethod
    def _read(cls, cursor, *, extended):
        metadata = None
        if extended:
            char = cursor.string()
            if len(char) != 1 or ord(char) > 0xffff:
                raise FontError('未知的扩展字形字符布局')
            metadata = cursor.take(4)
        else:
            char = chr(cursor.number('H'))
        count = cursor.number('I')
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
        return cls(char, tuple(tuple(s) for s in strokes), metadata)


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
    version: int = 6
    metadata: bytes | None = None
    entry_chars: tuple[str, ...] = ()

    @property
    def metadata_encoding(self):
        return 'tea' if self.metadata is not None else 'plain'

    @classmethod
    def load(cls, path: str | Path):
        return cls.decode(Path(path).read_bytes())

    @classmethod
    def decode(cls, data: bytes):
        cursor = Cursor(data)
        version = cursor.number('I')
        if version not in (5, 6, 7):
            raise FontError('不支持此 .gfont 文件版本')
        metadata = None
        # The verified unencrypted dialect has a UTF creator directly after
        # version 6. Encrypted layouts begin with a uint32 byte count instead.
        if version == 6 and data[4:14] == encode_string('xiongzai'):
            body = cursor
        else:
            encrypted = cursor.take(cursor.number('I'))
            try:
                metadata = decrypt_metadata(encrypted)
            except ValueError as exc:
                raise FontError(str(exc)) from exc
            body = Cursor(metadata)
        body.string()  # Creator marker is metadata, not a font identity check.
        body.number('I')  # Unknown enum: preserve without interpreting.
        name_start = body.pos
        name = body.string()
        name_end = body.pos
        body.string()  # Author/id: preserve verbatim, not a proven identity field.
        body.string()  # Description.
        units, declared = body.number('I'), body.number('I')
        if metadata is not None:
            body.string()
            body.string()
            if version >= 7:
                body.string()  # Additional identifier; preserve unchanged.
            if body.pos != len(metadata):
                raise FontError('未知的 .gfont 元数据附加字段')
        preview_count = cursor.number('I')
        header = data[:cursor.pos]
        if declared > len(data) // 10 or preview_count > declared:
            raise FontError('无效的字形数量')
        previews = []
        preview_data = {}
        for _ in range(preview_count):
            start = cursor.pos
            glyph = Glyph.read(cursor, allow_extended=version >= 7)
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
        entry_chars = []
        entry_names = set()
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                if len(entries) != declared:
                    raise FontError('声明的字数与 ZIP 条目数不一致')
                for entry in entries:
                    raw = archive.read(entry)  # Also verifies the entry CRC.
                    sub = Cursor(raw)
                    glyph = Glyph.read(sub, allow_extended=version >= 7)
                    if (entry.filename in entry_names or glyph.char in glyphs
                            or entry.filename not in (glyph.char, str(ord(glyph.char)))):
                        raise FontError('重复或未知的 ZIP 字形名称')
                    if sub.pos != len(raw):
                        raise FontError('未知的字形记录布局')
                    if glyph.encode() != raw:
                        raise FontError('字形序列化不能无损往返')
                    glyphs[glyph.char] = glyph
                    entry_chars.append(glyph.char)
                    entry_names.add(entry.filename)
                for char, raw in preview_data.items():
                    if char not in glyphs or glyphs[char].encode() != raw:
                        raise FontError('预览字形与字形库不一致')
                comment = archive.comment
        except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as exc:
            raise FontError(f'无法读取 ZIP 字形库：{exc}') from exc
        return cls(name, units, glyphs, tuple(previews), header,
                   (name_start, name_end), tuple(entries), comment, version, metadata,
                   tuple(entry_chars))

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
            if self.metadata is None:
                prefix = prefix[:start] + encode_string(name) + prefix[end:]
            else:
                metadata = self.metadata[:start] + encode_string(name) + self.metadata[end:]
                encrypted = encrypt_metadata(metadata)
                prefix = struct.pack('>II', self.version, len(encrypted)) + encrypted + struct.pack('>I', len(self.previews))
        prefix += b''.join(payloads[ch] for ch in self.previews)
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, 'w') as archive:
            archive.comment = self.zip_comment
            characters = self.entry_chars or tuple(info.filename for info in self.entries)
            for info, char in zip(self.entries, characters):
                archive.writestr(copy(info), payloads[char])
        return prefix + archive_bytes.getvalue()

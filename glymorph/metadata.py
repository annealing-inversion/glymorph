"""The 16-round TEA envelope used by encrypted .gfont metadata.

This is file-format compatibility, not a general-purpose encryption API.
The format's fixed key and envelope are described in doc/gfont-format.md.
"""

import hashlib
import struct


_KEY = struct.unpack('>4I', bytes((1, 9, 8, 9, 0, 8, 2, 6, 1, 9, 9, 2, 0, 8, 2, 8)))
_MASK = 0xffffffff
_DELTA = 0x9e3779b9


def _block(data, decrypt):
    left, right = struct.unpack('>2I', data)
    total = (_DELTA * 16) & _MASK if decrypt else 0
    for _ in range(16):
        if decrypt:
            right = (right - (((left << 4) + _KEY[2]) ^ (left + total) ^ ((left >> 5) + _KEY[3]))) & _MASK
            left = (left - (((right << 4) + _KEY[0]) ^ (right + total) ^ ((right >> 5) + _KEY[1]))) & _MASK
            total = (total - _DELTA) & _MASK
        else:
            total = (total + _DELTA) & _MASK
            left = (left + (((right << 4) + _KEY[0]) ^ (right + total) ^ ((right >> 5) + _KEY[1]))) & _MASK
            right = (right + (((left << 4) + _KEY[2]) ^ (left + total) ^ ((left >> 5) + _KEY[3]))) & _MASK
    return struct.pack('>2I', left, right)


def _xor(a, b):
    return bytes(x ^ y for x, y in zip(a, b))


def decrypt_metadata(ciphertext):
    if len(ciphertext) < 16 or len(ciphertext) % 8:
        raise ValueError('无效的 .gfont 元数据加密块长度')
    previous_x = previous_c = bytes(8)
    blocks = []
    for offset in range(0, len(ciphertext), 8):
        current_c = ciphertext[offset:offset+8]
        current_x = _block(_xor(current_c, previous_x), True)
        blocks.append(_xor(current_x, previous_c))
        previous_x, previous_c = current_x, current_c
    plain = b''.join(blocks)
    start = (plain[0] & 7) + 3  # Length byte, padding, two salt bytes.
    if start > len(plain)-7 or plain[-7:] != bytes(7):
        raise ValueError('.gfont 元数据解密校验失败')
    return plain[start:-7]


def encrypt_metadata(metadata):
    padding = (-(len(metadata)+10)) % 8
    # Deterministic salt keeps identical generation recipes reproducible.
    salt = hashlib.sha256(metadata).digest()
    # Every verified file uses 0x20 in the marker's high bits.
    plain = bytes((0x20 | padding,)) + salt[:padding+2] + metadata + bytes(7)
    previous_x = previous_c = bytes(8)
    blocks = []
    for offset in range(0, len(plain), 8):
        current_x = _xor(plain[offset:offset+8], previous_c)
        current_c = _xor(_block(current_x, False), previous_x)
        blocks.append(current_c)
        previous_x, previous_c = current_x, current_c
    return b''.join(blocks)

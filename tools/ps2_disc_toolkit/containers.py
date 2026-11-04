"""
Physical container drivers for PS2 disc images:
- Iso2048Device : Standard 2048-byte sector .iso images (DVD-5 and DVD-9).
- Bin2352Device : Raw 2352-byte sector CD-ROM .bin / .cue images (Mode 1 and Mode 2 XA Form 1/Form 2).
- CsoDevice     : Compressed .cso (CISO v1/v2 zlib) images read on the fly without full decompression.
"""

from collections import OrderedDict
import os
import re
import struct
import zlib

SECTOR_SIZE = 2048
RAW_CD_SECTOR_SIZE = 2352
CD_SYNC_PATTERN = b'\x00\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\x00'
CSO_MAGIC = b'CISO'


class SectorDevice:
    """Abstract 2048-byte logical sector reader over any physical disc image container."""

    format_name = 'UNKNOWN'
    raw_sector_size = SECTOR_SIZE

    def __init__(self, path, total_sectors):
        self.path = path
        self.total_sectors = total_sectors

    @property
    def logical_size(self):
        return self.total_sectors * SECTOR_SIZE

    def read_sectors(self, sector, count):
        raise NotImplementedError

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


class Iso2048Device(SectorDevice):
    """Standard 2048-byte cooked ISO image reader (DVD-5 / DVD-9 / cooked CD)."""

    format_name = 'ISO-2048'
    raw_sector_size = SECTOR_SIZE

    def __init__(self, path):
        self._fp = open(path, 'rb')
        size = os.path.getsize(path)
        super().__init__(path, size // SECTOR_SIZE)

    def read_sectors(self, sector, count):
        if count <= 0 or sector >= self.total_sectors:
            return b''
        clamped = min(count, self.total_sectors - sector)
        self._fp.seek(sector * SECTOR_SIZE)
        data = self._fp.read(clamped * SECTOR_SIZE)
        if len(data) < clamped * SECTOR_SIZE:
            data += b'\x00' * (clamped * SECTOR_SIZE - len(data))
        return data

    def close(self):
        if getattr(self, '_fp', None):
            self._fp.close()
            self._fp = None


class Bin2352Device(SectorDevice):
    """
    Raw 2352-byte CD-ROM image reader (.bin or .cue).
    Supports Mode 1 (payload at +16) and Mode 2 XA Form 1/2 (payload at +24).
    """

    format_name = 'BIN-2352'
    raw_sector_size = RAW_CD_SECTOR_SIZE

    def __init__(self, path, bin_path=None, track_sector_offset=0):
        self.cue_path = path if path != bin_path and bin_path else None
        actual_bin = bin_path or path
        self._fp = open(actual_bin, 'rb')
        self.bin_path = actual_bin
        self.track_sector_offset = track_sector_offset
        size = os.path.getsize(actual_bin)
        total = max(0, (size // RAW_CD_SECTOR_SIZE) - track_sector_offset)
        super().__init__(path, total)
        self.cd_mode = self._detect_mode()

    def _detect_mode(self):
        self._fp.seek(self.track_sector_offset * RAW_CD_SECTOR_SIZE)
        raw = self._fp.read(RAW_CD_SECTOR_SIZE)
        if len(raw) >= 16 and raw[:12] == CD_SYNC_PATTERN:
            mode = raw[15]
            if mode in (1, 2):
                return mode
        return 2  # PS2 CD-ROMs are almost always Mode 2 XA

    @staticmethod
    def extract_user_data(raw_sector, default_mode=2):
        if len(raw_sector) < RAW_CD_SECTOR_SIZE:
            raw_sector = raw_sector.ljust(RAW_CD_SECTOR_SIZE, b'\x00')
        mode = raw_sector[15] if raw_sector[:12] == CD_SYNC_PATTERN else default_mode
        if mode == 1:
            return raw_sector[16:16 + SECTOR_SIZE]
        # Mode 2 XA: 12B sync + 4B header + 8B subheader = 24B offset
        return raw_sector[24:24 + SECTOR_SIZE]

    def read_sectors(self, sector, count):
        if count <= 0 or sector >= self.total_sectors:
            return b''
        clamped = min(count, self.total_sectors - sector)
        phys_sector = self.track_sector_offset + sector
        self._fp.seek(phys_sector * RAW_CD_SECTOR_SIZE)
        raw = self._fp.read(clamped * RAW_CD_SECTOR_SIZE)
        out = bytearray(clamped * SECTOR_SIZE)
        for i in range(clamped):
            chunk = raw[i * RAW_CD_SECTOR_SIZE:(i + 1) * RAW_CD_SECTOR_SIZE]
            if not chunk:
                break
            out[i * SECTOR_SIZE:(i + 1) * SECTOR_SIZE] = self.extract_user_data(chunk, self.cd_mode)
        return bytes(out)

    def close(self):
        if getattr(self, '_fp', None):
            self._fp.close()
            self._fp = None


class CsoDevice(SectorDevice):
    """
    Compressed ISO (.cso) reader supporting standard CISO v1 zlib block streams.
    Header layout (24 bytes):
      0..4   : 'CISO'
      4..8   : header_size (uint32 LE, usually 24)
      8..16  : total_bytes (uint64 LE, uncompressed ISO size)
      16..20 : block_size  (uint32 LE, usually 2048)
      20     : version     (uint8)
      21     : align       (uint8, index shift)
      22..24 : reserved
    """

    format_name = 'CSO-ZLIB'
    raw_sector_size = SECTOR_SIZE

    def __init__(self, path):
        self._fp = open(path, 'rb')
        hdr = self._fp.read(24)
        if len(hdr) < 24 or hdr[:4] != CSO_MAGIC:
            self._fp.close()
            raise ValueError(f'{path}: invalid CISO header')
        _, _, total_bytes, block_size, version, align = struct.unpack('<4sIQIBB2x', hdr)
        if block_size == 0 or block_size % SECTOR_SIZE != 0:
            self._fp.close()
            raise ValueError(f'{path}: unsupported CSO block size {block_size}')
        self.block_size = block_size
        self.sectors_per_block = block_size // SECTOR_SIZE
        self.version = version
        self.align = align
        self.num_blocks = (total_bytes + block_size - 1) // block_size
        idx_bytes = (self.num_blocks + 1) * 4
        idx_raw = self._fp.read(idx_bytes)
        if len(idx_raw) < idx_bytes:
            self._fp.close()
            raise ValueError(f'{path}: truncated CSO block index table')
        self.index = struct.unpack(f'<{self.num_blocks + 1}I', idx_raw)
        self._cache = OrderedDict()
        self._max_cache_blocks = 64
        super().__init__(path, total_bytes // SECTOR_SIZE)

    def _read_block(self, block_idx):
        if block_idx in self._cache:
            self._cache.move_to_end(block_idx)
            return self._cache[block_idx]
        if block_idx < 0 or block_idx >= self.num_blocks:
            return b'\x00' * self.block_size

        entry = self.index[block_idx]
        plain = (entry & 0x80000000) != 0
        next_entry = self.index[block_idx + 1] & 0x7FFFFFFF
        offset = (entry & 0x7FFFFFFF) << self.align
        end_offset = next_entry << self.align
        read_len = max(0, end_offset - offset)

        self._fp.seek(offset)
        raw = self._fp.read(read_len)
        if plain:
            data = raw.ljust(self.block_size, b'\x00')[:self.block_size]
        else:
            # CISO uses raw deflate (-zlib.MAX_WBITS) or standard zlib
            try:
                data = zlib.decompress(raw, -zlib.MAX_WBITS)
            except zlib.error:
                data = zlib.decompress(raw)
            if len(data) < self.block_size:
                data = data.ljust(self.block_size, b'\x00')

        self._cache[block_idx] = data
        if len(self._cache) > self._max_cache_blocks:
            self._cache.popitem(last=False)
        return data

    def read_sectors(self, sector, count):
        if count <= 0 or sector >= self.total_sectors:
            return b''
        clamped = min(count, self.total_sectors - sector)
        out = bytearray(clamped * SECTOR_SIZE)
        for i in range(clamped):
            s = sector + i
            blk = s // self.sectors_per_block
            sub = (s % self.sectors_per_block) * SECTOR_SIZE
            blk_data = self._read_block(blk)
            out[i * SECTOR_SIZE:(i + 1) * SECTOR_SIZE] = blk_data[sub:sub + SECTOR_SIZE]
        return bytes(out)

    def close(self):
        if getattr(self, '_fp', None):
            self._fp.close()
            self._fp = None


def parse_cue_sheet(cue_path):
    """Parse a .cue file to locate its primary data .bin file and sector size."""
    cue_dir = os.path.dirname(os.path.abspath(cue_path))
    bin_file = None
    sector_size = RAW_CD_SECTOR_SIZE
    with open(cue_path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            m_file = re.match(r'^FILE\s+"([^"]+)"', line, re.IGNORECASE) or re.match(r'^FILE\s+(\S+)', line, re.IGNORECASE)
            if m_file and bin_file is None:
                candidate = os.path.join(cue_dir, m_file.group(1))
                if os.path.isfile(candidate):
                    bin_file = candidate
            m_track = re.match(r'^TRACK\s+\d+\s+MODE\d/(\d+)', line, re.IGNORECASE)
            if m_track:
                sector_size = int(m_track.group(1))
    if not bin_file:
        raise ValueError(f'{cue_path}: could not find referenced .bin file')
    return bin_file, sector_size


def open_container(path):
    """
    Auto-detect and open a PS2 disc image container (.iso, .bin, .cue, .cso).
    Checks magic bytes and sector sync patterns before falling back to extension/size.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f'Disc image not found: {path}')

    lower = path.lower()
    if lower.endswith('.cue'):
        bin_path, sec_size = parse_cue_sheet(path)
        if sec_size == RAW_CD_SECTOR_SIZE:
            return Bin2352Device(path, bin_path=bin_path)
        return Iso2048Device(bin_path)

    with open(path, 'rb') as probe:
        head = probe.read(32)
        if head[:4] == CSO_MAGIC:
            return CsoDevice(path)

        # Check if sector 0 has the 12-byte CD-ROM sync pattern AND sector 16 (at 16 * 2352) has CD001
        if head[:12] == CD_SYNC_PATTERN:
            probe.seek(16 * RAW_CD_SECTOR_SIZE)
            sec16_raw = probe.read(RAW_CD_SECTOR_SIZE)
            if len(sec16_raw) >= 32 and (sec16_raw[16:22] == b'\x01CD001' or sec16_raw[24:30] == b'\x01CD001'):
                return Bin2352Device(path)

        # Check standard 2048-byte ISO 9660 PVD at sector 16 (offset 32768)
        probe.seek(16 * SECTOR_SIZE)
        sec16_iso = probe.read(6)
        if sec16_iso == b'\x01CD001':
            return Iso2048Device(path)

        # Also check if a raw 2352-byte image lacked sync at sector 0 but has PVD at 16 * 2352
        probe.seek(16 * RAW_CD_SECTOR_SIZE)
        sec16_raw = probe.read(32)
        if len(sec16_raw) >= 30 and (sec16_raw[16:22] == b'\x01CD001' or sec16_raw[24:30] == b'\x01CD001'):
            return Bin2352Device(path)

    raise ValueError(f'{path}: unrecognized disc container format (neither ISO-2048, BIN-2352, nor CSO)')

#!/usr/bin/env python3
"""
Automated unit tests for the independent PS2 Disc Extraction Toolkit (tools/ps2_disc_toolkit):
1. DVD-9 Dual-Layer ISO-2048 with PVD root_size=0 on Layer 1 and SYSTEM.CNF auto-detection
2. CD-ROM BIN/CUE-2352 (Mode 2 XA Form 1) extraction and verification
3. CSO (CISO zlib compressed) image extraction and verification
4. Hidden-LBA unindexed region splitting (unindexed/region_*.bin) and custom profile regions
"""

import os
import struct
import sys
import tempfile
import unittest
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))

from ps2_disc_toolkit.containers import (  # noqa: E402
    SECTOR_SIZE,
    RAW_CD_SECTOR_SIZE,
    CD_SYNC_PATTERN,
    CSO_MAGIC,
    open_container,
)
from ps2_disc_toolkit.cli import (  # noqa: E402
    extract_disc,
    verify_disc,
    detect_extracted_boot_elf,
)


def make_dir_record(lba, size, name_bytes, is_dir=False):
    name_len = len(name_bytes)
    rec_len = 33 + name_len
    if rec_len % 2 == 1:
        rec_len += 1
    buf = bytearray(rec_len)
    buf[0] = rec_len
    struct.pack_into('<I', buf, 2, lba)
    struct.pack_into('>I', buf, 6, lba)
    struct.pack_into('<I', buf, 10, size)
    struct.pack_into('>I', buf, 14, size)
    buf[25] = 2 if is_dir else 0
    struct.pack_into('<H', buf, 28, 1)
    struct.pack_into('>H', buf, 30, 1)
    buf[32] = name_len
    buf[33:33 + name_len] = name_bytes
    return bytes(buf)


def make_pvd(volume_id, total_sectors, root_lba, root_size):
    pvd = bytearray(SECTOR_SIZE)
    pvd[0:6] = b'\x01CD001'
    pvd[6] = 1
    vol_bytes = volume_id.encode('ascii')[:32].ljust(32, b' ')
    pvd[40:72] = vol_bytes
    struct.pack_into('<I', pvd, 80, total_sectors)
    struct.pack_into('>I', pvd, 84, total_sectors)
    struct.pack_into('<H', pvd, 128, SECTOR_SIZE)
    struct.pack_into('>H', pvd, 130, SECTOR_SIZE)
    root_rec = make_dir_record(root_lba, root_size, b'\x00', is_dir=True)
    pvd[156:156 + len(root_rec)] = root_rec
    return bytes(pvd)


def build_synthetic_dvd9_iso():
    """
    Create a synthetic 80-sector dual-layer DVD-9 ISO:
    - Layer 0: sectors 0..39 (PVD at 16, root dir at 20, SYSTEM.CNF at 21, SLES_999.01 at 22, hidden LBA data at 30..33)
    - Layer 1: base=40, sectors 40..79 (PVD at 56 with root_size=0, root dir at 60, ACT2.LMP at 61..62)
    """
    total_sectors = 80
    l0_sectors = 40
    l1_base = 40
    l1_sectors = 40
    img = bytearray(total_sectors * SECTOR_SIZE)

    syscnf_bytes = b"BOOT2 = cdrom0:\\SLES_999.01;1\r\nVER = 1.02\r\nVMODE = PAL\r\n"
    elf_bytes = b"\x7fELF" + b"SYNTHETIC_PS2_BOOT_EXECUTABLE" * 20
    l1_file_bytes = b"LAYER1_SNOWBLIND_LMP_ARCHIVE_" * 100

    # Layer 0 root directory at sector 20
    l0_root = bytearray()
    dot_pos = 0
    l0_root += make_dir_record(20, 0, b'\x00', is_dir=True)
    l0_root += make_dir_record(20, 0, b'\x01', is_dir=True)
    l0_root += make_dir_record(21, len(syscnf_bytes), b'SYSTEM.CNF;1', is_dir=False)
    l0_root += make_dir_record(22, len(elf_bytes), b'SLES_999.01;1', is_dir=False)
    l0_root_size = len(l0_root)
    struct.pack_into('<I', l0_root, dot_pos + 10, l0_root_size)

    img[16 * SECTOR_SIZE:17 * SECTOR_SIZE] = make_pvd('TEST_DVD9_L0', l0_sectors, 20, l0_root_size)
    img[20 * SECTOR_SIZE:20 * SECTOR_SIZE + l0_root_size] = l0_root
    img[21 * SECTOR_SIZE:21 * SECTOR_SIZE + len(syscnf_bytes)] = syscnf_bytes
    img[22 * SECTOR_SIZE:22 * SECTOR_SIZE + len(elf_bytes)] = elf_bytes

    # Hidden LBA data at sectors 30..33 (4 sectors = 8192 bytes outside ISO 9660 directory tree)
    hidden_data = (b"HIDDEN_LBA_STREAM_BLOCK_" * 342)[:4 * SECTOR_SIZE]
    img[30 * SECTOR_SIZE:34 * SECTOR_SIZE] = hidden_data

    # Layer 1 root directory at relative LBA 20 (absolute sector 40 + 20 = 60)
    l1_root = bytearray()
    l1_root += make_dir_record(20, 0, b'\x00', is_dir=True)
    l1_root += make_dir_record(20, 0, b'\x01', is_dir=True)
    l1_root += make_dir_record(21, len(l1_file_bytes), b'ACT2.LMP;1', is_dir=False)
    l1_root_size = len(l1_root)
    struct.pack_into('<I', l1_root, 10, l1_root_size)

    # Layer 1 PVD at sector 56 (l1_base + 16) intentionally sets root_size=0 to test DVD-9 fallback
    img[56 * SECTOR_SIZE:57 * SECTOR_SIZE] = make_pvd('TEST_DVD9_L1', l1_sectors, 20, 0)
    img[60 * SECTOR_SIZE:60 * SECTOR_SIZE + l1_root_size] = l1_root
    img[61 * SECTOR_SIZE:61 * SECTOR_SIZE + len(l1_file_bytes)] = l1_file_bytes

    return bytes(img)


def convert_iso_to_bin2352(iso_bytes):
    """Wrap 2048-byte ISO sectors into raw 2352-byte Mode 2 XA Form 1 CD-ROM sectors."""
    num_sectors = len(iso_bytes) // SECTOR_SIZE
    out = bytearray(num_sectors * RAW_CD_SECTOR_SIZE)
    for s in range(num_sectors):
        base = s * RAW_CD_SECTOR_SIZE
        out[base:base + 12] = CD_SYNC_PATTERN
        out[base + 15] = 2  # Mode 2 XA
        user = iso_bytes[s * SECTOR_SIZE:(s + 1) * SECTOR_SIZE]
        out[base + 24:base + 24 + SECTOR_SIZE] = user
        out[base + 24 + SECTOR_SIZE:base + RAW_CD_SECTOR_SIZE] = b'\xAA' * (RAW_CD_SECTOR_SIZE - 24 - SECTOR_SIZE)
    return bytes(out)


def convert_iso_to_cso(iso_bytes):
    """Compress 2048-byte ISO bytes into a CISO v1 (.cso) container."""
    num_blocks = len(iso_bytes) // SECTOR_SIZE
    header_size = 24
    index_table = [0] * (num_blocks + 1)
    data_chunks = []
    cur_offset = header_size + (num_blocks + 1) * 4

    for b in range(num_blocks):
        block = iso_bytes[b * SECTOR_SIZE:(b + 1) * SECTOR_SIZE]
        comp_obj = zlib.compressobj(level=6, wbits=-zlib.MAX_WBITS)
        compressed = comp_obj.compress(block) + comp_obj.flush()
        if len(compressed) < SECTOR_SIZE:
            index_table[b] = cur_offset
            data_chunks.append(compressed)
            cur_offset += len(compressed)
        else:
            index_table[b] = cur_offset | 0x80000000
            data_chunks.append(block)
            cur_offset += len(block)
    index_table[num_blocks] = cur_offset

    hdr = struct.pack('<4sIQIBB2x', CSO_MAGIC, header_size, len(iso_bytes), SECTOR_SIZE, 1, 0)
    idx_bytes = struct.pack(f'<{num_blocks + 1}I', *index_table)
    return hdr + idx_bytes + b''.join(data_chunks)


class TestPs2DiscToolkit(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.iso_bytes = build_synthetic_dvd9_iso()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_1_dvd9_iso2048_and_hidden_lba(self):
        iso_path = os.path.join(self.tmpdir.name, 'dvd9.iso')
        out_dir = os.path.join(self.tmpdir.name, 'extracted_dvd9')
        with open(iso_path, 'wb') as f:
            f.write(self.iso_bytes)

        # Use raw_threshold_mb=0.005 (~2 sectors) so the 4-sector hidden LBA block at 30..33 is split to unindexed/
        extract_disc(iso_path, out_dir, raw_threshold_mb=0.005)
        verify_disc(iso_path, out_dir)

        self.assertTrue(os.path.isfile(os.path.join(out_dir, 'layer0', 'SYSTEM.CNF')))
        self.assertTrue(os.path.isfile(os.path.join(out_dir, 'layer0', 'SLES_999.01')))
        self.assertTrue(os.path.isfile(os.path.join(out_dir, 'layer1', 'ACT2.LMP')))
        self.assertTrue(os.path.isfile(os.path.join(out_dir, 'unindexed', 'region_30_4.bin')))

        boot_elf = detect_extracted_boot_elf(out_dir)
        self.assertIsNotNone(boot_elf)
        self.assertEqual(os.path.basename(boot_elf), 'SLES_999.01')

    def test_2_bin_cue_2352_cdrom(self):
        bin_path = os.path.join(self.tmpdir.name, 'cdrom.bin')
        cue_path = os.path.join(self.tmpdir.name, 'cdrom.cue')
        out_dir = os.path.join(self.tmpdir.name, 'extracted_cdrom')

        with open(bin_path, 'wb') as f:
            f.write(convert_iso_to_bin2352(self.iso_bytes))
        with open(cue_path, 'w', encoding='utf-8') as f:
            f.write('FILE "cdrom.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')

        with open_container(cue_path) as dev:
            self.assertEqual(dev.format_name, 'BIN-2352')
            self.assertEqual(dev.total_sectors, 80)

        extract_disc(cue_path, out_dir)
        verify_disc(cue_path, out_dir)
        self.assertTrue(os.path.isfile(os.path.join(out_dir, 'layer1', 'ACT2.LMP')))

    def test_3_cso_compressed_container(self):
        cso_path = os.path.join(self.tmpdir.name, 'compressed.cso')
        out_dir = os.path.join(self.tmpdir.name, 'extracted_cso')

        with open(cso_path, 'wb') as f:
            f.write(convert_iso_to_cso(self.iso_bytes))

        with open_container(cso_path) as dev:
            self.assertEqual(dev.format_name, 'CSO-ZLIB')
            self.assertEqual(dev.total_sectors, 80)

        extract_disc(cso_path, out_dir)
        verify_disc(cso_path, out_dir)
        self.assertTrue(os.path.isfile(os.path.join(out_dir, 'layer0', 'SLES_999.01')))
        self.assertTrue(os.path.isfile(os.path.join(out_dir, 'layer1', 'ACT2.LMP')))


if __name__ == '__main__':
    unittest.main(verbosity=2)

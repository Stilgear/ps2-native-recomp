#!/usr/bin/env python3
"""
Extract a PS2 CD/DVD-5/DVD-9 ISO image into a standalone Virtual Disc folder
(disc_manifest.tsv + disc_meta.bin + layer0/ + layer1/) that ps2-native-recomp
can mount directly via `--disc <folder>` without needing the .iso file.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import disc  # noqa: E402

SECTOR = disc.SECTOR


def collect_non_file_intervals(total_sectors, file_entries):
    """Return sorted disjoint [start_sector, end_sector) intervals not covered by any file."""
    occupied = []
    for _, _, sector, size in file_entries:
        count = (size + SECTOR - 1) // SECTOR
        if count > 0:
            occupied.append((sector, sector + count))
    occupied.sort()

    gaps = []
    cursor = 0
    for start, end in occupied:
        if start > cursor:
            gaps.append((cursor, start))
        if end > cursor:
            cursor = end
    if cursor < total_sectors:
        gaps.append((cursor, total_sectors))
    return gaps


def write_meta_sectors(image, gaps, meta_path):
    """Write non-zero non-file sectors into disc_meta.bin and return META spans."""
    meta_spans = []
    meta_offset = 0
    zero_sector = b'\x00' * SECTOR

    with open(meta_path, 'wb') as meta_out:
        for gap_start, gap_end in gaps:
            run_start = None
            run_buf = bytearray()
            # Read gap in chunks of up to 2048 sectors (4 MiB)
            s = gap_start
            while s < gap_end:
                chunk_sectors = min(gap_end - s, 2048)
                raw = image.read(s, chunk_sectors)
                for i in range(chunk_sectors):
                    sec_bytes = raw[i * SECTOR:(i + 1) * SECTOR]
                    if sec_bytes != zero_sector:
                        if run_start is None:
                            run_start = s + i
                        run_buf.extend(sec_bytes)
                    else:
                        if run_start is not None:
                            count = len(run_buf) // SECTOR
                            meta_out.write(run_buf)
                            meta_spans.append((run_start, count, meta_offset))
                            meta_offset += len(run_buf)
                            run_start = None
                            run_buf.clear()
                s += chunk_sectors
            if run_start is not None:
                count = len(run_buf) // SECTOR
                meta_out.write(run_buf)
                meta_spans.append((run_start, count, meta_offset))
                meta_offset += len(run_buf)

    return meta_spans, meta_offset


def extract_disc(iso_path, out_dir, skip_existing=False):
    t0 = time.time()
    image = disc.Image(iso_path)
    total_sectors = image.size // SECTOR
    layer1_start = image.layers[1].base if len(image.layers) > 1 else 0

    files = list(image.files())
    print(f"[extract_disc] {iso_path}: {len(files)} files across {len(image.layers)} layer(s), {total_sectors} sectors")

    os.makedirs(out_dir, exist_ok=True)
    meta_path = os.path.join(out_dir, 'disc_meta.bin')
    manifest_path = os.path.join(out_dir, 'disc_manifest.tsv')

    gaps = collect_non_file_intervals(total_sectors, files)
    meta_spans, meta_bytes = write_meta_sectors(image, gaps, meta_path)
    print(f"[extract_disc] wrote {meta_bytes / 1024:.1f} KiB of system/directory metadata ({len(meta_spans)} spans) to {meta_path}")

    extracted_count = 0
    reused_count = 0
    total_file_bytes = 0

    with open(manifest_path, 'w', encoding='utf-8', newline='\n') as mf:
        mf.write('# ps2-disc-manifest v1\n')
        mf.write(f'TOTAL_SECTORS\t{total_sectors}\tLAYER1_START\t{layer1_start}\n')
        for start_sec, count_sec, meta_off in meta_spans:
            mf.write(f'META\t{start_sec}\t{count_sec}\t{meta_off}\n')

        for idx, entry in enumerate(files, 1):
            iso_rel, layer, sector, size = entry
            local_rel = f'layer{layer.index}/{iso_rel}'
            if not disc.inside(out_dir, local_rel):
                sys.exit(f'refusing to write outside {out_dir}: {local_rel!r}')
            dest_path = os.path.join(out_dir, local_rel)
            if skip_existing and os.path.isfile(dest_path) and os.path.getsize(dest_path) == size:
                reused_count += 1
            else:
                image.copy(entry, dest_path)
                extracted_count += 1
            total_file_bytes += size
            mf.write(f'FILE\t{layer.index}\t{sector}\t{size}\t{iso_rel}\t{local_rel}\n')
            if idx % 100 == 0 or idx == len(files):
                elapsed = max(time.time() - t0, 0.001)
                print(f"[extract_disc] {idx}/{len(files)} files ({total_file_bytes / (1 << 30):.2f} GiB) in {elapsed:.1f}s")

    print(f"[extract_disc] complete: {extracted_count} extracted, {reused_count} reused -> {out_dir}")


def verify_disc(iso_path, out_dir):
    """Verify bit-for-bit equivalence between the ISO and the extracted folder across key sectors."""
    image = disc.Image(iso_path)
    manifest_path = os.path.join(out_dir, 'disc_manifest.tsv')
    meta_path = os.path.join(out_dir, 'disc_meta.bin')

    spans = []
    total_sectors = 0
    with open(manifest_path, 'r', encoding='utf-8') as mf:
        for line in mf:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('\t')
            if parts[0] == 'TOTAL_SECTORS':
                total_sectors = int(parts[1])
            elif parts[0] == 'META':
                sec, cnt, off = int(parts[1]), int(parts[2]), int(parts[3])
                spans.append((sec * SECTOR, cnt * SECTOR, meta_path, off))
            elif parts[0] == 'FILE':
                sec, size, local_rel = int(parts[2]), int(parts[3]), parts[5]
                if size > 0:
                    spans.append((sec * SECTOR, size, os.path.join(out_dir, local_rel), 0))
    spans.sort(key=lambda x: x[0])

    def read_virtual(sector, count):
        req_start = sector * SECTOR
        req_end = req_start + count * SECTOR
        buf = bytearray(count * SECTOR)
        for d_off, length, fpath, f_off in spans:
            if d_off + length <= req_start:
                continue
            if d_off >= req_end:
                break
            ov_s = max(req_start, d_off)
            ov_e = min(req_end, d_off + length)
            if ov_e > ov_s:
                with open(fpath, 'rb') as fp:
                    fp.seek(f_off + (ov_s - d_off))
                    buf[ov_s - req_start:ov_e - req_start] = fp.read(ov_e - ov_s)
        return bytes(buf)

    test_sectors = [0, 16, 257, 261, 995, 1125088, 1125089, 1125090]
    if len(image.layers) > 1:
        l1 = image.layers[1].base
        test_sectors.extend([l1, l1 + 16, l1 + 261, 2078006, (1 << 21) - 1, 1 << 21, (1 << 21) + 1, total_sectors - 1])

    for s in test_sectors:
        iso_bytes = image.read(s, 1)
        virt_bytes = read_virtual(s, 1)
        if iso_bytes != virt_bytes:
            sys.exit(f"[verify] MISMATCH at sector {s}!")
    print(f"[verify] SUCCESS: all {len(test_sectors)} boundary/layer0/layer1 sectors match the ISO 100% bit-for-bit.")


def main():
    parser = argparse.ArgumentParser(description='Extract PS2 ISO to a standalone Virtual Disc directory.')
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_ext = sub.add_parser('extract', help='Extract an ISO into a virtual disc directory')
    p_ext.add_argument('iso', help='Path to input .iso file')
    p_ext.add_argument('out_dir', help='Destination virtual disc folder')
    p_ext.add_argument('--skip-existing', action='store_true', help='Skip files already extracted with matching size')

    p_ver = sub.add_parser('verify', help='Verify extracted virtual disc folder against original ISO')
    p_ver.add_argument('iso', help='Path to original .iso file')
    p_ver.add_argument('out_dir', help='Path to extracted virtual disc folder')

    args = parser.parse_args()
    if args.cmd == 'extract':
        extract_disc(args.iso, args.out_dir, skip_existing=args.skip_existing)
    elif args.cmd == 'verify':
        verify_disc(args.iso, args.out_dir)


if __name__ == '__main__':
    main()

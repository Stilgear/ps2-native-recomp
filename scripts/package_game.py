#!/usr/bin/env python3
"""
Package a recompiled PS2 game into a standalone, ISO-free native distribution folder.
"""

import argparse
import os
import shutil
import stat
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_disc  # noqa: E402


def package_game(binary_path, elf_path, iso_or_disc_dir, output_dir, keys_path=None, memcard_path=None, link_assets=False):
    if not os.path.isfile(binary_path):
        sys.exit(f"Binary not found: {binary_path}")
    if not os.path.isfile(elf_path):
        sys.exit(f"Guest ELF not found: {elf_path}")

    os.makedirs(output_dir, exist_ok=True)
    data_dir = os.path.join(output_dir, 'data')
    saves_dir = os.path.join(output_dir, 'saves')
    os.makedirs(saves_dir, exist_ok=True)

    bin_name = os.path.basename(binary_path)
    elf_name = os.path.basename(elf_path)
    dst_bin = os.path.join(output_dir, bin_name)
    dst_elf = os.path.join(output_dir, elf_name)

    shutil.copy2(binary_path, dst_bin)
    os.chmod(dst_bin, os.stat(dst_bin).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    shutil.copy2(elf_path, dst_elf)

    if keys_path and os.path.isfile(keys_path):
        shutil.copy2(keys_path, os.path.join(output_dir, 'keys.ini'))

    if memcard_path and os.path.isfile(memcard_path):
        shutil.copy2(memcard_path, os.path.join(saves_dir, 'memcard.ps2'))

    if os.path.isdir(iso_or_disc_dir):
        if link_assets:
            if os.path.lexists(data_dir):
                os.unlink(data_dir) if os.path.islink(data_dir) else shutil.rmtree(data_dir)
            os.symlink(os.path.abspath(iso_or_disc_dir), data_dir)
            print(f"[package_game] linked extracted data directory -> {data_dir}")
        else:
            shutil.copytree(iso_or_disc_dir, data_dir, dirs_exist_ok=True)
            print(f"[package_game] copied extracted data directory -> {data_dir}")
    else:
        extract_disc.extract_disc(iso_or_disc_dir, data_dir, skip_existing=True)

    launch_sh = os.path.join(output_dir, 'launch.sh')
    with open(launch_sh, 'w', encoding='utf-8', newline='\n') as f:
        f.write('#!/usr/bin/env bash\n')
        f.write('set -euo pipefail\n')
        f.write('DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n')
        f.write('cd "$DIR"\n')
        f.write('mkdir -p "$DIR/saves"\n')
        f.write('EXTRA_ARGS=(--widescreen)\n')
        f.write('if [[ " $* " != *" --frames "* && " $* " != *" --window "* && " $* " != *" --fullscreen "* ]]; then\n')
        f.write('  EXTRA_ARGS+=(--window)\n')
        f.write('fi\n')
        f.write(f'exec "$DIR/{bin_name}" "$DIR/{elf_name}" --disc "$DIR/data" --memcard "$DIR/saves/memcard.ps2" "${{EXTRA_ARGS[@]}}" "$@"\n')
    os.chmod(launch_sh, os.stat(launch_sh).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    print(f"[package_game] standalone ISO-free package ready in: {output_dir}")
    print(f"[package_game] launch with: {launch_sh}")


def main():
    parser = argparse.ArgumentParser(description='Package a recompiled PS2 game into a standalone ISO-free folder.')
    parser.add_argument('--binary', required=True, help='Path to compiled native game binary')
    parser.add_argument('--elf', required=True, help='Path to guest boot ELF (e.g. SLES_523.25)')
    parser.add_argument('--disc', required=True, help='Path to .iso image OR already-extracted virtual disc folder')
    parser.add_argument('--out', required=True, help='Output standalone package directory')
    parser.add_argument('--keys', help='Optional keys.ini file to bundle')
    parser.add_argument('--memcard', help='Optional existing .ps2 memory card file to bundle')
    parser.add_argument('--link-assets', action='store_true', help='Symlink data/ to existing extracted disc folder instead of copying')
    args = parser.parse_args()
    package_game(args.binary, args.elf, args.disc, args.out, keys_path=args.keys, memcard_path=args.memcard, link_assets=args.link_assets)


if __name__ == '__main__':
    main()

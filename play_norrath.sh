#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
export PS2_WINDOW_TITLE="Champions of Norrath"
DISC_SRC="games/norrath/disc.iso"
ELF_SRC="games/norrath/disc/SLES_523.25"
if [ -f "games/norrath/disc_files/disc_manifest.tsv" ]; then
  DISC_SRC="games/norrath/disc_files"
  ELF_SRC="games/norrath/disc_files/layer0/SLES_523.25"
fi
exec ./build/native-norrath/ps2run "$ELF_SRC" --disc "$DISC_SRC" --window --widescreen --memcard games/norrath/norrath.ps2 "$@"

# Virtual Disc Folder (`disc_folder`) & Asset Extraction Toolkit (`ps2_disc_toolkit`)

`ps2-native-recomp` can run a game directly from an **extracted virtual disc directory** (`--disc games/<name>/disc_files`) without keeping the original `.iso` / `.bin` / `.cso` / `.chd` disc image around.

Unlike a plain file-only extraction, `tools/ps2_disc_toolkit` preserves the exact 2048-byte sector layout (`disc_manifest.tsv` + `disc_meta.bin` + `unindexed/`), so games that stream assets by raw LBA sector numbers (`sceCdRead`) work identically to a raw disc image while keeping all files on disk open for inspection and modding.

---

## 1. Extracting a Disc Image (`scripts/extract_disc.py`)

Supported input containers:
- **ISO-2048** (`.iso`, single-layer DVD-5 and dual-layer DVD-9 / PTP)
- **BIN/CUE-2352** (`.bin` / `.cue`, CD-ROM Mode 1 & Mode 2 Form 1 XA)
- **CSO** (`.cso`, CISO zlib-compressed images)
- **CHD v5** (`.chd`, MAME Compressed Hunks of Data: `zlib`, `lzma`, `zstd`, `cdzl`, `cdlz`, `cdzs`)

```bash
# 1. Inspect disc metadata, dual-layer PVD, and hidden LBA gaps
python3 scripts/extract_disc.py inspect path/to/game.iso --scan-gaps

# 2. Extract all files + sector manifest into games/<name>/disc_files
python3 scripts/extract_disc.py extract path/to/game.iso games/<name>/disc_files --skip-existing

# 3. Verify sector-for-sector reconstruction against the original image
python3 scripts/extract_disc.py verify path/to/game.iso games/<name>/disc_files
```

Running with the extracted directory:
```bash
./build/native-<name>/ps2run games/<name>/disc_files/layer0/<BOOT_ELF> --disc games/<name>/disc_files
```

---

## 2. Unpacking 2nd-Level Game Archives & Converting PS2 Assets

Many PS2 games pack their 3D models, textures, audio streams, and relocatable overlays inside container files (`.AFS`, `.LMP`, `.GOB`, `.TEX`, `DATA.BIN`, etc.). `extract_disc.py` includes a built-in 2nd-level unpacker and Sony SDK asset converter:

```bash
# List subfiles inside an archive (.AFS, .LMP, .GOB, .TEX)
python3 scripts/extract_disc.py unpack-list games/<name>/disc_files/layer0/DAT.AFS

# Extract and convert PS2 textures (.tm2, .tex, .16 -> .png), audio (.vag -> .wav),
# Metrowerks MWo3 overlays, and Capcom LZ16 containers (.dec.bin)
python3 scripts/extract_disc.py unpack-extract \
  games/<name>/disc_files/layer0/DAT.AFS \
  games/<name>/assets_unpacked/dat_afs \
  --convert --recursive

# Carve TIM2 textures and VAGp audio from proprietary binary containers
python3 scripts/extract_disc.py unpack-extract \
  games/<name>/disc_files/layer0/DATA.BIN \
  games/<name>/assets_unpacked/data_carved \
  --carve --convert
```

---

## 3. Single-File Executable Bundler (`PS2PACK1`, Linux & Windows)

Once a game has been extracted into `games/<name>/disc_files` and compiled, you can package the entire recompiled game—including the host `ps2run` binary, the guest ELF, precompiled `ee-live` caches (`.so` on Linux, `.dll` on Windows), optional JSON assets, and the complete virtual disc (`disc_files/`)—into a **single self-contained executable** per target OS (`<Game>-Linux-x86_64` and `<Game>-Windows-x86_64.exe`).

At launch (0 command-line arguments / double-click), the executable inspects the last 64 bytes of its own binary (`/proc/self/exe` on Linux, `GetModuleFileNameW(NULL)` on Windows) for the `PS2PACK1` trailer. If present:
- It serves all disc sector reads (`sceCdRead`) directly from its own file descriptor via `pread64` / `ReadFile(OVERLAPPED)` (`0 bytes` of temporary disc extraction to `/tmp`).
- It loads the embedded guest ELF directly into RAM.
- It automatically creates a `saves/` folder (`saves/memcard.ps2`, `saves/states/`, `saves/cache/ee-live/`) next to the executable on first launch and seeds any embedded `ee-live` caches.
- If a file inside `games/<name>/disc_files/layer0/` was modified (e.g. modded textures or patched scripts) before bundling, the bundler automatically patches its ISO-9660 directory entry LBA/size inside `disc_meta.bin`.

```bash
# 1. (Optional, fetched automatically when building for Windows)
#    Fetch llvm-mingw UCRT toolchain, SDL2 mingw, and wgpu-native-win into third_party/
sh scripts/fetch_win_cross.sh

# 2. Build a single-file executable for Linux, Windows, or both (--os linux | windows | all)
python3 scripts/extract_disc.py bundle \
  --game <name> \
  --os all \
  --out dist/<GameTitle>
```

Output:
- `dist/<GameTitle>-Linux-x86_64`
- `dist/<GameTitle>-Windows-x86_64.exe` (statically linked against `libc++`, `libunwind`, `winpthread`, `SDL2`, and `wgpu_native`; zero external runtime DLL dependencies)


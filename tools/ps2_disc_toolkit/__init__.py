"""
Independent, multi-format PS2 Disc Extraction & Virtual Disc Packaging Toolkit.
Supports ISO-2048 (DVD-5 / DVD-9), BIN/CUE-2352 (CD-ROM Mode 1 / Mode 2 XA),
and CSO (CISO zlib compressed images), plus configurable engine profiles and
hidden-LBA unindexed region extraction.
"""

from .containers import open_container, SectorDevice, SECTOR_SIZE  # noqa: F401
from .iso9660 import IsoFileSystem, SystemCnf, FileEntry, LayerInfo  # noqa: F401
from .profiles import ProfileConfig, load_profile, match_profile  # noqa: F401

import os
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
REPOSITORY_DIR = PROJECT_ROOT / "repository"

TESSDATA_DIR = PROJECT_ROOT / "tessdata"
TESSERACT_BLACKLIST = "@#!$^&*_|=?><,;®‘"

TMP_DIR = Path(os.environ.get("D2R_LOOT_READER_TMP", Path(tempfile.gettempdir()) / "d2rlootreader"))

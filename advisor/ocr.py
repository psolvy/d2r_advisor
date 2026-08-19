"""OCR of a tooltip crop using Tesseract with the bundled D2R font model."""
import os
import re

import cv2
import pytesseract

from advisor.colors import classify_line_quality, text_mask
from d2rlootreader.cfg import TESSDATA_DIR, TESSERACT_BLACKLIST
from d2rlootreader.screen import preprocess

# Lines that are UI hints, not item data.
_JUNK_PATTERNS = [
    re.compile(r"left click", re.I),
    re.compile(r"hold shift", re.I),
    re.compile(r"right click", re.I),
    re.compile(r"to (equip|drop|move|unequip|compare|use)", re.I),
    re.compile(r"cost:", re.I),
    # Screen/panel headers that can end up inside the tooltip crop. The gold
    # "INVENTORY" title especially poisons the color-based quality hint.
    re.compile(r"^\W*(inventory|stash|horadric cube|mercenary|character|quests|waypoint)\W*$", re.I),
    re.compile(r"^\W*(mana|life|stamina)\s*[:;]", re.I),
    re.compile(r"^\W*page\s+\S+\s*/", re.I),
    # Stash tab labels (any combination, e.g. "Personal Swap." or "Gems").
    re.compile(r"^[\s.,]*((personal|shared|swap|gems|materials|runes)[\s.,]*)+$", re.I),
]

MIN_UPSCALE_HEIGHT = 300
MAX_WIDTH = 900  # downscale huge crops (4K/1440p) — speeds up Tesseract a lot


def _is_junk(line: str) -> bool:
    alnum = sum(ch.isalnum() for ch in line)
    if alnum < 3:
        return True
    # Real tooltip lines always contain words; icon-noise like "+At1 1" doesn't.
    if sum(ch.isalpha() for ch in line) < 3:
        return True
    # Mostly non-letters -> OCR noise from the background.
    if alnum / max(1, len(line)) < 0.4:
        return True
    # Icon-noise reads as runs of digits and 1-3 char fragments
    # ("1 1y Vv Lin 1 Win 1"); real tooltip lines carry a word of 4+ letters.
    tokens = line.split()
    if tokens and not any(sum(ch.isalpha() for ch in t) >= 4 for t in tokens):
        digitish = sum(1 for t in tokens if any(ch.isdigit() for ch in t))
        if digitish >= max(2, len(tokens) // 3):
            return True
    return any(p.search(line) for p in _JUNK_PATTERNS)


def _clean_line(line: str) -> str:
    line = line.strip()
    # Trim trailing garbage after two or more spaces (background bleed).
    line = re.sub(r"\s{3,}\S{1,4}$", "", line)
    return line.strip()


def _ocr_data(rgb, config):
    """OCR returning (lines, boxes): cleaned text lines with their pixel boxes."""
    data = pytesseract.image_to_data(
        rgb, lang="d2r", config=config, output_type=pytesseract.Output.DICT
    )
    grouped = {}  # (block, par, line) -> {"words", "x0", "y0", "x1", "y1"}
    order = []
    for i in range(len(data["text"])):
        word = (data["text"][i] or "").strip()
        if not word:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        x, y = data["left"][i], data["top"][i]
        x1, y1 = x + data["width"][i], y + data["height"][i]
        if key not in grouped:
            grouped[key] = {"words": [], "x0": x, "y0": y, "x1": x1, "y1": y1}
            order.append(key)
        g = grouped[key]
        g["words"].append(word)
        g["x0"], g["y0"] = min(g["x0"], x), min(g["y0"], y)
        g["x1"], g["y1"] = max(g["x1"], x1), max(g["y1"], y1)

    lines, boxes, raw = [], [], []
    for key in order:
        g = grouped[key]
        raw.append(" ".join(g["words"]))
        line = _clean_line(raw[-1])
        if line and not _is_junk(line):
            lines.append(line)
            boxes.append((g["x0"], g["y0"], g["x1"] - g["x0"], g["y1"] - g["y0"]))
    return lines, boxes, "\n".join(raw)


def _prepare(crop_bgr):
    img = crop_bgr
    h, w = img.shape[:2]
    if h and h < MIN_UPSCALE_HEIGHT:
        scale = MIN_UPSCALE_HEIGHT / float(h)
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    elif w > MAX_WIDTH:
        scale = MAX_WIDTH / float(w)
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return img


def scan_tooltip(crop_bgr, tesseract_cmd=None):
    """OCR a tooltip crop.

    Returns (variants, quality_hint, flags):
      variants     — iterator of line-lists (primary color-binarized pass first,
                     plain-grayscale fallback computed lazily);
      quality_hint — item quality ('Unique'/'Set'/'Rare'/'Magic'/'Crafted'/'Base')
                     classified from the color of the first OCR'd line (the item
                     name), or None when unknown;
      flags        — context flags, e.g. {'shop': True} for vendor/gamble
                     tooltips (a "Cost:"/"to Buy" line was present).
    """
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    img = _prepare(crop_bgr)

    # Point tesseract at the bundled d2r.traineddata via env var — avoids any
    # quoting problems with --tessdata-dir on Windows paths.
    os.environ["TESSDATA_PREFIX"] = str(TESSDATA_DIR)
    config = f"-c tessedit_char_blacklist={TESSERACT_BLACKLIST}"

    # Primary pass: binarize by tooltip text colors (kills icons/scenery behind
    # the translucent tooltip) and keep word boxes for color classification.
    mask = text_mask(img)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)))
    binarized = cv2.bitwise_not(mask)  # black text on white
    rgb = cv2.cvtColor(binarized, cv2.COLOR_GRAY2RGB)
    lines1, boxes1, raw1 = _ocr_data(rgb, config)

    # Context flags from the unfiltered text: vendor/gamble tooltips carry
    # "Cost:" / "Right Click to Buy" lines that the junk filter strips.
    flags = {"shop": bool(re.search(r"to buy|cost\s*[:;]", raw1, re.I))}

    # Classify the item-name color. If the first line doesn't classify
    # (residual noise above the title), try the next one.
    hint = None
    for box in boxes1[:2]:
        hint = classify_line_quality(img, box)
        if hint:
            break

    def variants():
        if lines1:
            yield lines1
        # Fallback pass: plain grayscale (slower path, only runs when needed).
        rgb2 = cv2.cvtColor(preprocess(img, mode="none"), cv2.COLOR_GRAY2RGB)
        text = pytesseract.image_to_string(rgb2, lang="d2r", config=config)
        lines2 = []
        for raw in text.splitlines():
            line = _clean_line(raw)
            if line and not _is_junk(line):
                lines2.append(line)
        if lines2:
            yield lines2

    return variants(), hint, flags

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
import pytesseract

from d2rlootreader.cfg import TESSDATA_DIR, TESSERACT_BLACKLIST, TMP_DIR
from d2rlootreader.item_parser import ItemParser
from d2rlootreader.region_selector import select_region
from d2rlootreader.screen import preprocess


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _ensure_output_directory(file_path: str):
    """
    Ensures that the directory for the given file path exists.
    """
    output_dir = Path(file_path).parent
    if output_dir and not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)


def _save_image(image, path: str):
    """
    Saves an image to the specified path and prints a success or error message.
    """
    path = str(path)  # Ensure compatibility with cv2.imwrite
    if cv2.imwrite(path, image):
        print(f"{_timestamp()} Image saved to: {path}")
    else:
        print(f"{_timestamp()} Error: Failed to save image to {path}", file=sys.stderr)


def _save_text(text: str, path: str):
    """
    Saves text to the specified path and prints a success or error message.
    """
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"{_timestamp()} Text output saved to: {path}")
    except Exception as e:
        print(f"{_timestamp()} Error: Failed to save text to {path}: {e}", file=sys.stderr)


def _save_json(obj, path: str):
    """
    Saves a JSON object to the specified path and prints a success or error message.
    """
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        print(f"{_timestamp()} Item JSON saved to: {path}")
    except Exception as e:
        print(f"{_timestamp()} Error: Failed to save JSON to {path}: {e}", file=sys.stderr)


def capture_command(args):
    start_time = datetime.now(timezone.utc)
    command_timestamp = start_time.strftime("%Y%m%d-%H%M%S-%f")[:-3]  # trim to milliseconds

    captured_path = TMP_DIR / f"{command_timestamp}-captured.png"
    processed_path = TMP_DIR / f"{command_timestamp}-processed.png"
    textlog_path = TMP_DIR / f"{command_timestamp}-text.txt"
    jsonlog_path = TMP_DIR / f"{command_timestamp}-item.json"

    print(f"{_timestamp()} Please select the region of the screen to capture.")
    captured_image = select_region()
    if captured_image is None or captured_image.size == 0:
        print(f"{_timestamp()} Selection canceled or empty image.", file=sys.stderr)
        return
    _ensure_output_directory(captured_path)
    _save_image(captured_image, captured_path)

    print(f"{_timestamp()} Preprocessing image...")
    processed = preprocess(captured_image, mode="none")
    _save_image(processed, processed_path)

    print(f"{_timestamp()} Running OCR...")
    # Convert to RGB for pytesseract (OpenCV uses BGR; grayscale needs expansion)
    if len(processed.shape) == 2:
        rgb = cv2.cvtColor(processed, cv2.COLOR_GRAY2RGB)
    else:
        rgb = cv2.cvtColor(processed, cv2.COLOR_BGR2RGB)

    cfg_parts = [
        f"--tessdata-dir {TESSDATA_DIR}",
        f"-c tessedit_char_blacklist={TESSERACT_BLACKLIST}",
    ]
    config_str = " ".join(cfg_parts)

    try:
        text = pytesseract.image_to_string(rgb, lang="d2r", config=config_str)
    except RuntimeError as e:
        print(f"{_timestamp()} Tesseract OCR failed: {e}", file=sys.stderr)
        return

    _save_text(text, textlog_path)

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    print(f"{_timestamp()} Parsing item lines to JSON...")
    item_json = ItemParser(lines).parse_item_lines_to_json()

    _save_json(item_json, jsonlog_path)

    print(f"{_timestamp()} Outputting item JSON to stdout:")
    print(json.dumps(item_json, ensure_ascii=False, indent=2))

    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
    print(f"{_timestamp()} capture-ocr completed in {elapsed:.2f} seconds.")


def main():
    parser = argparse.ArgumentParser(description="D2R Loot Reader CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    capture_parser = subparsers.add_parser(
        "capture", help="Selects a screen region, preprocesses it, extracts text with Tesseract and parses it to JSON"
    )
    capture_parser.set_defaults(func=capture_command)

    args = parser.parse_args()
    if hasattr(args, "func"):
        result = args.func(args)
        if args.command == "capture" and result is not None:
            # Already printed to stdout in capture_ocr_command
            pass
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

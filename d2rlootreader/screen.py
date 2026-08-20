from typing import Literal

import cv2
import mss
import numpy as np

ADAPTIVE_THRESHOLD_BLOCK_SIZE = 21



def capture_monitor_at(cursor):
    """
    Captures only the monitor containing the cursor.

    On multi-monitor setups the virtual desktop is a stitched image whose
    origin differs from cursor coordinates; capturing a single monitor and
    working in its local coordinates avoids that mismatch entirely (and is
    much faster than OCR-scanning an 8K-wide desktop).

    Args:
        cursor: (x, y) in Windows virtual-screen coordinates, or None.

    Returns:
        (img_bgr, local_cursor, monitor_rect) where local_cursor is the cursor
        translated into image coordinates (or None) and monitor_rect is
        (left, top, width, height) in virtual-screen coordinates.
    """
    with mss.mss() as sct:
        monitors = sct.monitors
        mon = None
        if cursor:
            for m in monitors[1:]:
                if (m["left"] <= cursor[0] < m["left"] + m["width"]
                        and m["top"] <= cursor[1] < m["top"] + m["height"]):
                    mon = m
                    break
        if mon is None:
            mon = monitors[1] if len(monitors) > 1 else monitors[0]

        img = np.array(sct.grab(mon))[:, :, :3]
        local = None
        if cursor:
            local = (cursor[0] - mon["left"], cursor[1] - mon["top"])
        return img, local, (mon["left"], mon["top"], mon["width"], mon["height"])



def preprocess(image_bgr: np.ndarray, mode: Literal["otsu", "adaptive", "none"] = "adaptive") -> np.ndarray:
    """
    Converts a BGR image to grayscale and applies thresholding based on the specified mode.
    Output will have WHITE background with BLACK text for optimal OCR performance.

    Args:
        image_bgr (np.ndarray): The input image in BGR format.
        mode (Literal["otsu", "adaptive", "none"]): The thresholding mode to use.
            - "otsu": Uses Otsu's global thresholding. Best for images with a bimodal
                      histogram (e.g., clear foreground/background separation).
            - "adaptive": Uses adaptive Gaussian thresholding. Recommended for images
                          with uneven illumination or varying background intensity.
            - "none": Returns the grayscale image without thresholding.

    Returns:
        np.ndarray: A single-channel uint8 binary image (0 or 255) for "otsu" and
                    "adaptive" modes, or a single-channel uint8 grayscale image for
                    "none" mode. Background will be WHITE (255) and text will be BLACK (0).

    Raises:
        ValueError: If `blockSize` is not an odd integer >= 3 for "adaptive" mode.
    """
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    gray = cv2.bitwise_not(gray)

    if mode == "otsu":
        _, binarized = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return binarized
    elif mode == "adaptive":
        # Validate blockSize
        if not (
            isinstance(ADAPTIVE_THRESHOLD_BLOCK_SIZE, int)
            and ADAPTIVE_THRESHOLD_BLOCK_SIZE >= 3
            and ADAPTIVE_THRESHOLD_BLOCK_SIZE % 2 == 1
        ):
            raise ValueError("blockSize must be an odd integer >= 3 for adaptive thresholding.")
        binarized = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            blockSize=ADAPTIVE_THRESHOLD_BLOCK_SIZE,
            C=4,
        )
        return binarized
    elif mode == "none":
        return gray.astype(np.uint8)
    else:
        raise ValueError(f"Invalid mode: {mode}. Expected 'otsu', 'adaptive', or 'none'.")

"""Reads the contents of one box: empty / tick / single handwritten character."""
import cv2
import numpy as np

from .recognizer import CharClassifier

ALLOWED = {
    "alpha": "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "digit": "0123456789",
    "alnum": "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ",
}
ALLOWED["date_d"] = ALLOWED["date_m"] = ALLOWED["date_y"] = ALLOWED["digit"]

INSET = 5            # pixels trimmed from each side so the printed box border is ignored
MIN_INK_PIXELS = 40  # below this a box is treated as empty (dust / scan noise)
TICK_RATIO = 0.04    # share of a checkbox interior that must be inked to count as ticked

_classifier = None


def classifier():
    global _classifier
    if _classifier is None:
        _classifier = CharClassifier()
    return _classifier


def ink_mask(cell_bgr):
    """Pen strokes inside a cell (any pen colour), with the box border removed.

    The threshold is set per cell, halfway between the paper and the darkest
    ink in that cell, so blurred or low-resolution scans keep true stroke width.
    """
    g = cv2.cvtColor(cell_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    paper, darkest = np.percentile(g, 90), np.percentile(g, 0.5)
    if paper - darkest < 45:  # no real contrast: empty box (just paper / noise)
        return np.zeros(g.shape, np.uint8)
    ink = (g < (paper + darkest) / 2).astype(np.uint8) * 255
    # Drop leftover pieces of the printed box border that survived the inset.
    for k in ((ink.shape[1] * 3 // 4, 1), (1, ink.shape[0] * 3 // 4)):
        line = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, k))
        edge = np.zeros_like(line)
        edge[:3, :], edge[-3:, :], edge[:, :3], edge[:, -3:] = 255, 255, 255, 255
        ink &= ~(line & edge)  # only remove long lines that touch the cell edge
    # Remove specks.
    n, lab, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < 12:
            ink[lab == i] = 0
    return ink


def crop_cell(page_bgr, box, inset=INSET):
    x, y, w, h = box
    return page_bgr[y + inset:y + h - inset, x + inset:x + w - inset]


def is_ticked(page_bgr, box):
    """A checkbox is ticked if enough of its interior is covered by ink."""
    ink = ink_mask(crop_cell(page_bgr, box, inset=6))
    ratio = float((ink > 0).mean())
    return ratio > TICK_RATIO, round(ratio, 3)


def is_single_stroke(ink):
    """True for one straight line (upright or slanted): only I or 1 look like that."""
    ys, xs = np.nonzero(ink)
    if len(xs) < 10:
        return False
    n, _, _, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    if n - 1 > 1:
        return False
    ev = np.linalg.eigvalsh(np.cov(np.vstack([xs, ys]).astype(np.float64)))
    return ev[1] > 0 and np.sqrt(max(ev[0], 0) / ev[1]) < 0.22


def classify_mask(ink, kind):
    """Read one box's pen mask. Returns (character, confidence 0-100, probabilities[36])."""
    probs = classifier().probs(ink)
    allowed = ALLOWED.get(kind, ALLOWED["alnum"])
    if is_single_stroke(ink):
        narrow = "".join(c for c in "I1" if c in allowed)
        if narrow:
            allowed = narrow
    ch, conf = classifier().pick(probs, allowed)
    return ch, conf, probs


def read_char(page_bgr, box, kind):
    """Box-crop reader (kept for tools/tests). Returns (character or '', confidence)."""
    ink = ink_mask(crop_cell(page_bgr, box))
    if int((ink > 0).sum()) < MIN_INK_PIXELS:
        return "", 100.0
    return classify_mask(ink, kind)[:2]

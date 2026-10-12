"""Finds the handwriting that belongs to each box, even when it overflows the box.

Cropping each box on its own clips characters that are written bigger than
the box, and erases strokes that lie on the printed border. Instead we:

 1. find all dark pixels on the page (pen of any colour, plus the printed form),
 2. remove only the printed box lines, at the positions the template says they
    are, and re-join pen strokes that crossed a removed line,
 3. split the page into connected pen strokes and give each stroke to the box
    its centre falls in. A stroke that clearly spans two boxes (two characters
    written joined) is cut at the box border.

The result is a clean white-on-black image per box, however large the writing.
"""
import cv2
import numpy as np

RING = 5            # search distance (px) around each expected printed line
SNAP = 9            # how far (px) a box line may sit from its expected place (photos)
MIN_COMPONENT = 15  # smaller blobs are scan noise
MIN_INK = 40        # a box with less pen ink than this is empty
INK_CONTRAST = 70   # a pen stroke is at least this much darker than the paper (0-255)


def dark_mask(page_bgr):
    """Loose mask of everything darker than the nearby paper (pen and print), plus the
    grey image and local paper level used later to refine each character."""
    g = cv2.cvtColor(page_bgr, cv2.COLOR_BGR2GRAY)
    # paper = the brightest nearby, but ignoring single bright specks: on dim, grainy phone
    # photos they made the paper look brighter than it is, and the grey paper became "ink"
    paper = cv2.dilate(cv2.medianBlur(g, 5), cv2.getStructuringElement(cv2.MORPH_RECT, (41, 41)))
    loose = ((g.astype(np.int16) < paper.astype(np.int16) - 35) * 255).astype(np.uint8)
    return loose, g, paper


LOCAL_SEARCH = 24   # px: how far a row may sit from where the page-wide alignment put it
LABEL_REACH = 260   # px to the left of a row that holds its printed label
CONTEXT = 70        # px above and below a row included when lining it up (neighbouring
                    # rows look alike; their labels make the match unambiguous)


def _structure(gray, blank_boxes):
    """Edges of the printed form (labels, box borders), with the insides of the
    boxes blanked so handwriting does not influence the local line-up."""
    g = gray.copy()
    for x, y, w, h in blank_boxes:
        g[y + 3:y + h - 3, x + 3:x + w - 3] = 255
    g = cv2.GaussianBlur(g, (3, 3), 0).astype(np.float32)
    return cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))


class PageSegmenter:
    def __init__(self, entries, shape, reference=None):
        """entries: template fields on this page (text, date and checkbox).
        reference: the blank reference page, used to correct each row locally
        (paper in a photo is rarely perfectly flat)."""
        h, w = shape[:2]
        self.shape = (h, w)
        entries = [e for e in entries if e["type"] != "image"]   # picture-only areas
        self.entries = entries
        self.all_boxes = [b for e in entries for b in e["cells"]]
        self.ref_struct = None
        if reference is not None:
            self.ref_struct = _structure(cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY), self.all_boxes)
        # Zones where printed lines are expected: a band around every box border.
        hz = np.zeros((h, w), np.uint8)   # horizontal-line zones
        vz = np.zeros((h, w), np.uint8)   # vertical-line zones
        for e in entries:
            for x, y, cw, ch in e["cells"]:
                x0, y0, x1, y1 = x - 2, y - 2, x + cw + 1, y + ch + 1   # approx. line centres
                cv2.rectangle(hz, (x0 - RING, y0 - RING), (x1 + RING, y0 + RING), 255, -1)
                cv2.rectangle(hz, (x0 - RING, y1 - RING), (x1 + RING, y1 + RING), 255, -1)
                cv2.rectangle(vz, (x0 - RING, y0 - RING), (x0 + RING, y1 + RING), 255, -1)
                cv2.rectangle(vz, (x1 - RING, y0 - RING), (x1 + RING, y1 + RING), 255, -1)
        self.hz, self.vz = hz, vz
        self.rows = [e["cells"] for e in entries if e["type"] not in ("check", "flag")]

    def _snap_rows(self, dark, shifts=None):
        """Find where each row's printed box lines really are in this image.

        Photos of slightly bent paper leave the lines a few pixels away from the
        box map. For every row we locate the vertical lines near their expected
        places (one shared shift for the row, then a small local correction) and
        the top/bottom lines, and return the boxes moved onto them plus a mask of
        the printed line pixels. Rows without visible lines (green form) keep the
        box map positions."""
        H, W = dark.shape
        d = (dark > 0).astype(np.float32)
        snapped, vlines = {}, np.zeros_like(dark)
        widths = []                       # measured thickness of the box dividers found
        hwidths = []                      # ... and of the top/bottom lines of the rows
        row_thick = {}                    # first box of a row -> thickness of its top/bottom lines
        shifts = shifts or {}
        # rows and checkboxes first moved by the local correction (if any)
        for e in self.entries:
            dx, dy = shifts.get(tuple(e["cells"][0]), (0, 0))
            if dx or dy:
                snapped[tuple(e["cells"][0])] = [[x + dx, y + dy, w, h] for x, y, w, h in e["cells"]]
        pending = []                      # (x, y0, y1, row height) of dividers to remove
        for cells0 in self.rows:
            cells = snapped.get(tuple(cells0[0]), cells0)
            x0 = cells[0][0] - 2
            y0 = min(c[1] for c in cells) - 2
            y1 = max(c[1] + c[3] for c in cells) + 1
            ch = y1 - y0
            if y0 - SNAP < 0 or y1 + SNAP >= H:
                continue
            # --- vertical lines: columns that are dark over most of the row height
            band = d[y0 + 4:y1 - 3]
            colfrac = band.mean(axis=0)
            borders = [c[0] - 2 for c in cells] + [cells[-1][0] + cells[-1][2] + 1]
            offs = []
            for b in borders:
                lo, hi = max(0, b - SNAP), min(W, b + SNAP + 1)
                seg = colfrac[lo:hi]
                if len(seg) and seg.max() >= 0.7:
                    offs.append(lo + int(np.argmax(seg)) - b)
            if len(offs) < max(2, len(borders) // 3):       # no printed lines here
                continue
            row_off = int(np.median(offs))
            xs = []
            for b in borders:
                lo, hi = max(0, b + row_off - 3), min(W, b + row_off + 4)
                seg = colfrac[lo:hi]
                xs.append(lo + int(np.argmax(seg)) if len(seg) and seg.max() >= 0.5 else b + row_off)
                if len(seg) and seg.max() >= 0.5:
                    x = xs[-1]
                    # how thick is this divider? (dark run through x at mid-height)
                    mid = d[(y0 + y1) // 2, max(0, x - 8):x + 9]
                    c = min(x, 8)
                    if mid[c] > 0:
                        a = c
                        while a > 0 and mid[a - 1] > 0:
                            a -= 1
                        b = c
                        while b + 1 < len(mid) and mid[b + 1] > 0:
                            b += 1
                        widths.append(b - a + 1)
                    pending.append((x, y0, y1, ch))
            # --- top and bottom lines
            span = d[:, xs[0]:xs[-1]]
            rowfrac = span.mean(axis=1)
            ys = []
            n_before = len(hwidths)
            for yb in (y0, y1):
                seg = rowfrac[yb - SNAP:yb + SNAP + 1]
                ys.append(yb - SNAP + int(np.argmax(seg)) if seg.max() >= 0.5 else yb)
                if seg.max() >= 0.5:              # thickness of this line: dark run through it,
                    yl = ys[-1]                   # in the middle of a few boxes
                    for k in range(0, len(cells), max(1, len(cells) // 4)):
                        xc = cells[k][0] + cells[k][2] // 2
                        a = yl
                        while a > yl - 10 and d[a - 1, xc] > 0:
                            a -= 1
                        b = yl
                        while b < yl + 10 and d[b + 1, xc] > 0:
                            b += 1
                        if d[yl, xc] > 0:
                            hwidths.append(b - a + 1)
            if len(hwidths) > n_before:
                row_thick[tuple(cells0[0])] = int(np.median(hwidths[n_before:]))
            snapped[tuple(cells0[0])] = [[xs[k] + 2, ys[0] + 2, xs[k + 1] - xs[k] - 3, ys[1] - ys[0] - 3]
                                         for k in range(len(cells))]
        # Remove the dividers found: dark pixels around each one that form a tall run.
        # Photos that were enlarged or are blurry have thicker lines, so the width
        # removed follows the thickness measured on this image.
        thick = int(np.median(widths)) if len(widths) >= 10 else 3
        half = max(2, (thick + 1) // 2)
        for x, y0, y1, ch in pending:
            col = dark[y0 - 3:y1 + 4, max(0, x - half):x + half + 1]
            tall = cv2.morphologyEx(col, cv2.MORPH_OPEN,
                                    cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(8, int(0.6 * ch)))))
            vlines[y0 - 3:y1 + 4, max(0, x - half):x + half + 1] |= tall
        thick_h = int(np.median(hwidths)) if len(hwidths) >= 10 else 3
        return snapped, vlines, thick, thick_h, row_thick

    def _local_shifts(self, gray):
        """Per row (and checkbox): small (dx, dy) that lines its surroundings up with the
        reference. Returns {first box: (dx, dy)}."""
        if self.ref_struct is None:
            return {}
        page = _structure(gray, self.all_boxes)
        H, W = gray.shape
        out = {}
        for e in self.entries:
            cells = e["cells"]
            x0 = max(0, min(c[0] for c in cells) - LABEL_REACH)
            x1 = min(W, max(c[0] + c[2] for c in cells) + 10)
            y0 = max(0, min(c[1] for c in cells) - CONTEXT)
            y1 = min(H, max(c[1] + c[3] for c in cells) + CONTEXT)
            tpl = self.ref_struct[y0:y1, x0:x1]
            sx0, sy0 = max(0, x0 - LOCAL_SEARCH), max(0, y0 - LOCAL_SEARCH)
            sx1, sy1 = min(W, x1 + LOCAL_SEARCH), min(H, y1 + LOCAL_SEARCH)
            win = page[sy0:sy1, sx0:sx1]
            if tpl.std() < 1 or win.shape[0] < tpl.shape[0] or win.shape[1] < tpl.shape[1]:
                continue
            res = cv2.matchTemplate(win, tpl, cv2.TM_CCOEFF_NORMED)
            _, score, _, loc = cv2.minMaxLoc(res)
            if score > 0.3:
                out[tuple(cells[0])] = (sx0 + loc[0] - x0, sy0 + loc[1] - y0)
        return out

    def ink(self, page_bgr):
        """Pen strokes only (printed box lines removed, crossings repaired).
        Returns a dict used by components() / cell_masks()."""
        dark, gray, paper = dark_mask(page_bgr)
        shifts = self._local_shifts(gray)
        snapped, vsnap, thick, thick_h, row_thick = self._snap_rows(dark, shifts)
        # Printed lines are long, thin and straight; find them only inside the zones
        # (widened a little so lines that sit slightly off in a photo are caught too,
        # and more for thick lines).
        grow = SNAP - RING + max(0, thick_h - 3)
        hz = cv2.dilate(self.hz, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 2 * grow + 1)))
        hl = cv2.morphologyEx(dark & hz, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (30, 1)))
        vl = cv2.morphologyEx(dark & self.vz, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 30)))
        vl |= vsnap
        # Keep only the thin core of each line: a pen stroke lying along the
        # border is thicker than the printed line, so its extra width survives.
        # Blurry or enlarged photos have thicker printed lines: allow for that, measured
        # on this image (normal scans keep the usual limit).
        hl = self._thin_lines(hl, horizontal=True, max_thick=max(5, thick_h + 2))
        vl = self._thin_lines(vl, horizontal=False, max_thick=max(5, thick + 2))
        lines = cv2.dilate(hl | vl, np.ones((3, 3), np.uint8)) & dark
        pen = dark & ~lines
        # Re-join strokes that crossed a line: close small gaps, but only on the line.
        bridged = cv2.morphologyEx(pen, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
        return {"pen": pen | (bridged & lines), "gray": gray, "paper": paper, "lines": lines,
                "snapped": snapped, "thick": thick, "thick_h": thick_h, "row_thick": row_thick}

    @staticmethod
    def _refine(m, ink, X0, Y0):
        """Re-threshold one character halfway between its paper and its own darkest ink,
        so strokes keep their true width (loose mask is too fat on blurry scans)."""
        h, w = m.shape
        g = ink["gray"][Y0:Y0 + h, X0:X0 + w].astype(np.int16)
        paper = ink["paper"][Y0:Y0 + h, X0:X0 + w].astype(np.int16)
        on_line = ink["lines"][Y0:Y0 + h, X0:X0 + w] > 0
        sel = (m > 0) & ~on_line
        if sel.sum() < 10:
            return m
        darkest = np.percentile(g[sel], 3)
        thr = (paper + darkest) / 2.0
        refined = (m > 0) & ((g < thr) | on_line)   # keep repaired line crossings
        return (refined * 255).astype(np.uint8)

    @staticmethod
    def _thin_lines(mask, horizontal, max_thick=5):
        """Drop parts of a detected line that are much thicker than a printed rule."""
        k = (1, max_thick + 2) if horizontal else (max_thick + 2, 1)
        thick = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, k))
        return mask & ~thick

    @staticmethod
    def tick_ratio(ink, box, inset=3):
        """Share of a checkbox's inside covered by pen (box lines already removed)."""
        x, y, w, h = ink["snapped"].get(tuple(box), [box])[0]
        sub = ink["pen"][y + inset:y + h - inset, x + inset:x + w - inset]
        return float((sub > 0).mean()) if sub.size else 0.0

    def components(self, ink):
        n, labels, stats, cents = cv2.connectedComponentsWithStats(ink["pen"], connectivity=8)
        return labels, stats, cents, ink

    def cell_masks(self, comps, cells):
        """For one field (a row of boxes) return one pen mask per box (or None if empty).

        Each mask is cropped to the ink it contains, so writing that sticks out of
        the box is kept whole.
        """
        labels, stats, cents, ink = comps
        cells = ink["snapped"].get(tuple(cells[0]), cells)
        H, W = labels.shape
        xs = [c[0] for c in cells]
        x_lo, x_hi = xs[0] - 4, cells[-1][0] + cells[-1][2] + 4
        y_lo = min(c[1] for c in cells) - 4
        y_hi = max(c[1] + c[3] for c in cells) + 4
        cw = float(np.median([c[2] for c in cells]))
        ch = float(np.median([c[3] for c in cells]))
        line_top = int(np.median([c[1] for c in cells])) - 2                 # printed line centres
        line_bot = int(np.median([c[1] + c[3] for c in cells])) + 1
        # Look a generous distance around the row for strokes whose centre is inside it.
        wy0, wy1 = max(0, int(y_lo - 1.5 * ch)), min(H, int(y_hi + 1.5 * ch))
        wx0, wx1 = max(0, int(x_lo - 2 * cw)), min(W, int(x_hi + 2 * cw))
        ids = np.unique(labels[wy0:wy1, wx0:wx1])
        per_cell = [[] for _ in cells]
        for i in ids:
            if i == 0:
                continue
            x, y, w, h, area = stats[i]
            cx, cy = cents[i]
            if area < MIN_COMPONENT or not (y_lo <= cy <= y_hi) or not (x_lo <= cx <= x_hi):
                continue
            if h > 2.6 * ch or w > 4 * cw:     # e.g. a stray tick or ruled line, not a character
                continue
            if h < 0.3 * ch and w < 0.3 * cw:  # a speck: dust, paper texture, ink dot
                continue
            # A flat, solid piece lying ON the row's top or bottom printed line (its
            # height spans the line's centre) is what is left of a thick or uneven rule
            # in a photo, not handwriting.
            if h <= max(5, 0.25 * ch) and w >= 6 and area >= 0.5 * w * h and any(
                    y <= ly <= y + h - 1 for ly in (line_top, line_bot)):
                continue
            comp = labels[y:y + h, x:x + w] == i
            if (ink["paper"][y:y + h, x:x + w][comp].astype(int)
                    - ink["gray"][y:y + h, x:x + w][comp].astype(int)).max() < INK_CONTRAST:
                continue                        # too faint to be pen (shadow, grid, crease)
            # Which boxes does this stroke cover horizontally?
            cover = [max(0, min(x + w, c[0] + c[2]) - max(x, c[0])) / c[2] for c in cells]
            spanned = [k for k, f in enumerate(cover) if f >= 0.45]
            if len(spanned) >= 2 and w > 1.5 * cw:
                for k in spanned:              # joined characters: cut at the box borders
                    per_cell[k].append((i, cells[k][0] - 2, cells[k][0] + cells[k][2] + 2))
            else:
                k = int(np.argmin([abs(cx - (c[0] + c[2] / 2)) for c in cells]))
                per_cell[k].append((i, None, None))

        out = []
        for k, parts in enumerate(per_cell):
            if not parts:
                out.append(None)
                continue
            xs0 = [stats[i][0] if a is None else max(a, stats[i][0]) for i, a, _ in parts]
            xs1 = [stats[i][0] + stats[i][2] if b is None else min(b, stats[i][0] + stats[i][2]) for i, _, b in parts]
            ys0 = [stats[i][1] for i, _, _ in parts]
            ys1 = [stats[i][1] + stats[i][3] for i, _, _ in parts]
            X0, X1, Y0, Y1 = min(xs0), max(xs1), min(ys0), max(ys1)
            m = np.zeros((Y1 - Y0, X1 - X0), np.uint8)
            sub = labels[Y0:Y1, X0:X1]
            for i, a, b in parts:
                sel = sub == i
                if a is not None:
                    cols = np.arange(X0, X1)
                    sel &= ((cols >= a) & (cols < b))[None, :]
                m[sel] = 255
            m = self._refine(m, ink, X0, Y0)
            mh, mw = m.shape
            if mh < 0.3 * ch and mw > 2.5 * mh:
                out.append(None)              # a flat bar (left-over printed line), not a character
                continue
            out.append(m if int((m > 0).sum()) >= MIN_INK else None)
        return out

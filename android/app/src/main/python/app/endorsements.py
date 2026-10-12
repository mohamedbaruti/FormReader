"""Signatures and stamps on page 2 (items 59, 60, 68, 70, 71).

Checked when the photo of page 2 is added in New Enrolment (FormExtractor.inspect) and again
when the form is read (saved with the record). Settings: app/endorsement_settings.json.

How it works, on the page already straightened onto the reference page:
 1. Ink = everything darker than the paper around it, or clearly coloured (stamps are often
    violet, blue or red), that is NOT printed on the empty reference form. Long straight
    lines (box borders) and specks are removed.
 2. Ink near each box (the box plus stamp_margin_mm around it) is grouped into pieces.
 3. A piece is a STAMP when it is large (stamp_min_mm tall and wide) and looks like a stamp:
    a ring or frame around an empty middle, or many small letters. A signature is long but
    low; a name is low. Each stamp counts for the box nearest to its centre only.
 4. WRITING (name / signature) = ink inside the box itself that is not part of a stamp.
"""
import base64
import json
import os

import cv2
import numpy as np

SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "endorsement_settings.json")
PAGE_WIDTH_MM = 210.0           # A4


def load_settings(path=SETTINGS_PATH):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"enabled": False}


def _ink(page_bgr, ref_gray, pxmm):
    """Pen and stamp ink that is not part of the printed form."""
    g = cv2.cvtColor(page_bgr, cv2.COLOR_BGR2GRAY)
    paper = cv2.dilate(g, np.ones((41, 41), np.uint8))
    diff = paper.astype(np.int16) - g
    dark = diff > 35
    # coloured ink (violet / blue / red stamps can be light): much more colourful than the paper
    hsv = cv2.cvtColor(page_bgr, cv2.COLOR_BGR2HSV)
    s = hsv[..., 1].astype(np.int16)
    s_paper = cv2.medianBlur(hsv[..., 1], 41).astype(np.int16)
    coloured = (s - s_paper > 55) & (diff > 12)
    ink = (dark | coloured).astype(np.uint8)

    # printed on the empty form (with a little room for imperfect straightening)
    rp = cv2.dilate(ref_gray, np.ones((41, 41), np.uint8))
    printed = ((rp.astype(np.int16) - ref_gray) > 35).astype(np.uint8)
    k = max(3, int(round(0.9 * pxmm)) | 1)
    printed = cv2.dilate(printed, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    ink &= 1 - printed

    # long straight lines left over from box borders, and specks
    lh = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((1, int(12 * pxmm)), np.uint8))
    lv = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((int(8 * pxmm), 1), np.uint8))
    ink &= 1 - (lh | lv)
    ink = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    return ink


def other_cells(template, page):
    """Boxes of the ordinary fields on a page of a template (everything but pictures)."""
    return [tuple(c) for f in template.get("fields", []) if f.get("page") == page and f.get("type") != "image"
            for c in f.get("cells", [])]


def _rect(b, pxmm, margin, shape):
    x, y, w, h = b
    m = margin or {}
    x0 = max(0, int(x - m.get("side", 0) * pxmm))
    y0 = max(0, int(y - m.get("top", 0) * pxmm))
    x1 = min(shape[1], int(x + w + m.get("side", 0) * pxmm))
    y1 = min(shape[0], int(y + h + m.get("bottom", 0) * pxmm))
    return x0, y0, x1, y1


def _dist(cx, cy, b):
    x, y, w, h = b
    dx = max(x - cx, 0, cx - (x + w))
    dy = max(y - cy, 0, cy - (y + h))
    return (dx * dx + dy * dy) ** 0.5


def _ring_cover(piece, pxmm, min_mm):
    """Best share (0-1) of a circle's circumference covered by ink, over circles found in the piece."""
    img = cv2.GaussianBlur(piece * 255, (5, 5), 1.5)
    # round stamps are 22-60 mm across (a smaller circle fits through any line of text)
    rmin, rmax = int(max(11.0, min_mm / 2) * pxmm), int(30 * pxmm)
    circles = cv2.HoughCircles(img, cv2.HOUGH_GRADIENT, dp=1.5, minDist=4 * pxmm, param1=100,
                               param2=max(12, int(0.9 * rmin)), minRadius=rmin, maxRadius=rmax)
    if circles is None:
        return 0.0
    tol = max(1, int(round(0.6 * pxmm)))
    near = cv2.dilate(piece, np.ones((2 * tol + 1, 2 * tol + 1), np.uint8))
    best = 0.0
    for cx, cy, r in circles[0][:8]:
        a = np.linspace(0, 2 * np.pi, 120, endpoint=False)
        xs = np.round(cx + r * np.cos(a)).astype(int)
        ys = np.round(cy + r * np.sin(a)).astype(int)
        ok = (xs >= 0) & (ys >= 0) & (xs < piece.shape[1]) & (ys < piece.shape[0])
        if ok.mean() < 0.6:                 # mostly outside what is visible
            continue
        hit = np.zeros(len(a), bool)
        hit[ok] = near[ys[ok], xs[ok]] > 0
        # every quarter of the circle must have ink (a signature never goes all the way round)
        quarters = [hit[q * 30:(q + 1) * 30][ok[q * 30:(q + 1) * 30]] for q in range(4)]
        if any(len(qq) and qq.mean() < 0.45 for qq in quarters):
            continue
        best = max(best, hit[ok].mean() * min(1.0, ok.mean() / 0.85))
    return best


def _frame_cover(piece, pxmm):
    """Share of the edges of the piece's box that are covered by ink (the weakest side counts)."""
    h, w = piece.shape
    t = max(2, int(round(1.5 * pxmm)))
    sides = [piece[:t, :].any(axis=0), piece[-t:, :].any(axis=0), piece[:, :t].any(axis=1), piece[:, -t:].any(axis=1)]
    return float(min(s.mean() for s in sides))


def _is_stamp(piece, pxmm, min_mm, cells=None):
    """piece: 0/1 ink of one group, cropped to its bounding box. cells: same size, 1 inside the
    boxes of other fields (handwritten digits there are not a stamp's letters)."""
    h, w = piece.shape
    if h < min_mm * pxmm or w < min_mm * pxmm:
        return False
    fill = piece.mean()
    if fill > 0.6:                    # a solid blot (fingerprint, scribbled-out area)
        return False
    # a round stamp: ink follows a circle most of the way round (even where pieces of the ring
    # were removed together with a printed line)
    if _ring_cover(piece, pxmm, min_mm) >= 0.6:
        return True
    # a rectangular stamp: ink runs along all four sides of a frame
    if _frame_cover(piece, pxmm) >= 0.55:
        return True
    # lettering: many separate small pieces of ink spread over a large area
    # (letter-sized pieces only: specks and long strokes do not count)
    n, _, stats, cents = cv2.connectedComponentsWithStats(piece, connectivity=8)
    # A stamp's letters are many and all about the same height; handwriting is uneven.
    hs = np.array([stats[i, cv2.CC_STAT_HEIGHT] for i in range(1, n)
                   if stats[i, cv2.CC_STAT_AREA] >= 0.6 * pxmm * pxmm
                   and not (cells is not None and cells[int(cents[i][1]), int(cents[i][0])])
                   and 1.8 * pxmm <= stats[i, cv2.CC_STAT_HEIGHT] <= 7 * pxmm
                   and stats[i, cv2.CC_STAT_WIDTH] <= 9 * pxmm], float)
    return len(hs) >= 14 and hs.std() / hs.mean() <= 0.3


def _writing_in_stamp(page_bgr, pix_mask, min_px):
    """A signature written over a stamp touches it and joins it. Try to tell them apart by
    colour (black or blue pen on a violet / red stamp): True = a second ink was found,
    None = could not tell (same colour, or a black-and-white scan)."""
    ys, xs = np.nonzero(pix_mask)
    if len(ys) < 2 * min_px:
        return None
    # only the dark middle of the strokes: the edges are mixed with the paper colour
    g = cv2.cvtColor(page_bgr, cv2.COLOR_BGR2GRAY).astype(np.int16)
    paper = cv2.dilate(g.astype(np.uint8), np.ones((41, 41), np.uint8)).astype(np.int16)
    depth = (paper - g)[ys, xs]
    core = depth >= 0.65 * np.percentile(depth, 95)
    ys, xs = ys[core], xs[core]
    if len(ys) < 2 * min_px:
        return None
    lab = cv2.cvtColor(page_bgr, cv2.COLOR_BGR2LAB)[ys, xs].astype(np.float32)
    feats = lab[:, 1:3].copy()             # colour (a, b); darkness is tested separately below
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
    cv2.setRNGSeed(12345)
    def solid(sel):
        # the second ink must form real strokes, not just the thin edges of the stamp's lines
        m = np.zeros(pix_mask.shape, np.uint8)
        m[ys[sel], xs[sel]] = 1
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
        return cv2.erode(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))).sum() >= 0.2 * min_px

    # 1. two clearly different colours (black pen on a violet or red stamp)
    _, lbl, centers = cv2.kmeans(feats, 2, None, crit, 3, cv2.KMEANS_PP_CENTERS)
    lbl = lbl.ravel()
    sizes = np.bincount(lbl, minlength=2)
    small = int(np.argmin(sizes))
    far = float(np.linalg.norm(centers[0] - centers[1]))
    spread = max(float(np.sqrt(((feats[lbl == k] - centers[k]) ** 2).sum(1).mean())) for k in (0, 1) if sizes[k])
    if far >= 28 and far >= 2.2 * spread and 0.6 * min_px <= sizes[small] <= 0.75 * len(ys) and solid(lbl == small):
        return True
    # 2. a much darker ink over a lighter one (black pen on a blue or green stamp)
    L = lab[:, 0].reshape(-1, 1).copy()
    _, lb, cl = cv2.kmeans(L, 2, None, crit, 3, cv2.KMEANS_PP_CENTERS)
    lb = lb.ravel()
    dark = int(np.argmin(cl.ravel()))
    n_dark = int((lb == dark).sum())
    gap = float(abs(cl[0, 0] - cl[1, 0]))
    if gap >= 36 and 0.6 * min_px <= n_dark <= 0.75 * len(ys) and solid(lb == dark):
        return True
    return None


def _thumb(img, max_w=420):
    k = min(1.0, max_w / img.shape[1])
    small = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k < 1 else img
    ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 78])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode() if ok else None


def check(aligned_page, ref_gray, form_id, settings=None, images=True, other_cells=()):
    """Signatures and stamps of one straightened page 2. None when this edition has no boxes
    listed (or the check is switched off). Otherwise:
    {"ok": bool, "missing": n, "items": [{"id", "numbers", "label", "label_en", "needs",
      "stamp", "writing", "writing_pieces", "missing": [...], "notes": [...], "ok", "image"}]}
    other_cells: boxes of the other fields on this page (dates, section H...): handwriting in them
    belongs to those fields and is left out."""
    cfg = settings or load_settings()
    boxes = (cfg.get("boxes") or {}).get(form_id)
    if not cfg.get("enabled", True) or not boxes:
        return None
    H, W = aligned_page.shape[:2]
    pxmm = W / PAGE_WIDTH_MM
    margin = cfg.get("stamp_margin_mm", {"top": 12, "bottom": 12, "side": 4})
    min_mm = float(cfg.get("stamp_min_mm", 14))
    min_px = float(cfg.get("min_writing_mm2", 4)) * pxmm * pxmm

    ink = _ink(aligned_page, ref_gray, pxmm)
    # only look near the boxes
    area = np.zeros_like(ink)
    for b in boxes.values():
        x0, y0, x1, y1 = _rect(b, pxmm, margin, ink.shape)
        area[y0:y1, x0:x1] = 1
    ink &= area
    cellmask = np.zeros_like(ink)                  # inside the form's other boxes (dates, section H)
    for cx, cy, cw, ch in other_cells:
        cellmask[max(0, cy + 1):cy + ch - 1, max(0, cx + 1):cx + cw - 1] = 1

    # group ink into pieces (strokes closer than ~3.5 mm belong together; this also bridges the gaps
    # where a stamp crosses a printed line, which is removed with the printed form)
    k = max(3, int(round(3.5 * pxmm)) | 1)
    grouped = cv2.dilate(ink, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    n, labels, stats, cents = cv2.connectedComponentsWithStats(grouped, connectivity=8)
    # which box each pixel is nearest to (a stamp is counted only for the box(es) it really sits on)
    names = list(boxes)
    yy, xx = np.mgrid[0:ink.shape[0], 0:ink.shape[1]].astype(np.float32)
    nearest = np.argmin(np.stack([np.hypot(np.maximum.reduce([bx - xx, np.zeros_like(xx), xx - (bx + bw)]),
                                           np.maximum.reduce([by - yy, np.zeros_like(yy), yy - (by + bh)]))
                                  for bx, by, bw, bh in (boxes[nm] for nm in names)]), axis=0) if names else None
    stamp_mask = np.zeros_like(ink)        # the area stamps cover (their outline, filled in)
    stamps_for = {name: 0 for name in boxes}
    stamp_ids = set()
    grow = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    for i in range(1, n):
        x, y, w, h = stats[i, :4]
        piece = (ink[y:y + h, x:x + w] & (labels[y:y + h, x:x + w] == i)).astype(np.uint8)
        cm = cellmask[y:y + h, x:x + w]
        if not piece.any() or not _is_stamp(piece, pxmm, min_mm, cm):
            continue
        found = False
        for j, nm in enumerate(names):         # two stamps side by side can touch: judge each box's share
            part = piece & (nearest[y:y + h, x:x + w] == j)
            if not part.any():
                continue
            pys, pxs = np.nonzero(part)
            sub = part[pys.min():pys.max() + 1, pxs.min():pxs.max() + 1]
            if _is_stamp(sub, pxmm, min_mm, cm[pys.min():pys.max() + 1, pxs.min():pxs.max() + 1]):
                stamps_for[nm] += 1
                found = True
        if found:
            stamp_ids.add(i)

    def hull_of(ids):
        out = np.zeros_like(ink)
        for i in ids:
            x, y, w, h = stats[i, :4]
            pys, pxs = np.nonzero(ink[y:y + h, x:x + w] & (labels[y:y + h, x:x + w] == i))
            if len(pys):
                cv2.fillConvexPoly(out, cv2.convexHull(np.column_stack([pxs + x, pys + y]).astype(np.int32)), 1)
        return cv2.dilate(out, grow)

    # parts of a stamp that broke away (letters, pieces of the ring) lie inside its outline: join them
    for _ in range(2):
        if not stamp_ids:
            break
        stamp_mask = hull_of(stamp_ids)
        more = set()
        for i in range(1, n):
            if i in stamp_ids:
                continue
            x, y, w, h = stats[i, :4]
            own = ink[y:y + h, x:x + w] & (labels[y:y + h, x:x + w] == i)
            if own.sum() and (own & stamp_mask[y:y + h, x:x + w]).sum() >= 0.5 * own.sum():
                more.add(i)
        if not more:
            break
        stamp_ids |= more
    stamp_mask = hull_of(stamp_ids) if stamp_ids else stamp_mask

    items, missing_total = [], 0
    for chk in cfg.get("checks", []):
        b = boxes.get(chk["id"])
        if not b:
            continue
        x, y, w, h = b
        inside = ink[y:y + h, x:x + w] & (1 - cellmask[y:y + h, x:x + w])
        writing = inside & (1 - stamp_mask[y:y + h, x:x + w])
        mark_px = int(inside.sum())
        writing_px = int(writing.sum())
        # separate pieces of writing (a name and a signature are apart from each other)
        # separate pieces of writing (a name and a signature are apart: side by side or one above
        # the other)
        pieces = 0
        if writing_px >= min_px:
            kk = max(3, int(round(3 * pxmm)) | 1)
            nw, _, ws, _ = cv2.connectedComponentsWithStats(
                cv2.dilate(writing, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kk, kk))), connectivity=8)
            pieces = sum(1 for j in range(1, nw) if ws[j, cv2.CC_STAT_AREA] >= 2 * min_px)
        has_stamp = stamps_for.get(chk["id"], 0) > 0
        has_writing = writing_px >= min_px
        if not has_writing and (stamp_mask[y:y + h, x:x + w] & inside).sum() >= min_px:
            # the signature may be written over the stamp: True (seen by its colour) or None (can't tell)
            has_writing = _writing_in_stamp(aligned_page[y:y + h, x:x + w],
                                            stamp_mask[y:y + h, x:x + w] & inside, min_px)
        miss, notes = [], []
        for need in chk.get("needs", []):
            if need == "mark" and mark_px < min_px:
                miss.append("signature or fingerprint")
            elif need in ("writing", "name_signature") and has_writing is False:
                miss.append("name and signature" if need == "name_signature" else "signature")
            elif need == "stamp" and not has_stamp:
                miss.append("stamp")
        wants_writing = any(nd in ("writing", "name_signature") for nd in chk.get("needs", []))
        if has_writing is None and wants_writing:
            notes.append("The writing is on top of the stamp in the same colour, so the reader cannot tell "
                         "whether the " + ("name and signature are" if "name_signature" in chk.get("needs", []) else "signature is")
                         + " there: look at the picture.")
        elif ("name_signature" in chk.get("needs", []) and has_writing and pieces == 1
              and np.ptp(np.nonzero(writing.any(axis=1))[0]) < 8 * pxmm):   # one low line of writing
            notes.append("Only one piece of writing found: check that both the name and the signature are there.")
        numbers = (cfg.get("numbers_by_form") or {}).get(form_id, {}).get(chk["id"]) or chk.get("numbers")
        item = {"id": chk["id"], "numbers": numbers, "label": chk.get("label"),
                "label_en": chk.get("label_en"), "needs": chk.get("needs", []),
                "stamp": has_stamp,
                # True / False, or None = cannot tell (writing on top of a stamp of the same colour)
                "writing": has_writing if "mark" not in chk.get("needs", []) else mark_px >= min_px,
                "writing_pieces": pieces, "missing": miss, "notes": notes, "ok": not miss}
        if images:
            x0, y0, x1, y1 = _rect(b, pxmm, {"top": 6, "bottom": 6, "side": 2}, ink.shape)
            crop = aligned_page[y0:y1, x0:x1].copy()
            cv2.rectangle(crop, (x - x0, y - y0), (x - x0 + w, y - y0 + h), (200, 140, 30), 1)
            item["image"] = _thumb(crop)
        missing_total += len(miss)
        items.append(item)
    unsure = sum(1 for i in items if i["notes"])
    return {"ok": missing_total == 0, "missing": missing_total, "unsure": unsure, "items": items}

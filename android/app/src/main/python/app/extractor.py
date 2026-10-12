"""Turns an uploaded PDF into the JSON record, using the saved template."""
import json
import os
import re
import time
from collections import OrderedDict

import cv2
import numpy as np

from .cells import classify_mask
TICK_RATIO = 0.10   # share of a checkbox that must be inked to count as ticked
from .recognizer import CLASSES, CharClassifier
from .segment import PageSegmenter
from . import endorsements
from .imaging import MIN_SIFT_INLIERS, Aligner, load_pages

FORMS_DIR = os.path.join(os.path.dirname(__file__), "forms")
MIN_DETECT_INLIERS = 25   # below this, the photo does not look like any known page
MIN_FULL_INLIERS = 60     # the same, when matched at full size (more points are found there)
MIN_WEAK_SIFT = 25        # second method: fewer agreeing points than MIN_SIFT_INLIERS are accepted
GOOD_GRID_FIT = 9.0       #   when the page's box map clearly lands on the printed boxes
BLANK_SHARE = 0.04        # writing found in under 4 % of a page's boxes, and nothing ticked
                          # = probably an empty form (a filled page has 25-50 %)
DETECT_SIZE = 900   # long side (px) of the small images used to recognise the edition
# Fields containing a character the model is less than this sure of (0-100) are
# listed in "needs_review". The model tends to be over-confident, so keep it high.
LOW_CONFIDENCE = 90

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
DIGITS = "0123456789"
PREFIX_LOOKALIKES = "OIDQ"   # letters that are really 0/1 when they start an ID number


def decode_alnum(cells, fmt=None):
    """Choose letters or digits in mixed fields, using the model's probabilities
    rather than only its first guess.

    cells: list of (char, confidence, probabilities) per box, char '' = empty box.
    fmt:   optional box-by-box format from field_formats.json, e.g. "LLDDDDDDDD"
           (L = letter, D = digit, * = either, space = must be empty).
    Without a format, each word is read whichever way is more likely overall:
    - as letters (B0X -> BOX, MKWA4A -> MKWAYA), or
    - as an ID number: up to 2 leading letters (TZ, S, AB...) then digits
      (TZ9D184729 -> TZ90184729, SO3120089 -> S03120089),
    - a one-character word follows the nearest longer word (the O in "P O BOX").
    Returns the new list of (char, confidence).
    """
    if fmt:
        out = []
        for k, (c, conf, p) in enumerate(cells):
            rule = fmt[k] if k < len(fmt) else "*"
            if not c:
                out.append(("", 100.0))
            elif rule == "L":
                out.append(CharClassifier.pick(p, LETTERS))
            elif rule == "D":
                out.append(CharClassifier.pick(p, DIGITS))
            else:
                out.append((c, conf))
        return out

    # Split into words (runs of filled boxes).
    words, cur = [], []
    for k, c in enumerate(cells):
        if c[0]:
            cur.append(k)
        elif cur:
            words.append(cur)
            cur = []
    if cur:
        words.append(cur)

    def best_reading(ks):
        """Compare the whole word read as letters vs as an ID number, using the
        model's probabilities. Returns (is_digit_word, n_prefix_letters)."""
        lp_let = [np.log(max(cells[k][2][10:].max(), 1e-6)) for k in ks]   # best letter
        lp_dig = [np.log(max(cells[k][2][:10].max(), 1e-6)) for k in ks]   # best digit
        letters_score = sum(lp_let)
        best = (letters_score, False, 0)
        if len(ks) < 2:
            return best[1], best[2]
        # ID numbers: up to 2 leading letters (TZ.., S.., AB..) then digits.
        # O, I, D, Q look like 0/1, so they are never taken as a prefix.
        for n_pre in range(0, min(2, len(ks) - 2) + 1):
            pre = [cells[k] for k in ks[:n_pre]]
            if any(CharClassifier.pick(c[2], LETTERS)[0] in PREFIX_LOOKALIKES for c in pre):
                continue
            score = sum(lp_let[:n_pre]) + sum(lp_dig[n_pre:]) + n_pre * np.log(0.7)
            if score > best[0]:
                best = (score, True, n_pre)
        return best[1], best[2]

    kinds = [best_reading(w) if len(w) > 1 else None for w in words]
    for i, w in enumerate(words):
        if kinds[i] is None:   # one-character word: follow the nearest longer word
            after = [kinds[j] for j in range(i + 1, len(words)) if kinds[j] is not None]
            before = [kinds[j] for j in range(i - 1, -1, -1) if kinds[j] is not None]
            near = after[0] if after else before[0] if before else None
            if near is None:
                near = (cells[w[0]][0].isdigit(), 0)
            kinds[i] = (near[0], 0)

    out = [("", 100.0)] * len(cells)
    for w, (digit_word, n_pre) in zip(words, kinds):
        for j, k in enumerate(w):
            p = cells[k][2]
            if digit_word and j >= n_pre:
                out[k] = CharClassifier.pick(p, DIGITS)
            else:
                out[k] = CharClassifier.pick(p, LETTERS)
    return out


# Dates in enrolment: the day is read as 00-31, the month as 00-12 and the year as 19xx or 20xx,
# choosing the most likely digits that make such a number (a "9" that could be a "1"...).
# Not used on the Training page, where the reading must show what is really written.
DATE_LIMITS = {"date_d": (0, 31), "date_m": (0, 12), "date_y": (1900, 2099)}


def plausible_number(full, cells, kind):
    """full: (char, confidence, probabilities) per box; cells: (char, confidence) per box.
    Returns cells with the digits replaced by the most likely number inside DATE_LIMITS[kind]."""
    filled = [k for k, c in enumerate(full) if c[0] and c[2] is not None]
    lo, hi = DATE_LIMITS[kind]
    width = len(str(hi))
    if len(filled) != width:                 # e.g. a day written with one digit: leave it
        return cells
    P = [np.clip(np.asarray(full[k][2][:10], float), 1e-9, 1) for k in filled]   # digits 0-9
    best, best_lp = None, -np.inf
    for n in range(lo, hi + 1):
        digits = str(n).zfill(width)
        lp = sum(np.log(P[i][int(d)]) for i, d in enumerate(digits))
        if lp > best_lp:
            best, best_lp = digits, lp
    out = list(cells)
    for i, k in enumerate(filled):
        d = best[i]
        conf = float(P[i][int(d)] / P[i].sum() * 100)
        out[k] = (d, round(conf, 1) if d == cells[k][0] else min(conf, cells[k][1]))
    return out


VOCAB_DIR = os.path.join(os.path.dirname(__file__), "vocab")


def load_vocab():
    """Place-name lists (app/vocab/*.txt) -> {category: {length: [(name, letters)]}}."""
    out = {}
    for cat in ("countries", "regions", "districts"):
        path = os.path.join(VOCAB_DIR, cat + ".txt")
        if not os.path.exists(path):
            continue
        names = set()
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                w = " ".join(line.strip().upper().split())
                if w and not w.startswith("#"):
                    names.add(w)
                    if cat == "districts" and " " not in w:
                        names.update({w + " MJINI", w + " VIJIJINI"})
        by_len = {}
        for w in sorted(names):
            letters = w.replace(" ", "")
            if letters.isalpha():
                by_len.setdefault(len(letters), []).append((w, letters))
        out[cat] = by_len
    return out


def vocab_category(field):
    if "country" in field:
        return "countries"
    if field.endswith("_region"):
        return "regions"
    if field.endswith("_district"):
        return "districts"
    return None


# How much less likely (log, per letter) a listed name may be than the raw reading.
# Short lists of very different names (countries, regions) can be more lenient.
VOCAB_MARGIN = {"countries": 1.6, "regions": 1.4, "districts": 1.1}
SKIP_PENALTY = 3.0   # cost (log) of assuming one box was missed or added by the writer


def _name_score(P, letters):
    """Log-likelihood of `letters` for boxes with log-probabilities P (n x 36),
    allowing one extra or one missing box."""
    idx = [CLASSES.index(ch) for ch in letters]
    n, m = len(P), len(idx)
    if n == m:
        return P[np.arange(n), idx].sum()
    if n == m + 1:        # one extra box (a stray mark or a split letter)
        return max(np.delete(P, k, 0)[np.arange(m), idx].sum() for k in range(n)) - SKIP_PENALTY
    if n + 1 == m:        # one letter missing (not written, or two letters in one box)
        return max(P[np.arange(n), idx[:k] + idx[k + 1:]].sum() for k in range(m)) - SKIP_PENALTY
    return -np.inf


def snap_to_vocab(probs, raw_text, by_len, margin):
    """Replace a reading with a listed name when the handwriting supports it.

    probs: 36-way probabilities of each filled box, in order. Every listed name
    of about the same length is scored by how likely its letters are in those
    boxes; the best is used if it is not much less likely than the raw reading.
    Returns the name, or None to keep the raw reading."""
    if not probs:
        return None
    P = np.log(np.clip(np.array(probs), 1e-6, 1))
    n = len(P)
    raw = P[:, 10:].max(axis=1).sum()                    # best letters, box by box
    best, best_score = None, -np.inf
    for L in (n - 1, n, n + 1):
        for name, letters in by_len.get(L, []):
            sc = _name_score(P, letters)
            if sc > best_score:
                best, best_score = name, sc
    if best is None or best.replace(" ", "") == raw_text.replace(" ", ""):
        return None
    return best if best_score >= raw - margin * n else None


def load_formats(path):
    """field_formats.json: {"field_name": "box-by-box format", ...}; keys starting with _ are notes."""
    try:
        with open(path, encoding="utf-8") as fh:
            return {k: v for k, v in json.load(fh).items() if not k.startswith("_")}
    except FileNotFoundError:
        return {}


def label_for(name):
    return name.replace("_", " ").capitalize()


class FormLayout:
    """One edition of the form: its box map, reference pages and readers."""

    def __init__(self, folder):
        with open(os.path.join(folder, "template.json")) as fh:
            self.tpl = json.load(fh)
        self.id = self.tpl.get("id", os.path.basename(folder))
        self.title = self.tpl.get("title", self.id)
        self.dpi = self.tpl["dpi"]
        self.n_pages = self.tpl["pages"]
        # identifies each page's printed layout; editions can share a page (1.4 green and
        # white have different page 1s but the same page 2)
        self.page_ids = self.tpl.get("page_ids") or [f"{self.id}_p{p + 1}" for p in range(self.n_pages)]
        # other looks of each page (faded scan, grey photocopy...), already lined up onto the
        # reference: app/forms/<edition>/variants/page_<N>_*.jpg (added with tools/add_page_look.py)
        import glob as _glob
        self.aligners = [Aligner(cv2.imread(os.path.join(folder, f"page_{p}.png")),
                                 variants=[cv2.imread(v) for v in sorted(
                                     _glob.glob(os.path.join(folder, "variants", f"page_{p}_*.jpg")))])
                         for p in range(self.n_pages)]
        refs = [cv2.imread(os.path.join(folder, f"page_{p}.png")) for p in range(self.n_pages)]
        self.segmenters = [
            PageSegmenter([f for f in self.tpl["fields"] if f["page"] == p], self.tpl["page_size"][p][::-1],
                          reference=refs[p])
            for p in range(self.n_pages)]
        # small copies of each page, used only to recognise which edition / page an upload is
        self.page_detectors = []
        for ref in refs:
            k = DETECT_SIZE / max(ref.shape[:2])
            self.page_detectors.append(
                Aligner(cv2.resize(ref, None, fx=k, fy=k, interpolation=cv2.INTER_AREA), n_features=2000))
        self.detector = self.page_detectors[0]
        sec_path = os.path.join(folder, "sections.json")
        if os.path.exists(sec_path):
            with open(sec_path, encoding="utf-8") as fh:
                self.sections = json.load(fh)["sections"]
        else:                              # no section list: one section per page
            self.sections = [{"id": str(p + 1), "page": p, "title": f"Page {p + 1}", "subtitle": "",
                              "fields": [{"name": n, "label": label_for(n), "label_en": label_for(n)}
                                         for n in dict.fromkeys(f["name"] for f in self.tpl["fields"]
                                                                if f["page"] == p and not f["name"].endswith("_attached"))]}
                             for p in range(self.n_pages)]
        self.groups = OrderedDict()        # field name -> its template entries, in form order
        for f in self.tpl["fields"]:
            self.groups.setdefault(f["name"], []).append(f)

    def read(self, aligned, formats, vocab=None, lookups=None, plausible=True):
        """Read every field from the aligned pages (None for pages not supplied).
        lookups: official name lists (app/lookups.py); a field that has one gets the
        listed name the handwriting most likely is. Returns data, review, readings and
        matches {field: {"read_as": raw text, "match": "sure" | "guess" | "none"}}."""
        vocab = vocab or {}
        matches, pending = {}, {}
        inks = [None if aligned[p] is None else self.segmenters[p].ink(aligned[p])
                for p in range(self.n_pages)]
        comps = [None if ink is None else self.segmenters[p].components(ink) for p, ink in enumerate(inks)]

        def ticked(e):
            return PageSegmenter.tick_ratio(inks[e["page"]], e["cells"][0]) > TICK_RATIO
        data, review, readings = OrderedDict(), [], {}
        for name, entries in self.groups.items():
            kind = entries[0]["type"]
            if kind == "image":          # signature / stamp: shown as a picture only
                continue
            if aligned[entries[0]["page"]] is None:
                data[name] = None
                continue
            if kind == "check":
                on = [e["value"] for e in entries if ticked(e)]
                data[name] = ",".join(on) if on else None
                if len(on) > 1:
                    review.append(name)
            elif kind == "flag":
                data[name] = ticked(entries[0])
            else:
                parts, low, field_probs = {}, False, []
                for e in entries:
                    masks = self.segmenters[e["page"]].cell_masks(comps[e["page"]], e["cells"])
                    full = [("", 100.0, None) if m is None else classify_mask(m, e["type"]) for m in masks]
                    field_probs += [c[2] for c in full if c[0]]
                    fmt = formats.get(name)
                    cells = decode_alnum(full, fmt) if (e["type"] == "alnum" or fmt) else [c[:2] for c in full]
                    if plausible and e["type"] in DATE_LIMITS:
                        cells = plausible_number(full, cells, e["type"])
                    readings.setdefault(name, []).append(list(zip(masks, cells)))
                    text = re.sub(r"\s+", " ", "".join(c if c else " " for c, _ in cells)).strip()
                    # a field can span two rows of boxes (e.g. employer name)
                    parts[e["type"]] = (parts.get(e["type"], "") + " " + text).strip()
                    low |= any(c and conf < LOW_CONFIDENCE for c, conf in cells)
                if kind.startswith("date_"):
                    d, m, y = (parts.get(k, "").replace(" ", "") for k in ("date_d", "date_m", "date_y"))
                    data[name] = f"{d}/{m}/{y}" if (d or m or y) else None
                    ok = (len(d) == 2 and len(m) == 2 and len(y) == 4 and d.isdigit() and m.isdigit()
                          and 1 <= int(d) <= 31 and 1 <= int(m) <= 12)
                    if (d or m or y) and not ok:
                        low = True  # incomplete or impossible date
                else:
                    data[name] = parts.get(kind) or None
                    cat = vocab_category(name)
                    list_name = lookups.for_field(name) if lookups else None
                    if list_name:                 # matched below, a whole group at a time
                        pending[name] = (data[name], field_probs)
                    elif cat and data[name] and cat in vocab:
                        fixed = snap_to_vocab(field_probs, data[name], vocab[cat], VOCAB_MARGIN[cat])
                        if fixed:
                            data[name] = fixed
                if low:
                    review.append(name)
        # Place names from the official lists: region first, then the district among that
        # region's districts, then the ward among that district's wards.
        if pending:
            for name, (value, how) in lookups.match_fields(pending).items():
                raw_text = pending[name][0]
                data[name] = value
                matches[name] = {"read_as": raw_text,
                                 "match": how if (raw_text or value) else "empty"}
                if (raw_text or value) and how != "sure" and name not in review:
                    review.append(name)
                elif how == "sure" and name in review:
                    review.remove(name)       # clearly one of the listed names
        return data, review, readings, matches

    def grid_fit(self, aligned_page, p):
        """How well this edition's box map lands on a straightened page: how much darker the
        printed box lines are than the inside of the boxes (about 10+ when it fits, under 7 when
        it is the wrong page or badly lined up). Does not depend on the paper colour."""
        cells = [c for f in self.tpl["fields"] if f["page"] == p and f["type"] != "image" for c in f["cells"]]
        g = cv2.cvtColor(aligned_page, cv2.COLOR_BGR2GRAY).astype(np.float32)
        dark = cv2.dilate(g, np.ones((15, 15), np.uint8)) - g
        edge = cv2.dilate(dark, np.ones((5, 5), np.uint8))        # 2 px of tolerance
        H, W = g.shape
        sc = []
        for x, y, w, h in cells[::2]:
            x0, y0, x1, y1 = x - 2, y - 2, x + w + 2, y + h + 2
            if x0 < 0 or y0 < 0 or x1 >= W or y1 >= H or w < 8 or h < 8:
                continue
            border = np.concatenate([edge[y0, x0:x1], edge[y1, x0:x1], edge[y0:y1, x0], edge[y0:y1, x1]])
            sc.append(float(np.median(border) - np.median(dark[y + 3:y + h - 3, x + 3:x + w - 3])))
        return float(np.mean(sc)) if sc else 0.0

    def sift_candidate(self, img, p):
        """(points that agree, box-grid fit, homography) for this page with the second matching
        method; the fit is 0 when nothing matched."""
        H, n = self.aligners[p].sift_match(img)
        if H is None:
            return n, 0.0, None
        h, w = self.aligners[p].ref_shape
        warped = cv2.warpPerspective(img, H, (w, h), flags=cv2.INTER_LINEAR, borderValue=(255, 255, 255))
        return n, self.grid_fit(warped, p), H

    def align_page(self, img, p):
        """Straighten a photo of page p: the normal matching, else the second method (accepted
        with fewer agreeing points when the box map clearly fits)."""
        warped, info = self.aligners[p].align(img)
        if info["aligned"] and info.get("inliers", 0) >= 60:
            return warped, info
        n, fit, H = self.sift_candidate(img, p)
        if H is not None and (n >= MIN_SIFT_INLIERS or (n >= MIN_WEAK_SIFT and fit >= GOOD_GRID_FIT)):
            h, w = self.aligners[p].ref_shape
            warped = cv2.warpPerspective(img, H, (w, h), flags=cv2.INTER_LINEAR, borderValue=(255, 255, 255))
            return warped, {"aligned": True, "inliers": max(n, 60), "sift_points": n,
                            "grid_fit": round(fit, 1), "method": "sift"}
        return warped, info

    def endorsements(self, aligned_page, p, images=True):
        """Signatures and stamps on a straightened page (see app/endorsements.py); None when
        this edition / page has none listed in app/endorsement_settings.json."""
        try:
            return endorsements.check(aligned_page, self.aligners[p].ref_gray, self.id, images=images,
                                      other_cells=endorsements.other_cells(self.tpl, p))
        except Exception:                  # never let this check stop a reading
            return None

    def count_written(self, aligned_page, p):
        """How much of page p has been filled in: (boxes with writing, boxes in total,
        tick boxes ticked). Used to warn about an empty form before reading it."""
        seg = self.segmenters[p]
        ink = seg.ink(aligned_page)
        comps = seg.components(ink)
        written = total = ticks = 0
        for f in self.tpl["fields"]:
            if f["page"] != p or f["type"] == "image":
                continue
            if f["type"] in ("check", "flag"):
                ticks += PageSegmenter.tick_ratio(ink, f["cells"][0]) > TICK_RATIO
                continue
            masks = seg.cell_masks(comps, f["cells"])
            total += len(masks)
            written += sum(m is not None for m in masks)
        return written, total, ticks

    def field_strip(self, aligned, name, pad=6, height=44, max_boxes=None, pad_left=None):
        """Image of the part of the page holding a field (all its boxes).
        max_boxes: show only the first N boxes of a one-row field (the written part).
        pad_left: extra margin on the left (e.g. to include a tick-box's printed label)."""
        entries = self.groups[name]
        page = entries[0]["page"]
        if aligned[page] is None:
            return np.full((height, height), 255, np.uint8)
        if max_boxes and len(entries) == 1:
            boxes = entries[0]["cells"][:max_boxes]
        else:
            boxes = [b for e in entries if e["page"] == page for b in e["cells"]]
        x0 = min(b[0] for b in boxes) - (pad if pad_left is None else pad_left)
        y0 = min(b[1] for b in boxes) - pad
        x1 = max(b[0] + b[2] for b in boxes) + pad
        y1 = max(b[1] + b[3] for b in boxes) + pad
        crop = aligned[page][max(0, y0):y1, max(0, x0):x1]
        s = height / crop.shape[0]
        return cv2.resize(crop, (max(1, int(crop.shape[1] * s)), height), interpolation=cv2.INTER_AREA)

    @staticmethod
    def written_extent(readings, name, spare=1, minimum=6):
        """How many boxes of a one-row field to show: up to the last written box + spare."""
        rows = readings.get(name)
        if not rows or len(rows) != 1:
            return None
        last = max((k for k, (_, (ch, _)) in enumerate(rows[0]) if ch), default=-1)
        return max(minimum, last + 1 + spare)


class FormExtractor:
    """Reads any known edition of the form from a PDF or photo(s)."""

    def __init__(self, forms_dir=FORMS_DIR, lookups=None):
        self.lookups = lookups
        self.layouts = [FormLayout(os.path.join(forms_dir, d)) for d in sorted(os.listdir(forms_dir))
                        if os.path.exists(os.path.join(forms_dir, d, "template.json"))]
        if not self.layouts:
            raise FileNotFoundError(f"No form layouts found in {forms_dir}")
        self.by_id = {l.id: l for l in self.layouts}
        self.formats = load_formats(os.path.join(os.path.dirname(__file__), "field_formats.json"))
        self.vocab = load_vocab()

    # ------------------------------------------------------------------ core
    def run(self, files, form_id=None, plausible=True):
        """files: bytes of one PDF, or a list of file bytes (PDFs and/or images, in page order).
        Returns (result dict, layout, aligned pages, per-field readings)."""
        t0 = time.time()
        if isinstance(files, (bytes, bytearray)):
            files = [files]
        pages = [pg for f in files for pg in load_pages(f)]
        if not pages:
            raise ValueError("No pages found in the upload.")

        # Which edition is it? Recognise page 1 (see identify).
        if form_id:
            layout = self.by_id[form_id]
        else:
            _, _, li, _, _, _ = self.identify(pages[0], [(i, 0) for i in range(len(self.layouts))])
            layout = self.layouts[li]
            # Editions can share page 1 and differ on page 2 (1.4 has two printings of page 2):
            # then page 2 decides.
            same = [i for i, l in enumerate(self.layouts) if l.page_ids[0] == layout.page_ids[0] and l.n_pages > 1]
            if len(same) > 1 and len(pages) > 1:
                ok2, _, li2, _, _, _ = self.identify(pages[1], [(i, 1) for i in same])
                if ok2:
                    layout = self.layouts[li2]
        first, info0 = layout.align_page(pages[0], 0)
        if not info0["aligned"] or info0.get("inliers", 0) < 60:
            raise ValueError("This does not look like a known edition of Form 1A (could not line it up). "
                             "Check the photo shows the whole page, in focus and not too dark.")

        aligned, align_info = [first], [info0]
        for p in range(1, layout.n_pages):
            if p < len(pages):
                img, info = layout.align_page(pages[p], p)
                aligned.append(img if info["aligned"] else None)
                align_info.append(info)
            else:
                aligned.append(None)
                align_info.append({"aligned": False, "reason": "page not supplied"})

        data, review, readings, matches = layout.read(aligned, self.formats, self.vocab,
                                                       self.lookups if plausible else None, plausible)
        warnings = []
        for i, a in enumerate(align_info):
            if a.get("reason") == "page not supplied":
                warnings.append(f"Page {i + 1} of this form was not uploaded; its fields are empty.")
            elif not a["aligned"]:
                warnings.append(f"Page {i + 1} could not be lined up ({a.get('reason')}); its fields are empty.")
        if len(pages) > layout.n_pages:
            warnings.append(f"Only the first {layout.n_pages} page(s) were read; this form has "
                            f"{layout.n_pages}.")
        missing = [i + 1 for i, a in enumerate(align_info) if a.get("reason") == "page not supplied"]
        # signatures and stamps on page 2 (enrolment only; saved with the record)
        endorse = None
        if plausible and layout.n_pages > 1 and len(aligned) > 1 and aligned[1] is not None:
            endorse = layout.endorsements(aligned[1], 1)
        result = {"form": layout.id, "form_title": layout.title, "data": data, "pages_missing": missing,
                  "endorsements": endorse,
                  "lookup_matches": matches,
                  "needs_review": review, "warnings": warnings,
                  "processing_seconds": round(time.time() - t0, 2)}
        return result, layout, aligned, readings

    def identify(self, img, candidates=None):
        """Which edition and page is this photo? candidates: [(layout index, page index)] to
        consider (all pages of all editions by default). Tries, in order:
          1. quick: a small copy matched against small copies of each page (ORB);
          2. full size: once per distinct printed page (small or blurry photos);
          3. SIFT on flattened images, once per distinct printed page, also using the other
             looks of each page (faded scans, grey photocopies, pages photographed sideways).
        Returns (recognised, score, layout index, page index, how, runner-up score)."""
        if candidates is None:
            candidates = [(li, p) for li, lay in enumerate(self.layouts) for p in range(lay.n_pages)]
        k = DETECT_SIZE / max(img.shape[:2])
        small = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        quick = sorted(((self.layouts[li].page_detectors[p].align(small)[1].get("inliers", 0), -li, -p)
                        for li, p in candidates), reverse=True)
        runner = quick[1][0] if len(quick) > 1 else 0
        if quick[0][0] >= MIN_DETECT_INLIERS:
            return True, quick[0][0], -quick[0][1], -quick[0][2], "quick", runner
        seen, distinct = set(), []
        for li, p in candidates:                   # one try per printed page (editions share pages)
            pid = self.layouts[li].page_ids[p]
            if pid not in seen:
                seen.add(pid)
                distinct.append((li, p))
        full = sorted(((self.layouts[li].aligners[p].align(img)[1].get("inliers", 0), -li, -p)
                       for li, p in distinct), reverse=True)
        if full[0][0] >= MIN_FULL_INLIERS:
            return True, full[0][0], -full[0][1], -full[0][2], "full size", full[1][0] if len(full) > 1 else 0
        # The printings of one page share most of their text, so the number of agreeing points can
        # point to the wrong one on a poor photo: unless one page is far ahead, the page whose box
        # map lands best on the printed boxes is taken (grid_fit).
        cand = []
        for li, p in distinct:
            n, fit, H = self.layouts[li].sift_candidate(img, p)
            cand.append((n, fit, li, p))
        cand.sort(key=lambda c: (c[0], -c[2], -c[3]), reverse=True)
        top = cand[0]
        if len(cand) > 1 and top[0] < 4 * max(cand[1][0], 1):
            close = [c for c in cand if c[0] >= MIN_WEAK_SIFT]
            if close:
                top = max(close, key=lambda c: (c[1], c[0]))
        n, fit, li, p = top
        second = max((c[0] for c in cand if c is not top), default=0)
        if n >= MIN_SIFT_INLIERS or (n >= MIN_WEAK_SIFT and fit >= GOOD_GRID_FIT):
            return True, n, li, p, "sift", second
        return False, quick[0][0], -quick[0][1], -quick[0][2], "none", runner

    def extract(self, files, form_id=None):
        return self.run(files, form_id)[0]

    # ------------------------------------------------------------------ quick check of one photo
    def inspect(self, data):
        """Look at one uploaded photo (or the first page of a PDF) before reading it:
        which edition and which page it is, and whether anything is written on it.
        Never rejects anything: the caller shows the findings for a person to confirm."""
        t0 = time.time()
        pages = load_pages(data)
        if not pages:
            raise ValueError("No pages found in the upload.")
        img = pages[0]
        recognised, best, li, p, how, runner = self.identify(img)
        lay = self.layouts[li]
        same_page = [l.id for l in self.layouts if p < l.n_pages and l.page_ids[p] == lay.page_ids[p]]
        out = {"recognised": recognised, "form": lay.id, "form_title": lay.title,
               "compatible_forms": same_page,      # editions this page belongs to
               "page_count": lay.n_pages, "page": p + 1, "match": int(best), "matched_by": how,
               "runner_up": int(runner),
               "file_pages": len(pages), "blank": None, "boxes_written": None,
               "boxes_total": None, "ticks": None}
        if out["recognised"]:
            aligned, info = lay.align_page(img, p)
            if info["aligned"]:
                written, total, ticks = lay.count_written(aligned, p)
                out.update(boxes_written=written, boxes_total=total, ticks=ticks,
                           blank=written < max(4, BLANK_SHARE * total) and ticks == 0)
                # page 2: signatures and stamps (items 59, 60, 68, 70, 71; app/endorsements.py)
                if p == 1 and not out["blank"]:
                    out["endorsements"] = lay.endorsements(aligned, p)
            else:
                out["recognised"] = False
        out["processing_seconds"] = round(time.time() - t0, 2)
        return out

    # ------------------------------------------------------------------ images for review
    @staticmethod
    def filled_cells(readings, name):
        """(character image, predicted char) for every non-empty box of a text/date field,
        in order. Images are dark ink on white, as saved for retraining."""
        out = []
        for entry_readings in readings.get(name, []):
            for mask, (ch, _) in entry_readings:
                if ch and mask is not None:
                    out.append((cv2.copyMakeBorder(255 - mask, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=255), ch))
        return out

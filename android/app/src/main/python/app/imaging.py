"""Image helpers: PDF rendering, grid/ink masks and page alignment."""
import cv2
import numpy as np


def pdf_to_images(pdf_bytes, dpi=200):
    """Render every page of a PDF to a BGR numpy image."""
    import pypdfium2 as pdfium          # only needed for PDFs (not available on the phone)
    doc = pdfium.PdfDocument(pdf_bytes)
    pages = []
    try:
        for i in range(len(doc)):
            # Straight to numpy (no Pillow needed). pdfium renders in BGR order,
            # which is what OpenCV expects.
            bm = doc[i].render(scale=dpi / 72)
            img = np.array(bm.to_numpy(), copy=True)
            mode = str(getattr(bm, "mode", "BGR")).upper()
            if img.ndim == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            elif img.shape[2] == 4:
                img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR if mode.startswith("RGB") else cv2.COLOR_BGRA2BGR)
            elif mode.startswith("RGB"):
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            pages.append(img)
    finally:
        doc.close()
    return pages


IMAGE_TYPES = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")


def load_pages(data, dpi=200):
    """PDF bytes -> one image per page; image bytes (JPG, PNG, ...) -> [that image]."""
    if data[:4] == b"%PDF":
        return pdf_to_images(data, dpi)
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("This file is not a PDF or an image the app can read (use PDF, JPG or PNG).")
    # Very large phone photos are shrunk: 2500 px on the long side is plenty.
    s = 2500 / max(img.shape[:2])
    if s < 1:
        img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    return [img]


def grid_mask(img_bgr, min_len=25):
    """Long horizontal/vertical dark lines (the printed boxes)."""
    g = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    sat = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)[:, :, 1]
    dark = ((g < 170) & (sat < 80)).astype(np.uint8) * 255
    h = cv2.morphologyEx(dark, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (min_len, 1)))
    v = cv2.morphologyEx(dark, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, min_len)))
    return h | v


def remove_color_ink(img_bgr):
    """Paint coloured (e.g. blue pen) pixels white. Used to make a blank reference."""
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    ink = (hsv[:, :, 1] > 80) & (hsv[:, :, 2] < 235)
    ink = cv2.dilate(ink.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    out = img_bgr.copy()
    out[ink] = 255
    return out


def similarity_lsq(src, dst):
    """Least-squares rotation + uniform scale + shift mapping src points onto dst."""
    a, b = src.reshape(-1, 2).astype(np.float64), dst.reshape(-1, 2).astype(np.float64)
    ma, mb = a.mean(0), b.mean(0)
    a0, b0 = a - ma, b - mb
    den = (a0 ** 2).sum()
    c = (a0 * b0).sum() / den                                   # s*cos
    s = (a0[:, 0] * b0[:, 1] - a0[:, 1] * b0[:, 0]).sum() / den  # s*sin
    R = np.array([[c, -s], [s, c]])
    t = mb - R @ ma
    return np.hstack([R, t[:, None]]).astype(np.float64)


# ---------------------------------------------------------------- second matching method (SIFT)
# Used when the normal (ORB) matching fails: faded scans, grey photocopies, photos turned
# sideways or taken at an angle. Both images are first "flattened": divided by the paper around
# each point, so the paper colour (green, white, grey) and uneven light disappear and only the
# printing and writing remain. SIFT then finds the same printed words on both.
SIFT_SIZE = 1600          # long side (px) of the flattened images
MIN_SIFT_INLIERS = 60     # points that must agree before a page counts as recognised this way
_SIFT = None
_FLANN = None
_photo_cache = {"key": None, "val": None}


def _sift():
    global _SIFT, _FLANN
    if _SIFT is None:
        _SIFT = cv2.SIFT_create(6000)
        _FLANN = cv2.FlannBasedMatcher({"algorithm": 1, "trees": 4}, {"checks": 48})
    return _SIFT, _FLANN


def flatten(img, long_side=SIFT_SIZE):
    """Grey image with the paper colour and the light evened out (see above). Returns (image, scale)."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    k = long_side / max(g.shape[:2])
    g = cv2.resize(g, None, fx=k, fy=k, interpolation=cv2.INTER_AREA if k < 1 else cv2.INTER_LINEAR)
    paper = cv2.GaussianBlur(cv2.dilate(g, np.ones((21, 21), np.uint8)), (0, 0), 6).astype(np.float32)
    flat = np.clip(g.astype(np.float32) / np.maximum(paper, 1) * 255, 0, 255).astype(np.uint8)
    # what is much darker than the page's paper (a table or floor around a photographed page,
    # deep shadow) is not part of the form: make it plain white so it gives no points
    bright = float(np.percentile(paper, 90))
    background = cv2.erode((paper < 0.6 * bright).astype(np.uint8), np.ones((9, 9), np.uint8))
    flat[cv2.dilate(background, np.ones((31, 31), np.uint8)) > 0] = 255
    return flat, k


def _sift_features(img):
    """SIFT points of a (flattened) image, in the image's own full-size pixel coordinates."""
    sift, _ = _sift()
    flat, k = flatten(img)
    kp, des = sift.detectAndCompute(flat, None)
    pts = np.float32([p.pt for p in kp]) / k if kp else np.zeros((0, 2), np.float32)
    return pts, des


def _photo_features(img):
    """Same as _sift_features, remembered for the last photo (it is compared with many pages)."""
    key = (id(img), img.shape, int(img[::97, ::89].sum()))
    if _photo_cache["key"] != key:
        _photo_cache.update(key=key, val=_sift_features(img))
    return _photo_cache["val"]


class Aligner:
    """Warps a scanned page onto the reference page using ORB feature matching.

    Handles the usual scanner problems: small rotation, shift, scale and
    different resolution. Printed text on the form gives plenty of keypoints.
    """

    def __init__(self, reference_bgr, n_features=5000, variants=()):
        self.ref_shape = reference_bgr.shape[:2]
        # Other looks of the same page (a faded scan, a grey photocopy...), already lined up onto
        # the reference, so a match with any of them gives positions on the reference.
        self.variants = list(variants)
        self._sift_refs = None
        self.orb = cv2.ORB_create(n_features)
        self.ref_gray = cv2.cvtColor(reference_bgr, cv2.COLOR_BGR2GRAY)
        self.kp, self.des = self.orb.detectAndCompute(self.ref_gray, None)
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING)

    def align(self, img_bgr, robust=False):
        """Warp a scan or photo onto the reference page (see _align_orb). With robust=True, when
        the normal matching fails, the second method is tried (sift_match): faded scans,
        photocopies, pages photographed sideways."""
        warped, info = self._align_orb(img_bgr)
        if not robust or (info["aligned"] and info.get("inliers", 0) >= 60):
            return warped, info
        H, n = self.sift_match(img_bgr)
        if H is None or n < MIN_SIFT_INLIERS:
            return warped, info
        h, w = self.ref_shape
        warped = cv2.warpPerspective(img_bgr, H, (w, h), flags=cv2.INTER_LINEAR, borderValue=(255, 255, 255))
        return warped, {"aligned": True, "inliers": n, "method": "sift"}

    def _sift_reference(self):
        if self._sift_refs is None:
            self._sift_refs = [_sift_features(self.ref_gray)] + [_sift_features(v) for v in self.variants]
        return self._sift_refs

    def sift_match(self, img_bgr):
        """(homography from the photo to the reference, number of agreeing points), with the best
        of the reference and its other looks; (None, 0) when nothing fits."""
        _, flann = _sift()
        pts, des = _photo_features(img_bgr)
        if des is None or len(pts) < 50:
            return None, 0
        best = (None, 0)
        for rpts, rdes in self._sift_reference():
            if rdes is None or len(rpts) < 50:
                continue
            pairs = flann.knnMatch(des, rdes, k=2)
            good = [m for m, n in (p for p in pairs if len(p) == 2) if m.distance < 0.75 * n.distance]
            if len(good) < 20:
                continue
            src = pts[[m.queryIdx for m in good]].reshape(-1, 1, 2)
            dst = rpts[[m.trainIdx for m in good]].reshape(-1, 1, 2)
            cv2.setRNGSeed(12345)
            H, inl = cv2.findHomography(src, dst, cv2.RANSAC, 6.0)
            if H is None:
                continue
            n = int(inl.sum())
            if n >= 30:
                H2, _ = cv2.findHomography(src[inl.ravel() > 0], dst[inl.ravel() > 0], 0)
                H = H2 if H2 is not None else H
            if n > best[1] and self._sane(H, img_bgr.shape[:2], scale_free=True):
                best = (H, n)
        return best

    def _align_orb(self, img_bgr):
        """Warp a scan or photo onto the reference page.

        Scans: rotation + scale + shift (stable). Photos: full perspective
        (homography), used only when it fits clearly better, e.g. a phone held
        at an angle. The returned info has "inliers" = how well it matched,
        which is also used to recognise which form edition a page belongs to.
        """
        h, w = self.ref_shape
        # Scale so the long side matches the reference, keeping the photo's shape.
        s = max(h, w) / max(img_bgr.shape[:2])
        img = img_bgr if abs(s - 1) < 1e-3 else cv2.resize(
            img_bgr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        kp, des = self.orb.detectAndCompute(gray, None)
        fail = lambda why: (cv2.resize(img, (w, h)), {"aligned": False, "reason": why, "inliers": 0})
        if des is None or len(kp) < 50:
            return fail("too few features")
        pairs = self.matcher.knnMatch(des, self.des, k=2)
        good = [m for m, n in (p for p in pairs if len(p) == 2) if m.distance < 0.75 * n.distance]
        if len(good) < 40:
            return fail(f"only {len(good)} matches")
        src = np.float32([kp[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst = np.float32([self.kp[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        cv2.setRNGSeed(12345)          # same result every time for the same file
        M, inl_a = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=4.0)
        n_a = int(inl_a.sum()) if inl_a is not None else 0
        if n_a >= 30:                  # final exact fit on all agreeing points
            M = similarity_lsq(src[inl_a.ravel() > 0], dst[inl_a.ravel() > 0])
        cv2.setRNGSeed(12345)
        H, inl_h = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
        n_h = int(inl_h.sum()) if inl_h is not None else 0
        if n_h >= 30:
            H2, _ = cv2.findHomography(src[inl_h.ravel() > 0], dst[inl_h.ravel() > 0], 0)
            H = H2 if H2 is not None else H
        if H is not None and not self._sane(H, img.shape[:2]):
            n_h = 0
        if max(n_a, n_h) < 30:
            return fail("no consistent transform")
        if n_h > 1.1 * n_a:            # perspective clearly fits better: a photo
            warped = cv2.warpPerspective(img, H, (w, h), flags=cv2.INTER_LINEAR, borderValue=(255, 255, 255))
            # Second pass: the page is now nearly lined up, so matching again finds
            # many more points everywhere on the page and gives a precise fit.
            H2, n2 = self._refine_h(warped)
            if H2 is not None and n2 > n_h:
                H, n_h = H2 @ H, n2
                warped = cv2.warpPerspective(img, H, (w, h), flags=cv2.INTER_LINEAR,
                                             borderValue=(255, 255, 255))
            return warped, {"aligned": True, "inliers": n_h, "method": "perspective"}
        warped = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR, borderValue=(255, 255, 255))
        angle = float(np.degrees(np.arctan2(M[1, 0], M[0, 0])))
        return warped, {"aligned": True, "inliers": n_a, "method": "rotate+scale",
                        "rotation_deg": round(angle, 2)}

    def _refine_h(self, warped):
        """Homography from an already nearly aligned page to the reference, using
        only matches that are close to where they should be."""
        kp, des = self.orb.detectAndCompute(cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY), None)
        if des is None or len(kp) < 50:
            return None, 0
        pairs = self.matcher.knnMatch(des, self.des, k=2)
        good = [m for m, n in (p for p in pairs if len(p) == 2) if m.distance < 0.8 * n.distance]
        good = [m for m in good if np.hypot(*(np.subtract(kp[m.queryIdx].pt, self.kp[m.trainIdx].pt))) < 40]
        if len(good) < 40:
            return None, 0
        src = np.float32([kp[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst = np.float32([self.kp[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        cv2.setRNGSeed(12345)
        H, inl = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
        if H is None or inl.sum() < 30:
            return None, 0
        H2, _ = cv2.findHomography(src[inl.ravel() > 0], dst[inl.ravel() > 0], 0)
        return (H2 if H2 is not None else H), int(inl.sum())

    def _sane(self, H, shape, scale_free=False):
        """Reject wild perspective fits (page folded over itself, huge zoom). scale_free: the
        photo is at its own size (its page may fill only part of it), so only the shape of the
        page outline is checked, not its area."""
        h, w = shape
        if scale_free:
            rh, rw = self.ref_shape
            Hi = np.linalg.inv(H)                 # where the reference page lies on the photo
            c = cv2.perspectiveTransform(np.float32([[0, 0], [rw, 0], [rw, rh], [0, rh]]).reshape(-1, 1, 2), Hi)
            c = c.reshape(-1, 2)
            area = cv2.contourArea(c)
            return cv2.isContourConvex(c.astype(np.float32)) and 0.15 < area / (w * h) < 1.6
        c = cv2.perspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2), H)
        c = c.reshape(-1, 2)
        area = cv2.contourArea(c)
        rh, rw = self.ref_shape
        return cv2.isContourConvex(c.astype(np.float32)) and 0.3 < area / (rw * rh) < 3.0

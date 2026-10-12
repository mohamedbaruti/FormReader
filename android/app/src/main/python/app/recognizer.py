"""Handwritten character recogniser (digits 0-9 and capital letters A-Z).

Two small neural networks, both stored as plain numpy arrays and run with
numpy + OpenCV only (no PyTorch, no GPU):
  app/model/char_cnn.npz  convolutional network on the character image (main model)
  app/model/char_mlp.npz  network on stroke-direction (HOG) features
When both are present their probabilities are averaged (CNN_WEIGHT), which is
more accurate than either alone.
"""
import os

import cv2
import numpy as np

CLASSES = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
MODEL_PATH = os.path.join(os.path.dirname(__file__), "model", "char_mlp.npz")
CNN_PATH = os.path.join(os.path.dirname(__file__), "model", "char_cnn.npz")
CNN_WEIGHT = 0.6   # share of the CNN in the average (1.0 = CNN only, 0.0 = MLP only)

_HOG = cv2.HOGDescriptor((28, 28), (14, 14), (7, 7), (7, 7), 9)


def normalize_char(img):
    """Any character image (white ink on black, uint8) -> centred 28x28 float image.

    Used identically for training data and for scanned cells, so both look alike:
    crop to the ink, scale the longer side to 20 px, centre by centre of mass.
    """
    ys, xs = np.nonzero(img > 40)
    if len(xs) == 0:
        return np.zeros((28, 28), np.float32)
    ch = img[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = ch.shape
    s = 20.0 / max(h, w)
    nh, nw = max(1, int(round(h * s))), max(1, int(round(w * s)))
    ch = cv2.resize(ch, (nw, nh), interpolation=cv2.INTER_AREA)
    out = np.zeros((28, 28), np.float32)
    y0, x0 = (28 - nh) // 2, (28 - nw) // 2
    out[y0:y0 + nh, x0:x0 + nw] = ch
    m = cv2.moments(out)
    if m["m00"] > 0:
        dx, dy = 14 - m["m10"] / m["m00"], 14 - m["m01"] / m["m00"]
        out = cv2.warpAffine(out, np.float32([[1, 0, dx], [0, 1, dy]]), (28, 28))
    out = cv2.GaussianBlur(out, (3, 3), 0.8)
    mx = out.max()
    return out / mx if mx > 0 else out


def features(norm28):
    """HOG (stroke directions) + a 14x14 thumbnail of the character."""
    u8 = (np.clip(norm28, 0, 1) * 255).astype(np.uint8)
    hog = _HOG.compute(u8).ravel()
    thumb = cv2.resize(norm28, (14, 14), interpolation=cv2.INTER_AREA).ravel()
    return np.concatenate([hog, thumb]).astype(np.float32)


class CharClassifier:
    def __init__(self, path=MODEL_PATH, cnn_path=CNN_PATH, cnn_weight=None):
        self.layers = None
        if path and os.path.exists(path):
            m = np.load(path)
            self.mean, self.std = m["mean"], m["std"]
            self.layers = [(m[f"W{i}"], m[f"b{i}"]) for i in range(int(m["n_layers"]))]
        self.cnn = None
        if cnn_path and os.path.exists(cnn_path):
            from . import cnn
            self._cnn_mod = cnn
            self.cnn = cnn.load(cnn_path)
        if self.layers is None and self.cnn is None:
            raise FileNotFoundError("No character model found in app/model/")
        w = CNN_WEIGHT if cnn_weight is None else cnn_weight
        self.w_cnn = 0.0 if self.cnn is None else (1.0 if self.layers is None else w)

    def predict_proba(self, feats):
        x = (np.atleast_2d(feats) - self.mean) / self.std
        for i, (W, b) in enumerate(self.layers):
            x = x @ W + b
            if i < len(self.layers) - 1:
                x = np.maximum(x, 0)  # ReLU
        x -= x.max(axis=1, keepdims=True)
        e = np.exp(x)
        return e / e.sum(axis=1, keepdims=True)

    def probs(self, ink_mask):
        """Probability of each of the 36 characters for one pen mask."""
        norm = normalize_char(ink_mask)
        p = 0.0
        if self.w_cnn < 1.0:
            p = (1 - self.w_cnn) * self.predict_proba(features(norm))[0]
        if self.w_cnn > 0.0:
            p = p + self.w_cnn * self._cnn_mod.predict_proba(self.cnn, norm[None])[0]
        return p

    def classify(self, ink_mask, allowed=CLASSES):
        """Return (character, confidence 0-100) restricted to the allowed characters."""
        return self.pick(self.probs(ink_mask), allowed)

    @staticmethod
    def pick(p, allowed=CLASSES):
        """Best character among `allowed` given the 36 probabilities."""
        idx = [CLASSES.index(c) for c in allowed]
        sub = p[idx]
        best = int(np.argmax(sub))
        conf = sub[best] / max(sub.sum(), 1e-9)  # confidence among allowed characters
        return allowed[best], float(round(conf * 100, 1))

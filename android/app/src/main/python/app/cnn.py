"""A small convolutional neural network written in plain numpy.

Architecture (input: one 28x28 character image, values 0..1):
    conv 3x3, 32 filters, ReLU -> max-pool 2x2        (14x14x32)
    conv 3x3, 64 filters, ReLU -> max-pool 2x2        (7x7x64)
    fully connected 3136 -> 256, ReLU (dropout while training)
    fully connected 256 -> 36 classes (0-9, A-Z), softmax

Only numpy is needed, both to run it (app) and to train it (tools/train_cnn.py),
so it works on any CPU without PyTorch/TensorFlow. Reading a whole form
(~500 characters) takes well under a second.
"""
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view


def he(shape, fan_in, rng):
    return (rng.standard_normal(shape) * np.sqrt(2.0 / fan_in)).astype(np.float32)


def init_params(rng, n_classes=36):
    return {
        "c1w": he((9 * 1, 32), 9, rng), "c1b": np.zeros(32, np.float32),
        "c2w": he((9 * 32, 64), 9 * 32, rng), "c2b": np.zeros(64, np.float32),
        "f1w": he((7 * 7 * 64, 256), 7 * 7 * 64, rng), "f1b": np.zeros(256, np.float32),
        "f2w": he((256, n_classes), 256, rng), "f2b": np.zeros(n_classes, np.float32),
    }


# ---------------------------------------------------------------- layers (NHWC)
def im2col(x):
    """x (N,H,W,C) -> columns (N*H*W, 9*C) for a 3x3 'same' convolution."""
    n, h, w, c = x.shape
    xp = np.pad(x, ((0, 0), (1, 1), (1, 1), (0, 0)))
    win = sliding_window_view(xp, (3, 3), axis=(1, 2))          # N,H,W,C,3,3
    return np.ascontiguousarray(win.transpose(0, 1, 2, 4, 5, 3)).reshape(n * h * w, 9 * c)


def col2im(dcols, shape):
    """Inverse of im2col for gradients: (N*H*W, 9*C) -> (N,H,W,C)."""
    n, h, w, c = shape
    d = dcols.reshape(n, h, w, 3, 3, c)
    dxp = np.zeros((n, h + 2, w + 2, c), dcols.dtype)
    for i in range(3):
        for j in range(3):
            dxp[:, i:i + h, j:j + w, :] += d[:, :, :, i, j, :]
    return dxp[:, 1:-1, 1:-1, :]


def conv_forward(x, w, b):
    n, h, wd, _ = x.shape
    cols = im2col(x)
    out = (cols @ w + b).reshape(n, h, wd, -1)
    return out, cols


def pool_forward(x):
    n, h, w, c = x.shape
    r = x.reshape(n, h // 2, 2, w // 2, 2, c)
    out = r.max(axis=(2, 4))
    return out, r


def pool_backward(dout, r, out):
    mask = r == out[:, :, None, :, None, :]
    # share the gradient if several inputs tie for the max
    mask = mask / np.maximum(mask.sum(axis=(2, 4), keepdims=True), 1)
    return (mask * dout[:, :, None, :, None, :]).reshape(r.shape[0], r.shape[1] * 2, r.shape[3] * 2, r.shape[5])


# ---------------------------------------------------------------- model
def forward(p, x, train=False, rng=None, drop=0.4):
    """x: (N,28,28) float32. Returns logits and a cache for backward()."""
    x = x[..., None]
    a1, c1 = conv_forward(x, p["c1w"], p["c1b"])
    r1 = np.maximum(a1, 0)
    p1, pr1 = pool_forward(r1)
    a2, c2 = conv_forward(p1, p["c2w"], p["c2b"])
    r2 = np.maximum(a2, 0)
    p2, pr2 = pool_forward(r2)
    flat = p2.reshape(len(x), -1)
    h = np.maximum(flat @ p["f1w"] + p["f1b"], 0)
    dmask = None
    if train and drop > 0:
        dmask = (rng.random(h.shape) >= drop).astype(np.float32) / (1 - drop)
        h = h * dmask
    logits = h @ p["f2w"] + p["f2b"]
    cache = (x, c1, a1, r1, p1, pr1, c2, a2, r2, p2, pr2, flat, h, dmask)
    return logits, cache


def backward(p, cache, dlogits):
    x, c1, a1, r1, p1, pr1, c2, a2, r2, p2, pr2, flat, h, dmask = cache
    g = {}
    g["f2w"] = h.T @ dlogits
    g["f2b"] = dlogits.sum(0)
    dh = dlogits @ p["f2w"].T
    if dmask is not None:
        dh = dh * dmask
    dh = dh * (h > 0)
    g["f1w"] = flat.T @ dh
    g["f1b"] = dh.sum(0)
    dp2 = (dh @ p["f1w"].T).reshape(p2.shape)
    dr2 = pool_backward(dp2, pr2, p2)
    da2 = (dr2 * (a2 > 0)).reshape(-1, a2.shape[-1])
    g["c2w"] = c2.T @ da2
    g["c2b"] = da2.sum(0)
    dp1 = col2im(da2 @ p["c2w"].T, p1.shape)
    dr1 = pool_backward(dp1, pr1, p1)
    da1 = (dr1 * (a1 > 0)).reshape(-1, a1.shape[-1])
    g["c1w"] = c1.T @ da1
    g["c1b"] = da1.sum(0)
    return g


def softmax(z):
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def predict_proba(p, x, batch=256):
    out = []
    for i in range(0, len(x), batch):
        out.append(softmax(forward(p, x[i:i + batch].astype(np.float32))[0]))
    return np.concatenate(out)


def load(path):
    m = np.load(path)
    return {k: m[k] for k in m.files if k != "kind"}


def save(path, p):
    np.savez_compressed(path, kind=np.array("cnn"), **p)

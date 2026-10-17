"""Edge width metric for render-based tests. Pure NumPy, no bpy.

Edge width W = A / L, in pixels:
  A  transition area: pixels whose value lies strictly between `lo` and `hi` (0.1 and 0.9)
  L  boundary length of the 0.5 contour, estimated from the horizontal and vertical 0.5
     crossings: an isotropic curve of length L crosses grid lines (|cos| + |sin|) per unit
     length, 4/pi on average, so L = crossings * pi / 4.
W is the average width of the soft band around every edge: about 1 px for a crisp edge, 2.563
sigma for an edge blurred by a Gaussian of sigma px (the 10..90 % span of the error function).
"""

import math

import numpy as np


def _gray(img):
    a = np.asarray(img, dtype=np.float64)
    if a.ndim == 3:
        a = a[..., 0]  # Mask View is greyscale: R == G == B
    return a


def boundary_length(img, level=0.5):
    a = _gray(img) > level
    cx = np.count_nonzero(a[:, 1:] != a[:, :-1])
    cy = np.count_nonzero(a[1:, :] != a[:-1, :])
    return (cx + cy) * math.pi / 4.0


def transition_area(img, lo=0.1, hi=0.9):
    a = _gray(img)
    return int(np.count_nonzero((a > lo) & (a < hi)))


def edge_width(img, lo=0.1, hi=0.9, level=0.5):
    """W in pixels, or None when the image has no 0.5 boundary to measure."""
    length = boundary_length(img, level)
    if length <= 0:
        return None
    return transition_area(img, lo, hi) / length


def edge_report(img, lo=0.1, hi=0.9):
    """Dict with W, A, L and the covered fraction (mask > 0.5)."""
    a = _gray(img)
    length = boundary_length(a)
    area = transition_area(a, lo, hi)
    return {"W": (area / length) if length > 0 else None, "A": area, "L": length,
            "coverage": float(np.count_nonzero(a > 0.5)) / a.size}


# ------------------------------------------------------------- synthetic images (tests)
def disk(size, radius, center=None, supersample=1):
    """Hard disk (1 inside, 0 outside); supersample > 1 gives an anti-aliased edge."""
    c = (size / 2.0, size / 2.0) if center is None else center
    n = size * supersample
    yy, xx = np.mgrid[0:n, 0:n]
    inside = (((xx + 0.5) / supersample - c[0]) ** 2 + ((yy + 0.5) / supersample - c[1]) ** 2) <= radius ** 2
    img = inside.astype(np.float64)
    if supersample > 1:
        img = img.reshape(size, supersample, size, supersample).mean(axis=(1, 3))
    return img


def gaussian_blur(img, sigma):
    """Separable Gaussian blur (edges extended), so tests need no SciPy."""
    if sigma <= 0:
        return np.array(img, dtype=np.float64)
    r = int(math.ceil(4 * sigma))
    x = np.arange(-r, r + 1, dtype=np.float64)
    k = np.exp(-0.5 * (x / sigma) ** 2)
    k /= k.sum()
    a = np.pad(np.asarray(img, dtype=np.float64), r, mode="edge")
    a = np.apply_along_axis(lambda v: np.convolve(v, k, mode="valid"), 1, a)
    a = np.apply_along_axis(lambda v: np.convolve(v, k, mode="valid"), 0, a)
    return a


GAUSSIAN_W_PER_SIGMA = 2.0 * 1.2815516  # 10..90 % span of a Gaussian-blurred step, in sigmas

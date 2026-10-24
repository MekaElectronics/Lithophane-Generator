r"""
Image loading and tone preparation, on float32 arrays in 0..1.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter, label, zoom

try:
    from PIL import Image, ImageOps

    _HAVE_PIL = True
except ImportError:  # pragma: no cover
    _HAVE_PIL = False

LUMA_709 = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

RESAMPLE_FILTERS = ("lanczos", "bicubic", "bilinear", "nearest")


def srgb_to_linear(x: np.ndarray) -> np.ndarray:
    r"""
    Decode sRGB values to linear light.

    :param x: sRGB values in 0..1
    :return: linear values
    """
    x = np.asarray(x, dtype=np.float32)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4).astype(np.float32)


def linear_to_srgb(x: np.ndarray) -> np.ndarray:
    r"""
    Encode linear light as sRGB.

    :param x: linear values
    :return: sRGB values in 0..1
    """
    x = np.clip(np.asarray(x, dtype=np.float32), 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * x ** (1 / 2.4) - 0.055).astype(np.float32)


def load_rgb(path: str) -> np.ndarray:
    r"""
    Load an image as sRGB with alpha composited over white.

    :param path: image path
    :return: float32 array of shape (H, W, 3)
    """
    arr = _load_array(path)
    if arr.ndim == 2:
        return np.repeat(arr[:, :, None], 3, axis=2)

    rgb = arr[..., :3]
    if arr.shape[2] == 4:
        alpha = arr[..., 3:4]
        lin = srgb_to_linear(rgb) * alpha + (1.0 - alpha)
        rgb = linear_to_srgb(lin)
    return np.clip(rgb, 0.0, 1.0).astype(np.float32)


def load_grayscale(path: str) -> np.ndarray:
    r"""
    Load an image as grayscale with alpha composited over white.

    :param path: image path
    :return: float32 array of shape (H, W)
    """
    arr = _load_array(path)
    if arr.ndim == 2:
        return np.clip(arr, 0.0, 1.0).astype(np.float32)

    rgb = arr[..., :3]
    alpha = arr[..., 3:4] if arr.shape[2] == 4 else None

    lin = srgb_to_linear(rgb)
    if alpha is not None:
        lin = lin * alpha + (1.0 - alpha)
    return linear_to_srgb(lin @ LUMA_709)


def _load_array(path: str) -> np.ndarray:
    r"""
    Decode an image file.

    :param path: image path
    :return: (H, W) or (H, W, 3 or 4) array in 0..1
    """
    if _HAVE_PIL:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            if im.mode in ("I;16", "I", "F"):
                arr = np.asarray(im, dtype=np.float32)
                scale = 65535.0 if im.mode == "I;16" else (float(arr.max()) or 1.0)
                return np.clip(arr / scale, 0.0, 1.0)
            arr = np.asarray(im.convert("RGBA"), dtype=np.float32) / 255.0
    else:  # pragma: no cover
        from matplotlib import pyplot as plt

        arr = np.asarray(plt.imread(path), dtype=np.float32)
        if arr.max() > 1.0:
            arr = arr / 255.0
    return arr


def target_grid(
    shape: tuple[int, int],
    pitch_mm: float,
    width_mm: float | None = None,
    height_mm: float | None = None,
    longest_mm: float | None = None,
) -> tuple[int, int, float, float]:
    r"""
    Work out the sample grid for the requested physical size.

    :param shape: source (height, width)
    :param pitch_mm: sample spacing
    :param width_mm: plate width
    :param height_mm: plate height
    :param longest_mm: longest side when width and height are unset
    :return: rows, cols, width_mm, height_mm
    """
    src_h, src_w = shape
    aspect = src_w / src_h

    if width_mm is None and height_mm is None:
        longest = longest_mm if longest_mm else 100.0
        if src_w >= src_h:
            width_mm, height_mm = longest, longest / aspect
        else:
            height_mm, width_mm = longest, longest * aspect
    elif width_mm is None:
        width_mm = height_mm * aspect
    elif height_mm is None:
        height_mm = width_mm / aspect

    cols = max(2, int(round(width_mm / pitch_mm)) + 1)
    rows = max(2, int(round(height_mm / pitch_mm)) + 1)
    return rows, cols, (cols - 1) * pitch_mm, (rows - 1) * pitch_mm


def resample(gray: np.ndarray, rows: int, cols: int, filter_name: str = "lanczos") -> np.ndarray:
    r"""
    Resample to an exact grid with an anti-aliased filter.

    :param gray: source array
    :param rows: target rows
    :param cols: target columns
    :param filter_name: one of RESAMPLE_FILTERS
    :return: float32 array of shape (rows, cols)
    """
    if gray.shape == (rows, cols):
        return gray.astype(np.float32, copy=False)

    if _HAVE_PIL:
        filters = {
            "lanczos": Image.LANCZOS,
            "bicubic": Image.BICUBIC,
            "bilinear": Image.BILINEAR,
            "nearest": Image.NEAREST,
        }
        pil_filter = filters.get(filter_name, Image.LANCZOS)
        im = Image.fromarray(np.ascontiguousarray(gray, dtype=np.float32), mode="F")
        out = np.asarray(im.resize((cols, rows), pil_filter), dtype=np.float32)
    else:  # pragma: no cover
        order = 1 if filter_name in ("bilinear", "nearest") else 3
        if rows < gray.shape[0]:
            gray = gaussian_filter(gray, sigma=0.5 * gray.shape[0] / rows)
        out = zoom(gray, (rows / gray.shape[0], cols / gray.shape[1]), order=order)
        out = np.asarray(out, dtype=np.float32)[:rows, :cols]

    return np.clip(out, 0.0, 1.0)


def auto_level(gray: np.ndarray, low_pct: float = 0.5, high_pct: float = 99.5) -> np.ndarray:
    r"""
    Stretch the histogram onto the full range.

    :param gray: tone array
    :param low_pct: lower clip percentile
    :param high_pct: upper clip percentile
    :return: stretched array
    """
    lo, hi = np.percentile(gray, [low_pct, high_pct])
    if hi - lo < 1e-4:
        return gray
    return np.clip((gray - lo) / (hi - lo), 0.0, 1.0).astype(np.float32)


def apply_contrast(gray: np.ndarray, contrast: float = 1.0, brightness: float = 0.0) -> np.ndarray:
    r"""
    Pivot contrast around mid-grey, then offset.

    :param gray: tone array
    :param contrast: contrast multiplier
    :param brightness: brightness offset
    :return: adjusted array
    """
    if contrast != 1.0:
        gray = (gray - 0.5) * contrast + 0.5
    if brightness:
        gray = gray + brightness
    return np.clip(gray, 0.0, 1.0).astype(np.float32)


def apply_gamma(gray: np.ndarray, gamma: float = 1.0) -> np.ndarray:
    r"""
    Tone curve; gamma > 1 lifts shadows.

    :param gray: tone array
    :param gamma: gamma value
    :return: adjusted array
    """
    if gamma == 1.0:
        return gray
    return np.clip(gray, 0.0, 1.0).astype(np.float32) ** (1.0 / gamma)


def unsharp(gray: np.ndarray, amount: float = 0.0, radius: float = 1.2) -> np.ndarray:
    r"""
    Unsharp mask.

    :param gray: tone array
    :param amount: strength, 0 disables
    :param radius: blur sigma in samples
    :return: sharpened array
    """
    if amount <= 0:
        return gray
    blurred = gaussian_filter(gray, sigma=radius)
    return np.clip(gray + amount * (gray - blurred), 0.0, 1.0).astype(np.float32)


def smooth(gray: np.ndarray, sigma: float = 0.0) -> np.ndarray:
    r"""
    Gaussian smoothing.

    :param gray: tone array
    :param sigma: blur sigma in samples, 0 disables
    :return: smoothed array
    """
    if sigma <= 0:
        return gray
    return gaussian_filter(gray, sigma=sigma).astype(np.float32)


def parse_hex_color(text: str) -> np.ndarray:
    r"""
    Parse "#rrggbb", "rrggbb" or "#rgb".

    :param text: colour string
    :return: sRGB triple in 0..1
    """
    value = str(text).strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in value):
        raise ValueError(f"not a hex colour: {text!r}; expected something like #1e90ff")
    return np.array(
        [int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4)], dtype=np.float32
    )


def background_nearness(rgb: np.ndarray, color: np.ndarray) -> np.ndarray:
    r"""
    How close each pixel is to a colour, measured in linear light.

    :param rgb: (H, W, 3) sRGB image
    :param color: sRGB triple
    :return: array where 1.0 is an exact match
    """
    diff = srgb_to_linear(rgb) - srgb_to_linear(color)
    distance = np.sqrt(np.einsum("...c,...c->...", diff, diff) / 3.0)
    return (1.0 - np.clip(distance, 0.0, 1.0)).astype(np.float32)


def foreground_mask(
    tone: np.ndarray, threshold: float = 0.9, min_island_px: int = 0
) -> np.ndarray:
    r"""
    The samples to keep: everything darker than the threshold.

    :param tone: tone array
    :param threshold: tone at or above this is background
    :param min_island_px: drop kept islands smaller than this
    :return: boolean mask
    """
    keep = tone < threshold
    if min_island_px > 1 and keep.any():
        labels, found = label(keep)
        if found:
            sizes = np.bincount(labels.ravel())
            sizes[0] = 0
            keep = (sizes >= min_island_px)[labels]
    return keep


def prepare(
    gray: np.ndarray,
    *,
    pitch_mm: float = 0.2,
    width_mm: float | None = None,
    height_mm: float | None = None,
    longest_mm: float | None = None,
    resample_filter: str = "lanczos",
    denoise: float = 0.0,
    autolevel: bool = True,
    level_clip: tuple[float, float] = (0.5, 99.5),
    contrast: float = 1.0,
    brightness: float = 0.0,
    gamma: float = 1.0,
    smooth_sigma: float = 0.0,
    sharpen: float = 0.0,
    sharpen_radius: float = 1.2,
    invert: bool = False,
    mirror: bool = False,
) -> tuple[np.ndarray, float, float]:
    r"""
    Run the full tone pipeline.

    :param gray: source grayscale image
    :return: tone, width_mm, height_mm
    """
    if denoise > 0:
        gray = gaussian_filter(gray, sigma=denoise).astype(np.float32)

    rows, cols, width_mm, height_mm = target_grid(
        gray.shape, pitch_mm, width_mm, height_mm, longest_mm
    )
    tone = resample(gray, rows, cols, resample_filter)

    if autolevel:
        tone = auto_level(tone, *level_clip)
    tone = apply_contrast(tone, contrast, brightness)
    tone = apply_gamma(tone, gamma)
    tone = smooth(tone, smooth_sigma)
    tone = unsharp(tone, sharpen, sharpen_radius)

    if invert:
        tone = 1.0 - tone
    if mirror:
        tone = tone[:, ::-1]

    tone = np.nan_to_num(tone, nan=1.0, posinf=1.0, neginf=0.0)
    return np.clip(tone, 0.0, 1.0).astype(np.float32), width_mm, height_mm

r"""
Mapping image tone to plate thickness (Beer-Lambert aware).
"""

from __future__ import annotations

import numpy as np

CURVES = ("beer", "linear", "gamma")

DEFAULT_MU = 1.2


def tone_to_thickness(
    tone: np.ndarray,
    min_mm: float = 0.6,
    max_mm: float = 3.0,
    curve: str = "beer",
    mu: float = DEFAULT_MU,
    curve_gamma: float = 2.2,
) -> np.ndarray:
    r"""
    Convert tone to thickness; white maps to min_mm and black to max_mm.

    :param tone: array in 0..1, 0 = black
    :param min_mm: thinnest point
    :param max_mm: thickest point
    :param curve: one of CURVES
    :param mu: attenuation in 1/mm for the beer curve
    :param curve_gamma: exponent for the gamma curve
    :return: thickness in mm, float32
    """
    if not 0 < min_mm < max_mm:
        raise ValueError(f"need 0 < min_mm < max_mm, got min={min_mm}, max={max_mm}")

    tone = np.clip(np.asarray(tone, dtype=np.float32), 0.0, 1.0)

    if curve == "linear":
        frac = 1.0 - tone
    elif curve == "gamma":
        if curve_gamma <= 0:
            raise ValueError("curve_gamma must be positive")
        frac = 1.0 - tone ** (1.0 / curve_gamma)
    elif curve == "beer":
        if mu <= 0:
            raise ValueError("mu must be positive")
        t_bright = np.exp(-mu * min_mm, dtype=np.float32)
        t_dark = np.exp(-mu * max_mm, dtype=np.float32)
        transmission = t_dark + tone * (t_bright - t_dark)
        thickness = -np.log(transmission) / mu
        return np.clip(thickness, min_mm, max_mm).astype(np.float32)
    else:
        raise ValueError(f"unknown curve {curve!r}; choose from {CURVES}")

    return (min_mm + frac * (max_mm - min_mm)).astype(np.float32)


def add_border(
    thickness: np.ndarray,
    pitch_mm: float,
    border_mm: float,
    border_thickness_mm: float | None = None,
    feather_mm: float = 0.4,
) -> np.ndarray:
    r"""
    Raise a flat, feathered rim around the plate.

    :param thickness: thickness map in mm
    :param pitch_mm: sample spacing
    :param border_mm: rim width, 0 disables
    :param border_thickness_mm: rim thickness, defaults to the map maximum
    :param feather_mm: width of the ramp into the image
    :return: thickness map with the rim
    """
    if border_mm <= 0:
        return thickness

    out = thickness.copy()
    rim = max(1, int(round(border_mm / pitch_mm)))
    level = float(border_thickness_mm if border_thickness_mm else thickness.max())

    rows, cols = out.shape
    if rim * 2 >= min(rows, cols):
        return np.full_like(out, level)

    iy = np.minimum(np.arange(rows), np.arange(rows)[::-1])[:, None]
    ix = np.minimum(np.arange(cols), np.arange(cols)[::-1])[None, :]
    edge_dist = np.minimum(iy, ix).astype(np.float32)

    feather = max(1e-6, feather_mm / pitch_mm)
    weight = np.clip((rim + feather - edge_dist) / feather, 0.0, 1.0)
    return (out * (1.0 - weight) + level * weight).astype(np.float32)

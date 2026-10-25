# Copyright (C) 2026 MekaElectronics
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software under the GNU General Public License v3 or later; see LICENSE.
r"""
High-level lithophane generation.
"""

from __future__ import annotations

import os
import time

import numpy as np

from . import geometry, imaging, tone as tone_mod, writers
from .geometry import Mesh, build_mesh, check_watertight


class LithophaneSettings:
    r"""
    Everything that shapes the result.
    """

    FIELDS = (
        "pitch_mm", "width_mm", "height_mm", "longest_mm","min_mm", "max_mm",
        "curve", "mu", "curve_gamma", "resample_filter", "denoise", "autolevel",
        "level_clip", "contrast", "brightness", "gamma", "smooth_sigma", "sharpen",
        "sharpen_radius", "invert", "mirror","cutout", "bg_threshold", "bg_color", 
        "bg_tolerance", "relief", "min_island_mm2", "border_mm", "border_thickness_mm",
        "curve_radius", "back_segments", "adaptive_diagonals", "max_triangles"
    )

    def __init__(
        self,
        pitch_mm: float = 0.2,
        width_mm: float | None = None,
        height_mm: float | None = None,
        longest_mm: float | None = 100.0,
        min_mm: float = 0.6,
        max_mm: float = 3.0,
        curve: str = "beer",
        mu: float = tone_mod.DEFAULT_MU,
        curve_gamma: float = 2.2,
        resample_filter: str = "lanczos",
        denoise: float = 0.0,
        autolevel: bool = True,
        level_clip: tuple[float, float] = (0.5, 99.5),
        contrast: float = 1.0,
        brightness: float = 0.0,
        gamma: float = 1.0,
        smooth_sigma: float = 0.0,
        sharpen: float = 0.35,
        sharpen_radius: float = 1.2,
        invert: bool = False,
        mirror: bool = False,
        cutout: bool = False,
        bg_threshold: float = 0.9,
        bg_color: str | None = None,
        bg_tolerance: float = 0.12,
        relief: bool = False,
        min_island_mm2: float = 1.0,
        border_mm: float = 0.0,
        border_thickness_mm: float | None = None,
        curve_radius: float | None = None,
        back_segments: int | None = None,
        adaptive_diagonals: bool = True,
        max_triangles: int | None = 4_000_000,
    ) -> None:
        self.pitch_mm = pitch_mm
        self.width_mm = width_mm
        self.height_mm = height_mm
        self.longest_mm = longest_mm

        self.min_mm = min_mm
        self.max_mm = max_mm
        self.curve = curve
        self.mu = mu
        self.curve_gamma = curve_gamma

        self.resample_filter = resample_filter
        self.denoise = denoise
        self.autolevel = autolevel
        self.level_clip = level_clip
        self.contrast = contrast
        self.brightness = brightness
        self.gamma = gamma
        self.smooth_sigma = smooth_sigma
        self.sharpen = sharpen
        self.sharpen_radius = sharpen_radius
        self.invert = invert
        self.mirror = mirror

        self.cutout = cutout
        self.bg_threshold = bg_threshold
        self.bg_color = bg_color
        self.bg_tolerance = bg_tolerance
        self.relief = relief
        self.min_island_mm2 = min_island_mm2

        self.border_mm = border_mm
        self.border_thickness_mm = border_thickness_mm
        self.curve_radius = curve_radius
        self.back_segments = back_segments
        self.adaptive_diagonals = adaptive_diagonals

        self.max_triangles = max_triangles

    def as_dict(self) -> dict:
        return {name: getattr(self, name) for name in self.FIELDS}

    def replace(self, **overrides) -> LithophaneSettings:
        r"""
        Copy with some fields changed.

        :param overrides: field names and new values
        :return: the new settings
        """
        values = self.as_dict()
        values.update(overrides)
        return LithophaneSettings(**values)

    def __eq__(self, other) -> bool:
        if not isinstance(other, LithophaneSettings):
            return NotImplemented
        return self.as_dict() == other.as_dict()

    __hash__ = None

    def __repr__(self) -> str:
        inner = ", ".join(f"{name}={getattr(self, name)!r}" for name in self.FIELDS)
        return f"LithophaneSettings({inner})"

    def validate(self) -> None:
        if self.pitch_mm <= 0:
            raise ValueError("pitch_mm must be positive")
        if not 0 < self.min_mm < self.max_mm:
            raise ValueError("need 0 < min_mm < max_mm")
        if self.curve not in tone_mod.CURVES:
            raise ValueError(f"curve must be one of {tone_mod.CURVES}")
        if self.resample_filter not in imaging.RESAMPLE_FILTERS:
            raise ValueError(f"resample_filter must be one of {imaging.RESAMPLE_FILTERS}")
        if self.cutout and not 0.0 < self.bg_threshold <= 1.0:
            raise ValueError("bg_threshold must be in (0, 1]")
        if self.cutout and not 0.0 < self.bg_tolerance <= 1.0:
            raise ValueError("bg_tolerance must be in (0, 1]")
        if self.bg_color:
            imaging.parse_hex_color(self.bg_color)


class LithophaneResult:
    r"""
    What came out, and the numbers worth printing.
    """

    def __init__(
        self,
        mesh: Mesh,
        thickness: np.ndarray,
        settings: LithophaneSettings,
        width_mm: float,
        height_mm: float,
        output_path: str | None = None,
        elapsed_s: float = 0.0,
        stats: dict | None = None,
    ) -> None:
        self.mesh = mesh
        self.thickness = thickness
        self.settings = settings
        self.width_mm = width_mm
        self.height_mm = height_mm
        self.output_path = output_path
        self.elapsed_s = elapsed_s
        self.stats = {} if stats is None else stats

    def __repr__(self) -> str:
        rows, cols = self.thickness.shape
        return (
            f"LithophaneResult({self.width_mm:.1f} x {self.height_mm:.1f} mm, "
            f"{cols}x{rows} samples, {self.mesh.triangle_count():,} triangles, "
            f"output_path={self.output_path!r})"
        )

    def summary(self) -> str:
        rows, cols = self.thickness.shape
        lines = [
            f"plate      {self.width_mm:.1f} x {self.height_mm:.1f} x "
            f"{self.thickness.max():.2f} mm",
            f"samples    {cols} x {rows}  (pitch {self.settings.pitch_mm} mm)",
            f"thickness  {self.thickness.min():.2f} - {self.thickness.max():.2f} mm "
            f"({self.settings.curve} curve)",
            f"mesh       {self.mesh.triangle_count():,} triangles, "
            f"{self.mesh.vertex_count():,} vertices",
        ]
        if self.stats:
            state = "watertight" if self.stats.get("watertight") else "NOT watertight"
            lines.append(
                f"check      {state}, "
                f"{self.stats.get('boundary_edges', 0)} boundary / "
                f"{self.stats.get('nonmanifold_edges', 0)} non-manifold edges"
            )
            vol = self.stats.get("volume_mm3", 0.0)
            if vol:
                lines.append(f"volume     {vol / 1000.0:.2f} cm3 (~{vol * 1.24e-3:.1f} g in PLA)")
        if self.output_path:
            size = os.path.getsize(self.output_path) / 1e6
            lines.append(f"output     {self.output_path} ({size:.2f} MB)")
        lines.append(f"elapsed    {self.elapsed_s:.2f} s")
        return "\n".join(lines)


def _fit_triangle_budget(
    shape: tuple[int, int], settings: LithophaneSettings, verbose: bool
) -> LithophaneSettings:
    r"""
    Coarsen the pitch if the grid would exceed the triangle budget.

    :param shape: source (height, width)
    :param settings: requested settings
    :param verbose: print when the pitch changes
    :return: settings that fit the budget
    """
    if not settings.max_triangles:
        return settings

    def estimate(pitch: float) -> int:
        rows, cols, width_mm, _ = imaging.target_grid(
            shape, pitch, settings.width_mm, settings.height_mm, settings.longest_mm
        )
        surface = 2 * (rows - 1) * (cols - 1)
        ring = 2 * (rows + cols) - 4
        if not settings.curve_radius:
            return surface + 2 * ring + ring

        segs = geometry.back_segment_count(
            width_mm, settings.curve_radius, cols, settings.back_segments
        )
        return surface + (ring + 2 * (segs + 1)) + 2 * segs

    original = estimate(settings.pitch_mm)
    if original <= settings.max_triangles:
        return settings

    pitch = settings.pitch_mm
    for _ in range(8):
        pitch *= (estimate(pitch) / settings.max_triangles) ** 0.5 * 1.001
        if estimate(pitch) <= settings.max_triangles:
            break

    if verbose:
        print(
            f"[lithogen] {original:,} triangles exceeds the "
            f"{settings.max_triangles:,} budget; "
            f"pitch {settings.pitch_mm:.3f} -> {pitch:.3f} mm"
        )
    return settings.replace(pitch_mm=pitch)


def generate(
    image_path: str,
    output_path: str | None = "Output.stl",
    settings: LithophaneSettings | None = None,
    *,
    fmt: str | None = None,
    validate: bool = True,
    verbose: bool = True,
    **overrides,
) -> LithophaneResult:
    r"""
    Turn an image into a printable lithophane.

    :param image_path: input image
    :param output_path: output file, None to skip writing
    :param settings: settings object, defaults if None
    :param fmt: output format, defaults to the extension
    :param validate: run the manifold check
    :param verbose: print progress
    :param overrides: settings fields applied on top of settings
    :return: the result
    """
    started = time.perf_counter()

    settings = settings or LithophaneSettings()
    if overrides:
        settings = settings.replace(**overrides)
    settings.validate()

    if not os.path.exists(image_path):
        raise FileNotFoundError(f"image not found: {image_path}")

    if verbose:
        print(f"[lithogen] loading {image_path}")
    gray = imaging.load_grayscale(image_path)

    settings = _fit_triangle_budget(gray.shape, settings, verbose)

    tone, width_mm, height_mm = imaging.prepare(
        gray,
        pitch_mm=settings.pitch_mm,
        width_mm=settings.width_mm,
        height_mm=settings.height_mm,
        longest_mm=settings.longest_mm,
        resample_filter=settings.resample_filter,
        denoise=settings.denoise,
        autolevel=settings.autolevel,
        level_clip=settings.level_clip,
        contrast=settings.contrast,
        brightness=settings.brightness,
        gamma=settings.gamma,
        smooth_sigma=settings.smooth_sigma,
        sharpen=settings.sharpen,
        sharpen_radius=settings.sharpen_radius,
        invert=settings.invert,
        mirror=settings.mirror,
    )

    mask = None
    if settings.cutout:
        min_island_px = int(settings.min_island_mm2 / settings.pitch_mm**2)
        if settings.bg_color:
            rows, cols = tone.shape
            nearness = imaging.background_nearness(imaging.load_rgb(image_path), imaging.parse_hex_color(settings.bg_color))
            nearness = imaging.resample(nearness, rows, cols, settings.resample_filter)
            if settings.mirror:
                nearness = nearness[:, ::-1]
            mask = imaging.foreground_mask(nearness, 1.0 - settings.bg_tolerance, min_island_px)
        else:
            mask = imaging.foreground_mask(tone, settings.bg_threshold, min_island_px)

        if verbose:
            against = f"colour {settings.bg_color}" if settings.bg_color else "brightness"
            print(f"[lithogen] keeping {100.0 * mask.mean():.1f}% of the frame, background cut away by {against}")

    if settings.cutout and not settings.relief:
        thickness = np.full(tone.shape, settings.max_mm, dtype=np.float32)
    else:
        thickness = tone_mod.tone_to_thickness(
            tone,
            min_mm=settings.min_mm,
            max_mm=settings.max_mm,
            curve=settings.curve,
            mu=settings.mu,
            curve_gamma=settings.curve_gamma,
        )

    if settings.cutout:
        if settings.border_mm and verbose:
            print("[lithogen] ignoring the border: a cut-out has no rectangle to frame")
    else:
        thickness = tone_mod.add_border(thickness, settings.pitch_mm, settings.border_mm, settings.border_thickness_mm)

    if verbose:
        print(f"[lithogen] building mesh from a {thickness.shape[1]}x{thickness.shape[0]} grid")
    mesh = build_mesh(
        thickness,
        settings.pitch_mm,
        curve_radius=settings.curve_radius,
        adaptive_diagonals=settings.adaptive_diagonals,
        back_segments=settings.back_segments,
        mask=mask,
    )

    stats = check_watertight(mesh) if validate else {}
    if validate and not stats["watertight"]:  # pragma: no cover
        print(f"[lithogen] WARNING: mesh is not watertight ({stats['boundary_edges']} boundary edges).")

    if output_path:
        name = os.path.splitext(os.path.basename(image_path))[0]
        writers.write_mesh(mesh, output_path, fmt=fmt, name=name)

    result = LithophaneResult(
        mesh=mesh,
        thickness=thickness,
        settings=settings,
        width_mm=width_mm,
        height_mm=height_mm,
        output_path=output_path,
        elapsed_s=time.perf_counter() - started,
        stats=stats,
    )
    if verbose:
        print(result.summary())
    return result


def settings_dict(settings: LithophaneSettings) -> dict:
    r"""
    Settings as a plain dict.

    :param settings: settings object
    :return: dict of field names to values
    """
    return settings.as_dict()

# Copyright (C) 2026 MekaElectronics
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software under the GNU General Public License v3 or later; see LICENSE.
r"""
LithoGen - turn images into printable lithophanes.
"""

from __future__ import annotations

from .core import (
    LithophaneResult,
    LithophaneSettings,
    generate,
    settings_dict,
)
from .geometry import Mesh, build_mesh, check_watertight
from .imaging import load_grayscale, prepare
from .tone import add_border, tone_to_thickness
from .writers import write_3mf, write_binary_stl, write_mesh

__all__ = [
    "LithophaneResult",
    "LithophaneSettings",
    "Mesh",
    "add_border",
    "build_mesh",
    "check_watertight",
    "generate",
    "load_grayscale",
    "prepare",
    "settings_dict",
    "tone_to_thickness",
    "write_3mf",
    "write_binary_stl",
    "write_mesh",
]

#!/usr/bin/env python3
# Copyright (C) 2026 MekaElectronics
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software under the GNU General Public License v3 or later; see LICENSE.
r"""
LithoGen command line entry point, e.g. python LithoGen.py photo.jpg -o photo.3mf
"""

from __future__ import annotations

import sys

from lithogen.cli import main

if __name__ == "__main__":
    sys.exit(main())

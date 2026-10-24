#!/usr/bin/env python3
r"""
LithoGen command line entry point, e.g. python LithoGen.py photo.jpg -o photo.3mf
"""

from __future__ import annotations

import sys

from lithogen.cli import main

if __name__ == "__main__":
    sys.exit(main())

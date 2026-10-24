r"""
Command line interface.
"""

from __future__ import annotations

import argparse
import sys

from .core import LithophaneSettings, generate
from .imaging import RESAMPLE_FILTERS
from .tone import CURVES
from .writers import FORMATS

EPILOG = """\
examples:
  # 100 mm wide plate, sensible defaults
  lithogen photo.jpg

  # 150 mm tall, finer sampling, 3MF output (much smaller file)
  lithogen photo.jpg -o photo.3mf --height 150 -p 0.15

  # framed and stiffened, with a gentle curve so the edges stay lit
  lithogen photo.jpg --border 3 --curve-radius 120

  # preview the thickness map without writing geometry
  lithogen photo.jpg --preview --dry-run

  # a logo keychain: background cut away, flat 3 mm extrusion
  lithogen logo.png --cutout -s 40 -M 3
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lithogen",
        description="Generate a printable lithophane from an image.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("path", help="input image (jpg, png, bmp, tiff, webp, ...)")
    p.add_argument("-o", "--output", default=None,
                   help="output file; extension picks the format (default Output.stl)")
    p.add_argument("-f", "--format", choices=FORMATS, default=None,
                   help="force the output format regardless of extension")

    size = p.add_argument_group("size")
    size.add_argument("-p", "--pixelsize", "--pitch", type=float, default=0.2, dest="pitch",
                      help="XY sample spacing in mm (default 0.2)")
    size.add_argument("-W", "--width", type=float, default=None, help="plate width in mm")
    size.add_argument("-H", "--height", type=float, default=None, help="plate height in mm")
    size.add_argument("-s", "--size", type=float, default=100.0, dest="longest",
                      help="longest side in mm when width/height are unset (default 100)")

    thick = p.add_argument_group("thickness")
    thick.add_argument("-m", "--min", type=float, default=0.6, dest="min_mm",
                       help="thinnest point, the highlights, in mm (default 0.6)")
    thick.add_argument("-M", "--max", type=float, default=3.0, dest="max_mm",
                       help="thickest point, the shadows, in mm (default 3.0)")
    thick.add_argument("-c", "--curve", choices=CURVES, default="beer",
                       help="tone-to-thickness curve (default beer, physically linear)")
    thick.add_argument("--mu", type=float, default=1.2,
                       help="filament attenuation in 1/mm for the beer curve (default 1.2)")
    thick.add_argument("--curve-gamma", type=float, default=2.2,
                       help="exponent for the gamma curve (default 2.2)")

    img = p.add_argument_group("image")
    img.add_argument("-g", "--gaussian", "--smooth", type=float, default=0.0, dest="smooth",
                     help="gaussian smoothing sigma, in samples (default 0)")
    img.add_argument("--denoise", type=float, default=0.0,
                     help="pre-resize blur sigma, in source pixels, for noisy photos")
    img.add_argument("--sharpen", type=float, default=0.35,
                     help="unsharp amount applied after resampling (default 0.35)")
    img.add_argument("--sharpen-radius", type=float, default=1.2,
                     help="unsharp radius in samples (default 1.2)")
    img.add_argument("--contrast", type=float, default=1.0, help="contrast multiplier")
    img.add_argument("--brightness", type=float, default=0.0, help="brightness offset, -1..1")
    img.add_argument("--gamma", type=float, default=1.0,
                     help="tone gamma; >1 lifts shadows, <1 deepens them")
    img.add_argument("--no-autolevel", action="store_false", dest="autolevel",
                     help="keep the original histogram instead of stretching it")
    img.add_argument("--level-clip", type=float, nargs=2, default=(0.5, 99.5),
                     metavar=("LOW", "HIGH"), help="autolevel percentiles (default 0.5 99.5)")
    img.add_argument("--filter", choices=RESAMPLE_FILTERS, default="lanczos", dest="resample",
                     help="resampling filter (default lanczos)")
    img.add_argument("-i", "--invert", action="store_true",
                     help="invert tone, for a negative or a front-lit plate")
    img.add_argument("--mirror", action="store_true",
                     help="mirror horizontally, for printing face-down against the bed")

    cut = p.add_argument_group("cut-out (logo / keychain)")
    cut.add_argument("--cutout", action="store_true",
                     help="drop the background and keep only the artwork, so the "
                          "outline follows the design instead of a rectangle")
    cut.add_argument("--bg-threshold", type=float, default=0.9, metavar="T",
                     help="tone at or above this counts as background, 0..1 (default 0.9)")
    cut.add_argument("--bg-color", default=None, metavar="HEX",
                     help="cut on a background colour instead of brightness, e.g. "
                          "#1e90ff; use for any background that is not white")
    cut.add_argument("--bg-tolerance", type=float, default=0.12, metavar="T",
                     help="how far a pixel may sit from --bg-color and still count "
                          "as background, 0..1 (default 0.12)")
    cut.add_argument("--relief", action="store_true",
                     help="keep the tone relief in a cut-out; the default is a flat "
                          "extrusion at --max")
    cut.add_argument("--min-island", type=float, default=1.0, metavar="MM2",
                     help="drop kept specks smaller than this area in mm2 (default 1.0)")

    geo = p.add_argument_group("geometry")
    geo.add_argument("-b", "--border", type=float, default=0.0, dest="border",
                     help="flat rim width in mm, for stiffness and framing")
    geo.add_argument("--border-thickness", type=float, default=None,
                     help="rim thickness in mm (default: the maximum thickness)")
    geo.add_argument("--curve-radius", type=float, default=None,
                     help="bend the plate around a cylinder of this radius in mm")
    geo.add_argument("--back-segments", type=int, default=None, metavar="N",
                     help="quads across the back of a bent plate (default: as few as "
                          "the bend radius allows); lower for a smaller file")
    geo.add_argument("--no-adaptive-diagonals", action="store_false", dest="adaptive",
                     help="always split quads the same way instead of following the surface")
    geo.add_argument("--max-triangles", type=int, default=4_000_000,
                     help="triangle budget; the pitch is coarsened to fit (0 disables)")

    out = p.add_argument_group("output")
    out.add_argument("--preview", action="store_true",
                     help="show the thickness map before writing (needs matplotlib)")
    out.add_argument("--preview-save", default=None,
                     help="save the thickness map as an image instead of showing it")
    out.add_argument("--no-validate", action="store_false", dest="validate",
                     help="skip the manifold check")
    out.add_argument("--dry-run", action="store_true", help="do everything except write the mesh")
    out.add_argument("-q", "--quiet", action="store_true", help="only report errors")
    return p


def _save_preview(thickness, path: str | None, show: bool) -> None:
    r"""
    Save and/or show the thickness map.

    :param thickness: thickness map
    :param path: image path to save to, or None
    :param show: open a window
    """
    try:
        import matplotlib

        if not show:
            matplotlib.use("Agg")
        from matplotlib import pyplot as plt
    except ImportError:
        print("[lithogen] matplotlib is not installed; skipping preview", file=sys.stderr)
        return

    fig, ax = plt.subplots(figsize=(6, 6 * thickness.shape[0] / thickness.shape[1]))
    im = ax.imshow(thickness, cmap="bone_r")
    ax.set_axis_off()
    fig.colorbar(im, ax=ax, label="thickness (mm)", shrink=0.8)
    fig.tight_layout()
    if path:
        fig.savefig(path, dpi=150, bbox_inches="tight")
        print(f"[lithogen] preview written to {path}")
    if show:
        plt.show()
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    output = args.output
    if output is None and not args.dry_run:
        output = "Output.stl" if args.format in (None, "stl") else "Output.3mf"

    settings = LithophaneSettings(
        pitch_mm=args.pitch,
        width_mm=args.width,
        height_mm=args.height,
        longest_mm=args.longest,
        min_mm=args.min_mm,
        max_mm=args.max_mm,
        curve=args.curve,
        mu=args.mu,
        curve_gamma=args.curve_gamma,
        resample_filter=args.resample,
        denoise=args.denoise,
        autolevel=args.autolevel,
        level_clip=tuple(args.level_clip),
        contrast=args.contrast,
        brightness=args.brightness,
        gamma=args.gamma,
        smooth_sigma=args.smooth,
        sharpen=args.sharpen,
        sharpen_radius=args.sharpen_radius,
        invert=args.invert,
        mirror=args.mirror,
        cutout=args.cutout,
        bg_threshold=args.bg_threshold,
        bg_color=args.bg_color,
        bg_tolerance=args.bg_tolerance,
        relief=args.relief,
        min_island_mm2=args.min_island,
        border_mm=args.border,
        border_thickness_mm=args.border_thickness,
        curve_radius=args.curve_radius,
        back_segments=args.back_segments,
        adaptive_diagonals=args.adaptive,
        max_triangles=args.max_triangles or None,
    )

    try:
        result = generate(
            args.path,
            None if args.dry_run else output,
            settings,
            fmt=args.format,
            validate=args.validate,
            verbose=not args.quiet,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"lithogen: {exc}", file=sys.stderr)
        return 1

    if args.preview or args.preview_save:
        _save_preview(result.thickness, args.preview_save, args.preview)

    if args.dry_run and not args.quiet:
        print("[lithogen] dry run, nothing written")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

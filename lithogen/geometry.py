# Copyright (C) 2026 MekaElectronics
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software under the GNU General Public License v3 or later; see LICENSE.
r"""
Watertight mesh construction from a thickness map.
"""

from __future__ import annotations

import numpy as np

BACK_CHORD_TOLERANCE_MM = 0.05


class Mesh:
    r"""
    An indexed triangle mesh.
    """

    def __init__(self, vertices: np.ndarray, faces: np.ndarray) -> None:
        self.vertices = vertices
        self.faces = faces

    def __repr__(self) -> str:
        return f"Mesh({self.vertex_count():,} vertices, {self.triangle_count():,} triangles)"

    def triangle_count(self) -> int:
        return int(self.faces.shape[0])

    def vertex_count(self) -> int:
        return int(self.vertices.shape[0])

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        return self.vertices.min(axis=0), self.vertices.max(axis=0)

    def expand(self) -> np.ndarray:
        r"""
        Faces as raw coordinates.

        :return: (F, 3, 3) array
        """
        return self.vertices[self.faces]

    def face_normals(self) -> np.ndarray:
        tris = self.expand()
        n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
        norms = np.linalg.norm(n, axis=1, keepdims=True)
        np.divide(n, norms, out=n, where=norms > 0)
        return n.astype(np.float32)

    def volume_mm3(self) -> float:
        r"""
        Signed volume, positive if outward-wound.

        :return: volume in mm3
        """
        tris = self.expand().astype(np.float64)
        return float(np.einsum("ij,ij->i", tris[:, 0], np.cross(tris[:, 1], tris[:, 2])).sum() / 6.0)


def _boundary_ring(rows: int, cols: int) -> np.ndarray:
    r"""
    Grid indices of the boundary, counter-clockwise seen from +z.

    :param rows: grid rows
    :param cols: grid columns
    :return: (N, 2) array of row, column indices
    """
    r, c = rows - 1, cols - 1
    bottom = np.stack([np.full(c, r), np.arange(c)], axis=1)
    right = np.stack([np.arange(r, 0, -1), np.full(r, c)], axis=1)
    top = np.stack([np.zeros(c, dtype=int), np.arange(c, 0, -1)], axis=1)
    left = np.stack([np.arange(0, r), np.zeros(r, dtype=int)], axis=1)
    return np.concatenate([bottom, right, top, left]).astype(np.int64)


def _surface_faces(thickness: np.ndarray, adaptive_diagonals: bool = True) -> np.ndarray:
    r"""
    Triangulate the sample grid, two triangles per cell.

    :param thickness: thickness map
    :param adaptive_diagonals: split each quad along its flatter diagonal
    :return: (F, 3) face indices
    """
    rows, cols = thickness.shape
    idx = np.arange(rows * cols, dtype=np.int64).reshape(rows, cols)

    a = idx[:-1, :-1].ravel()
    b = idx[:-1, 1:].ravel()
    c = idx[1:, :-1].ravel()
    d = idx[1:, 1:].ravel()

    if adaptive_diagonals:
        z = thickness
        diag_bc = np.abs(z[:-1, 1:] - z[1:, :-1]).ravel()
        diag_ad = np.abs(z[:-1, :-1] - z[1:, 1:]).ravel()
        use_bc = diag_bc <= diag_ad
    else:
        use_bc = np.ones(a.shape, dtype=bool)

    faces = np.empty((a.size * 2, 3), dtype=np.int64)
    faces[0::2] = np.where(use_bc[:, None], np.stack([a, c, b], 1), np.stack([a, c, d], 1))
    faces[1::2] = np.where(use_bc[:, None], np.stack([b, c, d], 1), np.stack([a, d, b], 1))
    return faces


def back_segment_count(width_mm: float, radius: float, cols: int, requested: int | None = None) -> int:
    r"""
    Quads to spend across the back of a bent plate.

    :param width_mm: plate width
    :param radius: bend radius
    :param cols: sample columns
    :param requested: explicit count, clamped to the grid
    :return: segment count
    """
    if requested:
        return int(min(max(int(requested), 1), cols - 1))
    span = (8.0 * radius * BACK_CHORD_TOLERANCE_MM) ** 0.5
    stride = max(1, int(span / (width_mm / (cols - 1))))
    return int(min(max(-(-(cols - 1) // stride), 1), cols - 1))


def _bend(vertices: np.ndarray, radius: float, width_mm: float) -> np.ndarray:
    r"""
    Wrap the plate around a vertical cylinder.

    :param vertices: (V, 3) vertices
    :param radius: cylinder radius
    :param width_mm: plate width
    :return: bent vertices
    """
    out = vertices.copy()
    theta = (vertices[:, 0] - width_mm / 2.0) / radius
    r = radius + vertices[:, 2]
    out[:, 0] = r * np.sin(theta)
    out[:, 2] = r * np.cos(theta) - radius
    return out.astype(np.float32)


def _solid_cells(mask: np.ndarray) -> np.ndarray:
    r"""
    Cells whose four corners are kept, with diagonal pinches closed.

    :param mask: boolean keep mask on the sample grid
    :return: boolean cell mask
    """
    cells = mask[:-1, :-1] & mask[:-1, 1:] & mask[1:, :-1] & mask[1:, 1:]
    for _ in range(16):
        down = cells[:-1, :-1] & cells[1:, 1:] & ~cells[:-1, 1:] & ~cells[1:, :-1]
        up = cells[:-1, 1:] & cells[1:, :-1] & ~cells[:-1, :-1] & ~cells[1:, 1:]
        if not (down.any() or up.any()):
            break
        cells[:-1, 1:] |= down
        cells[:-1, :-1] |= up
    return cells


def _masked_shell(
    thickness: np.ndarray,
    mask: np.ndarray,
    xs: np.ndarray,
    ys: np.ndarray,
    adaptive_diagonals: bool,
) -> tuple[np.ndarray, np.ndarray]:
    r"""
    Extrude only the kept cells so the outline follows the artwork.

    :param thickness: thickness map
    :param mask: boolean keep mask
    :param xs: x coordinate per column
    :param ys: y coordinate per row
    :param adaptive_diagonals: split each quad along its flatter diagonal
    :return: vertices and faces
    """
    cells = _solid_cells(np.asarray(mask, dtype=bool))
    if not cells.any():
        raise ValueError(
            "nothing is left after removing the background; "
            "raise the threshold, or check the image is not all one tone"
        )

    used = np.zeros(mask.shape, dtype=bool)
    used[:-1, :-1] |= cells
    used[:-1, 1:] |= cells
    used[1:, :-1] |= cells
    used[1:, 1:] |= cells
    vid = np.full(mask.shape, -1, dtype=np.int64)
    n_used = int(used.sum())
    vid[used] = np.arange(n_used, dtype=np.int64)

    gx, gy = np.meshgrid(xs, ys)
    top = np.stack([gx[used], gy[used], thickness[used]], axis=1).astype(np.float32)
    bottom = top.copy()
    bottom[:, 2] = 0.0
    verts = np.concatenate([top, bottom])

    ci, cj = np.nonzero(cells)
    a, b = vid[ci, cj], vid[ci, cj + 1]
    c, d = vid[ci + 1, cj], vid[ci + 1, cj + 1]

    if adaptive_diagonals:
        use_bc = np.abs(thickness[ci, cj + 1] - thickness[ci + 1, cj]) <= np.abs(
            thickness[ci, cj] - thickness[ci + 1, cj + 1]
        )
    else:
        use_bc = np.ones(a.shape, dtype=bool)

    surface = np.empty((a.size * 2, 3), dtype=np.int64)
    surface[0::2] = np.where(use_bc[:, None], np.stack([a, c, b], 1), np.stack([a, c, d], 1))
    surface[1::2] = np.where(use_bc[:, None], np.stack([b, c, d], 1), np.stack([a, d, b], 1))
    faces = [surface, (surface + n_used)[:, ::-1]]

    pad = np.zeros((cells.shape[0] + 2, cells.shape[1] + 2), dtype=bool)
    pad[1:-1, 1:-1] = cells
    for exposed, (pi, pj), (qi, qj) in (
        (cells & ~pad[2:, 1:-1], (1, 0), (1, 1)),
        (cells & ~pad[:-2, 1:-1], (0, 1), (0, 0)),
        (cells & ~pad[1:-1, :-2], (0, 0), (1, 0)),
        (cells & ~pad[1:-1, 2:], (1, 1), (0, 1)),
    ):
        ei, ej = np.nonzero(exposed)
        if ei.size == 0:
            continue
        p = vid[ei + pi, ej + pj]
        q = vid[ei + qi, ej + qj]
        wall = np.empty((p.size * 2, 3), dtype=np.int64)
        wall[0::2] = np.stack([p + n_used, q + n_used, q], axis=1)
        wall[1::2] = np.stack([p + n_used, q, p], axis=1)
        faces.append(wall)

    return verts, np.concatenate(faces)


def _zip_walls(ring_top: np.ndarray, coarse_pos: np.ndarray, coarse_vtx: np.ndarray) -> np.ndarray:
    r"""
    Stitch a fine top boundary to a coarser base boundary.

    :param ring_top: vertex indices of the fine boundary walk
    :param coarse_pos: position of each base vertex in that walk
    :param coarse_vtx: vertex indices of the base boundary
    :return: (F, 3) wall faces
    """
    n_ring = ring_top.size
    n_coarse = coarse_pos.size

    if n_coarse == n_ring:
        nxt = np.roll(np.arange(n_ring, dtype=np.int64), -1)
        walls = np.empty((n_ring * 2, 3), dtype=np.int64)
        walls[0::2] = np.stack([coarse_vtx, coarse_vtx[nxt], ring_top[nxt]], axis=1)
        walls[1::2] = np.stack([coarse_vtx, ring_top[nxt], ring_top], axis=1)
        return walls

    fans = []
    for s in range(n_coarse):
        p = int(coarse_pos[s])
        q = int(coarse_pos[(s + 1) % n_coarse])
        if q <= p:
            q += n_ring
        seg = ring_top[np.arange(p, q + 1) % n_ring]

        fan = np.empty((seg.size, 3), dtype=np.int64)
        fan[0] = (coarse_vtx[s], coarse_vtx[(s + 1) % n_coarse], seg[-1])
        fan[1:, 0] = coarse_vtx[s]
        fan[1:, 1] = seg[:0:-1]
        fan[1:, 2] = seg[-2::-1]
        fans.append(fan)
    return np.concatenate(fans)

def build_mesh(
    thickness: np.ndarray,
    pitch_mm: float,
    *,
    curve_radius: float | None = None,
    adaptive_diagonals: bool = True,
    back_segments: int | None = None,
    mask: np.ndarray | None = None,
) -> Mesh:
    r"""
    Build the closed plate from a thickness map.

    :param thickness: 2-D thickness map in mm
    :param pitch_mm: sample spacing
    :param curve_radius: bend radius, None for flat
    :param adaptive_diagonals: split each quad along its flatter diagonal
    :param back_segments: quads across the back of a bent plate, None for auto
    :param mask: samples to keep, None for a full rectangle
    :return: the mesh
    """
    thickness = np.asarray(thickness, dtype=np.float32)
    if thickness.ndim != 2 or min(thickness.shape) < 2:
        raise ValueError(f"thickness must be a 2-D grid of at least 2x2, got {thickness.shape}")
    if thickness.min() <= 0:
        raise ValueError("thickness must be strictly positive, or the side walls degenerate")

    rows, cols = thickness.shape
    width_mm = (cols - 1) * pitch_mm
    height_mm = (rows - 1) * pitch_mm

    xs = np.arange(cols, dtype=np.float32) * pitch_mm
    ys = (rows - 1 - np.arange(rows, dtype=np.float32)) * pitch_mm
    if mask is not None:
        if mask.shape != thickness.shape:
            raise ValueError(f"mask is {mask.shape}, thickness is {thickness.shape}")
        verts, faces = _masked_shell(thickness, mask, xs, ys, adaptive_diagonals)
        if curve_radius:
            if curve_radius <= thickness.max():
                raise ValueError("curve_radius must exceed the maximum thickness")
            verts = _bend(verts, curve_radius, width_mm)
        return Mesh(verts.astype(np.float32), faces.astype(np.int32))

    gx, gy = np.meshgrid(xs, ys)
    top = np.stack([gx.ravel(), gy.ravel(), thickness.ravel()], axis=1).astype(np.float32)

    faces = [_surface_faces(thickness, adaptive_diagonals)]
    vertices = [top]

    ring = _boundary_ring(rows, cols)
    ring_top = (ring[:, 0] * cols + ring[:, 1]).astype(np.int64)
    n_ring = ring_top.size
    offset = rows * cols

    if curve_radius:
        segments = back_segment_count(width_mm, curve_radius, cols, back_segments)
        bcols = np.unique(np.linspace(0, cols - 1, segments + 1).round().astype(np.int64))
        n_b = bcols.size

        back_xyz = np.zeros((2 * n_b, 3), dtype=np.float32)
        back_xyz[:n_b, 0] = back_xyz[n_b:, 0] = xs[bcols]
        back_xyz[n_b:, 1] = height_mm
        vertices.append(back_xyz)

        lo = offset + np.arange(n_b, dtype=np.int64)
        hi = offset + n_b + np.arange(n_b, dtype=np.int64)

        base_ring = np.concatenate([lo, hi[::-1]])
        coarse_pos = np.concatenate(
            [bcols, ((cols - 1) + (rows - 1) + (cols - 1 - bcols))[::-1]]
        )

        i = np.arange(n_b - 1)
        floor = np.empty((2 * (n_b - 1), 3), dtype=np.int64)
        floor[0::2] = np.stack([lo[i], hi[i + 1], lo[i + 1]], axis=1)
        floor[1::2] = np.stack([lo[i], hi[i], hi[i + 1]], axis=1)
    else:
        ring_xyz = top[ring_top].copy()
        ring_xyz[:, 2] = 0.0
        centre = np.array([[width_mm / 2.0, height_mm / 2.0, 0.0]], dtype=np.float32)
        vertices += [ring_xyz, centre]

        base_ring = offset + np.arange(n_ring, dtype=np.int64)
        coarse_pos = np.arange(n_ring, dtype=np.int64)
        centre_idx = offset + n_ring
        floor = np.stack(
            [
                np.full(n_ring, centre_idx, dtype=np.int64),
                base_ring[np.roll(np.arange(n_ring, dtype=np.int64), -1)],
                base_ring,
            ],
            axis=1,
        )

    faces.append(_zip_walls(ring_top, coarse_pos, base_ring))
    faces.append(floor)

    verts = np.concatenate(vertices).astype(np.float32)
    if curve_radius:
        if curve_radius <= thickness.max():
            raise ValueError("curve_radius must exceed the maximum thickness")
        verts = _bend(verts, curve_radius, width_mm)

    return Mesh(verts, np.concatenate(faces).astype(np.int32))


def check_watertight(mesh: Mesh) -> dict:
    r"""
    Report on manifoldness and degenerate faces.

    :param mesh: mesh to check
    :return: dict of counts, volume and a watertight flag
    """
    f = mesh.faces.astype(np.int64)
    edges = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    lo = edges.min(axis=1)
    hi = edges.max(axis=1)
    keys = lo * np.int64(mesh.vertex_count()) + hi
    _, counts = np.unique(keys, return_counts=True)

    tris = mesh.expand()
    areas = 0.5 * np.linalg.norm(np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]), axis=1)

    return {
        "triangles": mesh.triangle_count(),
        "vertices": mesh.vertex_count(),
        "boundary_edges": int((counts == 1).sum()),
        "nonmanifold_edges": int((counts > 2).sum()),
        "degenerate_faces": int((areas <= 0).sum()),
        "volume_mm3": mesh.volume_mm3(),
        "watertight": bool((counts == 2).all()),
    }

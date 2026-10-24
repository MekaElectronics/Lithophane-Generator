# Copyright (C) 2026 MekaElectronics
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software under the GNU General Public License v3 or later; see LICENSE.
r"""
Mesh output: binary STL and 3MF.
"""

from __future__ import annotations

import os
import zipfile
from importlib.resources import files
from xml.sax.saxutils import quoteattr

import numpy as np

from .geometry import Mesh

STL_TRIANGLE_DTYPE = np.dtype(
    [("normal", "<f4", 3), ("vertices", "<f4", (3, 3)), ("attr", "<u2")]
)
assert STL_TRIANGLE_DTYPE.itemsize == 50, "binary STL triangle record must be 50 bytes"

FORMATS = ("stl", "3mf")

RESOURCES = files(__package__) / "resources"

_PACKAGE_PARTS = {
    "[Content_Types].xml": "3mf/content-types.xml",
    "_rels/.rels": "3mf/package-rels.xml",
}

_CACHE: dict[str, bytes] = {}


def write_binary_stl(mesh: Mesh, path: str, header: str = "LithoGen") -> str:
    r"""
    Write a binary STL.

    :param mesh: mesh to write
    :param path: output path
    :param header: 80 byte header text
    :return: the output path
    """
    tris = mesh.expand().astype(np.float32)
    records = np.zeros(tris.shape[0], dtype=STL_TRIANGLE_DTYPE)
    records["vertices"] = tris
    records["normal"] = mesh.face_normals()

    with open(path, "wb") as fh:
        fh.write(header.encode("ascii", "replace")[:80].ljust(80, b"\0"))
        fh.write(int(tris.shape[0]).to_bytes(4, "little"))
        records.tofile(fh)
    return path


def resource_bytes(name: str) -> bytes:
    r"""
    Read a packaged resource, cached.

    :param name: path relative to the resources folder
    :return: the file content
    """
    data = _CACHE.get(name)
    if data is None:
        data = _CACHE[name] = (RESOURCES / name).read_bytes()
    return data


def _model_xml(mesh: Mesh, name: str) -> bytes:
    r"""
    Serialise the mesh as 3MF model XML.

    :param mesh: mesh to serialise
    :param name: object name
    :return: the XML bytes
    """
    parts = [
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<model unit="millimeter" xml:lang="en-US" '
        b'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
        b"<resources>"
        b'<object id="1" type="model" name=',
        quoteattr(name).encode("utf-8", "replace"),
        b"><mesh><vertices>",
    ]

    v = mesh.vertices
    vert_lines = np.char.add(
        np.char.add(
            np.char.add('<vertex x="', np.char.mod("%.4f", v[:, 0])),
            np.char.add('" y="', np.char.mod("%.4f", v[:, 1])),
        ),
        np.char.add(np.char.add('" z="', np.char.mod("%.4f", v[:, 2])), '"/>'),
    )
    parts.append("".join(vert_lines.tolist()).encode("ascii"))
    parts.append(b"</vertices><triangles>")

    f = mesh.faces
    tri_lines = np.char.add(
        np.char.add(
            np.char.add('<triangle v1="', np.char.mod("%d", f[:, 0])),
            np.char.add('" v2="', np.char.mod("%d", f[:, 1])),
        ),
        np.char.add(np.char.add('" v3="', np.char.mod("%d", f[:, 2])), '"/>'),
    )
    parts.append("".join(tri_lines.tolist()).encode("ascii"))
    parts.append(
        b"</triangles></mesh></object></resources>"
        b'<build><item objectid="1"/></build></model>'
    )
    return b"".join(parts)


def write_3mf(mesh: Mesh, path: str, name: str = "lithophane") -> str:
    r"""
    Write a 3MF package containing the indexed mesh.

    :param mesh: mesh to write
    :param path: output path
    :param name: object name
    :return: the output path
    """
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for member, resource in _PACKAGE_PARTS.items():
            zf.writestr(member, resource_bytes(resource))
        zf.writestr("3D/3dmodel.model", _model_xml(mesh, name))
    return path


def write_mesh(mesh: Mesh, path: str, fmt: str | None = None, name: str = "lithophane") -> str:
    r"""
    Write the mesh, picking the format from fmt or the file extension.

    :param mesh: mesh to write
    :param path: output path
    :param fmt: "stl" or "3mf", defaults to the extension
    :param name: object name
    :return: the output path
    """
    if fmt is None:
        fmt = os.path.splitext(path)[1].lstrip(".").lower() or "stl"
    fmt = fmt.lower()
    if fmt == "stl":
        return write_binary_stl(mesh, path, header=f"LithoGen {name}")
    if fmt == "3mf":
        return write_3mf(mesh, path, name=name)
    raise ValueError(f"unsupported output format {fmt!r}; choose from {FORMATS}")

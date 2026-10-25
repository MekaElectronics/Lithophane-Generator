#!/usr/bin/env python3
# Copyright (C) 2026 MekaElectronics
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software under the GNU General Public License v3 or later; see LICENSE.
r"""
LithoGen desktop front end. Needs: pip install PyQt5 vtk
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile

try:
    from PyQt5.QtCore import QPointF, QRectF, Qt, QThread, QTimer, pyqtSignal
    from PyQt5.QtGui import QColor, QIcon, QPainter, QPalette, QPen
    from PyQt5.QtWidgets import (
        QApplication,
        QCheckBox,
        QColorDialog,
        QComboBox,
        QDoubleSpinBox,
        QFileDialog,
        QFormLayout,
        QFrame,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSlider,
        QSpinBox,
        QTabWidget,
        QVBoxLayout,
        QWidget
    )
    import vtk
    from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
except ImportError as exc:
    sys.exit(f"GUI.py needs the viewer extras ({exc.name} is missing).\nInstall them with:  pip install PyQt5 vtk\nThe command line generator works without them:  python LithoGen.py --help")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lithogen import LithophaneSettings, generate  # noqa: E402
from lithogen.imaging import RESAMPLE_FILTERS  # noqa: E402,F401
from lithogen.tone import CURVES  # noqa: E402

DEFAULT_OPACITY_PCT = 85
FIELD_WIDTH = 112

RESOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")
PALETTE_PATH = os.path.join(RESOURCES, "palette.json")
THEME_PATH = os.path.join(RESOURCES, "theme.qss")
ICON_PATH = os.path.join(RESOURCES, "Icon.ico")

def load_palette(path: str = PALETTE_PATH) -> dict:
    r"""
    Read palette.json
    :param path: path to the palette file
    :return: dict of colour names to hex strings
    """
    with open(path, encoding="utf-8") as fh:
        return {k: v for k, v in json.load(fh).items() if not k.startswith("_")}

def load_stylesheet(palette: dict, path: str = THEME_PATH) -> str:
    r"""
    theme.qss with every @name swapped for its colour.

    :param palette: dict of colour names to hex strings
    :param path: path to the theme file
    :return: str of the modified stylesheet
    """
    with open(path, encoding="utf-8") as fh:
        sheet = fh.read()
    for name in sorted(palette, key=len, reverse=True):
        sheet = sheet.replace("@" + name, palette[name])
    leftover = sorted(set(re.findall(r"@[a-z][a-z-]*", sheet)))
    if leftover:
        raise KeyError(f"{os.path.basename(path)} uses unknown colours: {leftover}")
    return sheet

def as_rgb(colour: str) -> tuple[float, float, float]:
    r"""
    Hex colour as a 0..1 triple
    :param colour: "#rrggbb" string
    :return: tuple of floats for VTK
    """
    value = colour.lstrip("#")
    return tuple(int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4))

PALETTE = load_palette()

AMBER = PALETTE["amber"]
AMBER_HOVER = PALETTE["amber-hover"]
AMBER_PRESSED = PALETTE["amber-pressed"]
AMBER_TRACK = PALETTE["amber-track"]
CHARCOAL = PALETTE["charcoal"]
WINDOW = PALETTE["window"]
SUNKEN = PALETTE["sunken"]
FIELD = PALETTE["field"]
LINE = PALETTE["line"]
TEXT = PALETTE["text"]
TEXT_DIM = PALETTE["text-dim"]
TEXT_OFF = PALETTE["text-off"]

MODEL_RGB = as_rgb(PALETTE["model"])
BACKLIGHT_RGB = as_rgb(PALETTE["backlight"])
VIEWPORT_RGB = as_rgb(PALETTE["viewport"])

STYLESHEET = load_stylesheet(PALETTE)

def apply_theme(app: QApplication) -> None:
    r"""
    Apply the Fusion style, dark palette, stylesheet and icon
    :param app: the application
    """
    app.setStyle("Fusion")

    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(WINDOW))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor(FIELD))
    pal.setColor(QPalette.AlternateBase, QColor(CHARCOAL))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.PlaceholderText, QColor(TEXT_OFF))
    pal.setColor(QPalette.Button, QColor(FIELD))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.BrightText, QColor(AMBER))
    pal.setColor(QPalette.Highlight, QColor(AMBER))
    pal.setColor(QPalette.HighlightedText, QColor(CHARCOAL))
    pal.setColor(QPalette.ToolTipBase, QColor(CHARCOAL))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT))
    pal.setColor(QPalette.Link, QColor(AMBER))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(TEXT_OFF))
    app.setPalette(pal)

    app.setStyleSheet(STYLESHEET)
    if os.path.exists(ICON_PATH):
        app.setWindowIcon(QIcon(ICON_PATH))

class GenerateWorker(QThread):
    r"""
    Runs generation off the UI thread.
    """

    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, image_path: str, output_path: str, settings: LithophaneSettings):
        super().__init__()
        self._image_path = image_path
        self._output_path = output_path
        self._settings = settings

    def run(self) -> None:
        try:
            result = generate(
                self._image_path, self._output_path, self._settings, verbose=False
            )
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.finished_ok.emit(result)

class BusyBadge(QWidget):
    r"""
    App icon whose ring doubles as a progress spinner.
    """

    RING_RADIUS = 0.88
    RING_WIDTH = 0.20
    SWEEP_DEGREES = 95

    def __init__(self, size: int = 38, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._icon = QIcon(ICON_PATH) if os.path.exists(ICON_PATH) else None
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._advance)

    def start(self) -> None:
        if not self._timer.isActive():
            self._angle = 0
            self._timer.start()
            self.update()

    def stop(self) -> None:
        self._timer.stop()
        self.update()

    def is_busy(self) -> bool:
        return self._timer.isActive()

    def _advance(self) -> None:
        self._angle = (self._angle + 9) % 360
        self.update()

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self._icon is not None:
            painter.drawPixmap(self.rect(), self._icon.pixmap(self.size()))
        if not self._timer.isActive():
            return

        half = self.width() / 2.0
        radius = self.RING_RADIUS * half
        thickness = self.RING_WIDTH * half
        ring = QRectF(half - radius, half - radius, 2 * radius, 2 * radius)

        painter.setPen(QPen(QColor(AMBER_TRACK), thickness, Qt.SolidLine, Qt.FlatCap))
        painter.drawArc(ring, 0, 360 * 16)
        painter.setPen(QPen(QColor(AMBER), thickness, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(ring, int(-self._angle * 16), int(-self.SWEEP_DEGREES * 16))

class LightPad(QWidget):
    r"""
    Radar dial for the light's x/y position around the model.
    """

    moved = pyqtSignal(float, float)

    def __init__(self, diameter: int = 104, parent=None):
        super().__init__(parent)
        self.setFixedSize(diameter, diameter)
        self.setCursor(Qt.CrossCursor)
        self._x = 0.0
        self._y = 0.0
        self.setToolTip("Where the light sits relative to the print.\nDrag the blip; double-click to put it back dead centre.")

    def position(self) -> tuple[float, float]:
        return self._x, self._y

    def set_position(self, x: float, y: float) -> None:
        r"""
        Clamp to the dial, repaint and emit moved
        :param x: -1..1, right is positive
        :param y: -1..1, up is positive
        """
        length = (x * x + y * y) ** 0.5
        if length > 1.0:
            x, y = x / length, y / length
        if (x, y) != (self._x, self._y):
            self._x, self._y = x, y
            self.update()
            self.moved.emit(x, y)

    def _from_event(self, pos) -> None:
        radius = self.width() / 2.0 - 8
        self.set_position((pos.x() - self.width() / 2.0) / radius,-(pos.y() - self.height() / 2.0) / radius)

    def mousePressEvent(self, event):  # noqa: N802
        self._from_event(event.pos())

    def mouseMoveEvent(self, event):  # noqa: N802
        self._from_event(event.pos())

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        self.set_position(0.0, 0.0)

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        centre = QPointF(self.width() / 2.0, self.height() / 2.0)
        radius = self.width() / 2.0 - 8

        painter.setPen(QPen(QColor(LINE), 1))
        painter.setBrush(QColor(SUNKEN))
        painter.drawEllipse(centre, radius + 6, radius + 6)

        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(LINE), 1, Qt.DotLine))
        for fraction in (0.34, 0.67):
            painter.drawEllipse(centre, radius * fraction, radius * fraction)
        painter.drawLine(QPointF(centre.x() - radius, centre.y()), QPointF(centre.x() + radius, centre.y()))
        painter.drawLine(QPointF(centre.x(), centre.y() - radius), QPointF(centre.x(), centre.y() + radius),)

        blip = QPointF(centre.x() + self._x * radius, centre.y() - self._y * radius)
        painter.setPen(QPen(QColor(AMBER_PRESSED), 1))
        painter.drawLine(centre, blip)
        painter.setPen(QPen(QColor(CHARCOAL), 2))
        painter.setBrush(QColor(AMBER))
        painter.drawEllipse(blip, 6.5, 6.5)


def _spin(lo, hi, step, value, suffix="", decimals=2):
    r"""
    Double spin box with a capped width
    :param lo: minimum
    :param hi: maximum
    :param step: single step
    :param value: initial value
    :param suffix: unit suffix
    :param decimals: decimals shown
    :return: the spin box
    """
    box = QDoubleSpinBox()
    box.setRange(lo, hi)
    box.setSingleStep(step)
    box.setDecimals(decimals)
    box.setValue(value)
    box.setMaximumWidth(FIELD_WIDTH)
    if suffix:
        box.setSuffix(suffix)
    return box


class LithoGenWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LithoGen")
        self.setGeometry(100, 100, 1300, 800)

        self._image_path: str | None = None
        self._result = None
        self._worker: GenerateWorker | None = None
        self._preview_stl = os.path.join(tempfile.mkdtemp(prefix="lithogen-"), "preview.stl")
        self.actor = None
        self._model_centre = (0.0, 0.0, 0.0)
        self._light_reach = 200.0

        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(12, 12, 12, 12)
        body.setSpacing(12)
        root.addLayout(body)

        self.vtk_widget = QVTKRenderWindowInteractor(central)
        view_panel = QFrame()
        view_panel.setObjectName("viewpanel")
        stack = QVBoxLayout(view_panel)
        stack.setContentsMargins(10, 10, 10, 10)
        stack.setSpacing(10)

        controls = QWidget()
        controls.setObjectName("panelrow")
        controls_row = QHBoxLayout(controls)
        controls_row.setContentsMargins(4, 2, 4, 2)
        controls_row.setSpacing(14)
        controls_row.addWidget(self._build_light_section())

        divider = QFrame()
        divider.setObjectName("vseparator")
        divider.setFixedWidth(1)
        controls_row.addWidget(divider)

        controls_row.addWidget(self._build_preview_section())
        controls_row.addStretch(1)
        stack.addWidget(controls)

        separator = QFrame()
        separator.setObjectName("separator")
        separator.setFixedHeight(1)
        stack.addWidget(separator)

        stack.addWidget(self.vtk_widget, stretch=1)
        body.addWidget(view_panel, stretch=3)

        panel = QWidget()
        panel.setLayout(self._build_controls())
        scroll = QScrollArea()
        scroll.setWidget(panel)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMinimumWidth(450)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body.addWidget(scroll, stretch=1)

        self.renderer = vtk.vtkRenderer()
        self.renderer.SetBackground(*VIEWPORT_RGB)
        self.renderer.SetUseDepthPeeling(1)
        self.renderer.SetMaximumNumberOfPeels(4)
        self.renderer.SetOcclusionRatio(0.1)
        render_window = self.vtk_widget.GetRenderWindow()
        render_window.AddRenderer(self.renderer)
        self._enable_depth_peeling(render_window)
        self.interactor = self.vtk_widget.GetRenderWindow().GetInteractor()
        self._apply_interactor_style()
        self._add_lights()

        self.statusBar().showMessage("Open an image to start.")

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("header")
        row = QHBoxLayout(header)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(12)

        self.badge = BusyBadge(38)
        row.addWidget(self.badge)

        wordmark = QLabel("LithoGen")
        wordmark.setObjectName("wordmark")
        row.addWidget(wordmark)

        tagline = QLabel("images into printable lithophanes")
        tagline.setObjectName("tagline")
        row.addWidget(tagline)

        row.addStretch(1)
        self.image_label = QLabel("No image loaded")
        self.image_label.setObjectName("filename")
        row.addWidget(self.image_label)
        return header

    def _build_light_section(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("panelrow")
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(16)

        title = QLabel("LIGHT")
        title.setObjectName("lightTitle")
        title.setAlignment(Qt.AlignTop)
        row.addWidget(title)

        self.light_pad = LightPad()
        self.light_pad.moved.connect(self._on_light_moved)
        row.addWidget(self.light_pad)

        self.light_z = QSlider(Qt.Vertical)
        self.light_z.setRange(-100, 100)
        self.light_z.setValue(-100)
        self.light_z.setFixedHeight(104)
        self.light_z.setToolTip("Where the light sits through the plate.\nBottom is behind it, the way a lithophane is read; top moves it\nround to the front to look at the surface instead.")
        self.light_z.valueChanged.connect(lambda _v: self._update_light())

        z_column = QVBoxLayout()
        z_column.setSpacing(2)
        z_column.addWidget(QLabel("front"), alignment=Qt.AlignHCenter)
        z_column.addWidget(self.light_z, alignment=Qt.AlignHCenter)
        z_column.addWidget(QLabel("behind"), alignment=Qt.AlignHCenter)
        row.addLayout(z_column)

        self.light_readout = QLabel()
        self.light_readout.setObjectName("readout")
        self.light_readout.setAlignment(Qt.AlignTop)

        reset = QPushButton("Reset light")
        reset.clicked.connect(self._reset_light)
        reset.setMaximumWidth(110)

        info = QVBoxLayout()
        info.setSpacing(8)
        info.addWidget(self.light_readout)
        info.addWidget(reset)
        info.addStretch(1)
        row.addLayout(info)
        return bar

    def _build_preview_section(self) -> QWidget:
        box = QWidget()
        box.setObjectName("panelrow")
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)

        title = QLabel("PREVIEW")
        title.setObjectName("lightTitle")
        column.addWidget(title)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)

        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(5, 100)
        self.opacity.setValue(DEFAULT_OPACITY_PCT)
        self.opacity.setFixedWidth(96)
        self.opacity.setToolTip("How solid the model looks in the viewer.\nTurn it down to see the thickness through the plate, the way the\nlight will. This only affects the preview, never the exported mesh.")
        self.opacity_label = QLabel()
        self.opacity.valueChanged.connect(self._on_opacity_changed)
        opacity_row = QHBoxLayout()
        opacity_row.setSpacing(6)
        opacity_row.addWidget(self.opacity)
        opacity_row.addWidget(self.opacity_label)
        form.addRow("Opacity", opacity_row)

        self.rotation_mode = QComboBox()
        self.rotation_mode.setFixedWidth(FIELD_WIDTH)
        self.rotation_mode.addItems(["Click to spin", "Drag to turn"])
        self.rotation_mode.setToolTip("Click to spin: hold the button and the model keeps turning, faster\nthe further the pointer sits from the middle.\nDrag to turn: the model follows the mouse and stops when you do.")
        self.rotation_mode.currentIndexChanged.connect(self._apply_interactor_style)
        form.addRow("Rotation", self.rotation_mode)

        self.rotation_speed = _spin(0.1, 4.0, 0.1, 1.0, "x", 1)
        self.rotation_speed.setToolTip("How far the model turns for the same mouse movement.")
        self.rotation_speed.valueChanged.connect(self._apply_interactor_style)
        form.addRow("Sensitivity", self.rotation_speed)

        reset_view = QPushButton("Reset view")
        reset_view.setMaximumWidth(110)
        reset_view.setToolTip("Point the camera back at the front of the model.")
        reset_view.clicked.connect(self._reset_view)
        form.addRow("", reset_view)

        column.addLayout(form)
        column.addStretch(1)
        self._on_opacity_changed(self.opacity.value())
        return box

    def _reset_light(self) -> None:
        self.light_pad.set_position(0.0, 0.0)
        self.light_z.setValue(-100)
        self._update_light()

    def _on_light_moved(self, _x: float, _y: float) -> None:
        self._update_light()

    def _update_light(self) -> None:
        r"""
        Aim the key light at the model from the dial and height bar
        """
        x, y = self.light_pad.position()
        z = self.light_z.value() / 100.0

        length = (x * x + y * y + z * z) ** 0.5
        if length < 0.15:
            z = -0.15
            length = (x * x + y * y + z * z) ** 0.5

        cx, cy, cz = self._model_centre
        reach = self._light_reach / length
        self.key_light.SetFocalPoint(cx, cy, cz)
        self.key_light.SetPosition(cx + x * reach, cy + y * reach, cz + z * reach)

        side = "behind" if z < -0.05 else ("front" if z > 0.05 else "edge-on")
        self.light_readout.setText(f"x {x:+.2f}\ny {y:+.2f}\nz {z:+.2f}  {side}")
        if self.actor is not None:
            self.vtk_widget.GetRenderWindow().Render()

    def _build_controls(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(10)

        self.open_button = QPushButton("Open image...")
        self.open_button.clicked.connect(self.open_image)
        column.addWidget(self.open_button)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_lithophane_tab(), "Lithophane")
        self.tabs.addTab(self._build_logo_tab(), "Logo")
        self.tabs.currentChanged.connect(self._on_mode_changed)
        column.addWidget(self.tabs)

        self.generate_button = QPushButton("Generate preview")
        self.generate_button.setObjectName("primary")
        self.generate_button.clicked.connect(self.generate_preview)
        self.generate_button.setEnabled(False)
        column.addWidget(self.generate_button)

        self.save_button = QPushButton("Save as...")
        self.save_button.clicked.connect(self.save_as)
        self.save_button.setEnabled(False)
        column.addWidget(self.save_button)

        self.info_label = QLabel()
        self.info_label.setObjectName("summary")
        self.info_label.setWordWrap(True)
        self.info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.info_label.setVisible(False)
        column.addWidget(self.info_label)

        column.addStretch(1)
        return column

    def _build_lithophane_tab(self) -> QWidget:
        tab = QWidget()
        column = QVBoxLayout(tab)

        size_box = QGroupBox("Size")
        size_form = QFormLayout(size_box)
        self.longest = _spin(10, 500, 5, 100.0, " mm", 1)
        self.pitch = _spin(0.05, 1.0, 0.05, 0.2, " mm", 3)
        size_form.addRow("Longest side", self.longest)
        size_form.addRow("Sample pitch", self.pitch)
        column.addWidget(size_box)

        thick_box = QGroupBox("Thickness")
        thick_form = QFormLayout(thick_box)
        self.min_mm = _spin(0.1, 5.0, 0.1, 0.6, " mm")
        self.max_mm = _spin(0.5, 10.0, 0.1, 3.0, " mm")
        self.curve = QComboBox()
        self.curve.setMaximumWidth(FIELD_WIDTH)
        self.curve.addItems(CURVES)
        self.curve.setToolTip("beer: compensates for how light falls off exponentially through\nplastic, so mid-tones survive. linear: raw thickness ramp.")
        thick_form.addRow("Highlights (min)", self.min_mm)
        thick_form.addRow("Shadows (max)", self.max_mm)
        thick_form.addRow("Tone curve", self.curve)
        column.addWidget(thick_box)

        look_box = QGroupBox("Image")
        look_form = QFormLayout(look_box)
        self.sharpen = _spin(0.0, 2.0, 0.05, 0.35)
        self.smooth = _spin(0.0, 5.0, 0.1, 0.0)
        self.contrast = _spin(0.2, 3.0, 0.05, 1.0)
        self.autolevel = QCheckBox("Stretch histogram")
        self.autolevel.setChecked(True)
        self.invert = QCheckBox("Invert")
        self.mirror = QCheckBox("Mirror")
        look_form.addRow("Sharpen", self.sharpen)
        look_form.addRow("Smooth", self.smooth)
        look_form.addRow("Contrast", self.contrast)
        look_form.addRow(self.autolevel)
        look_form.addRow(self.invert)
        look_form.addRow(self.mirror)
        column.addWidget(look_box)

        geo_box = QGroupBox("Geometry")
        geo_form = QFormLayout(geo_box)
        self.border = _spin(0.0, 20.0, 0.5, 0.0, " mm", 1)
        self.curve_radius = _spin(0.0, 500.0, 5.0, 0.0, " mm", 1)
        self.curve_radius.setSpecialValueText("flat")
        self.back_segments = QSpinBox()
        self.back_segments.setMaximumWidth(FIELD_WIDTH)
        self.back_segments.setRange(0, 400)
        self.back_segments.setSpecialValueText("auto")
        self.back_segments.setToolTip(
            "How many flat strips make up the curved back.\n"
            "auto picks the fewest that keep the back within 0.05 mm of the\n"
            "bend - below what a printer resolves. Lower it for a smaller\n"
            "file, at the cost of a visibly faceted back."
        )
        geo_form.addRow("Border", self.border)
        geo_form.addRow("Bend radius", self.curve_radius)
        geo_form.addRow("Back strips", self.back_segments)
        column.addWidget(geo_box)

        self.curve_radius.valueChanged.connect(
            lambda v: self.back_segments.setEnabled(v > 0)
        )
        self.back_segments.setEnabled(False)

        column.addStretch(1)
        return tab

    def _build_logo_tab(self) -> QWidget:
        tab = QWidget()
        column = QVBoxLayout(tab)

        size_box = QGroupBox("Size")
        size_form = QFormLayout(size_box)
        self.logo_longest = _spin(10, 500, 5, 60.0, " mm", 1)
        self.logo_pitch = _spin(0.05, 1.0, 0.05, 0.2, " mm", 3)
        size_form.addRow("Longest side", self.logo_longest)
        size_form.addRow("Sample pitch", self.logo_pitch)
        column.addWidget(size_box)

        cut_box = QGroupBox("Cut-out")
        cut_form = QFormLayout(cut_box)
        self.bg_threshold = _spin(0.05, 1.0, 0.05, 0.9)
        self.bg_threshold.setToolTip(
            "Anything lighter than this is background and gets cut away.\n"
            "1.00 keeps everything but pure white. Transparent pixels count\n"
            "as white, so a cut-out PNG works without changing this."
        )

        self.bg_color_on = QCheckBox("Cut a colour instead")
        self.bg_color = QLineEdit("#ffffff")
        self.bg_color.setPlaceholderText("#rrggbb")
        self.bg_color.setMaximumWidth(90)
        self.bg_pick = QPushButton("Pick...")
        self.bg_pick.setMaximumWidth(60)
        self.bg_pick.clicked.connect(self._pick_background_color)
        self.bg_swatch = QFrame()
        self.bg_swatch.setFixedSize(22, 22)
        self.bg_color.textChanged.connect(self._sync_color_swatch)
        self.bg_tolerance = _spin(0.01, 1.0, 0.01, 0.12)
        self.bg_tolerance.setToolTip(
            "How far a pixel may sit from the chosen colour and still count as\n"
            "background. Raise it for gradients, JPEG mush or anti-aliased\n"
            "edges; lower it when the artwork is close to the background."
        )
        color_row = QHBoxLayout()
        color_row.setSpacing(6)
        color_row.addWidget(self.bg_swatch)
        color_row.addWidget(self.bg_color)
        color_row.addWidget(self.bg_pick)
        color_row.addStretch(1)
        self._sync_color_swatch(self.bg_color.text())

        for widget in (self.bg_color, self.bg_pick, self.bg_tolerance):
            widget.setEnabled(False)
        self.bg_color_on.toggled.connect(self.bg_color.setEnabled)
        self.bg_color_on.toggled.connect(self.bg_pick.setEnabled)
        self.bg_color_on.toggled.connect(self.bg_tolerance.setEnabled)
        self.bg_color_on.toggled.connect(lambda on: self.bg_threshold.setEnabled(not on))
        self.min_island = _spin(0.0, 50.0, 0.5, 1.0, " mm2", 1)
        self.min_island.setToolTip(
            "Drop kept specks smaller than this, so JPEG noise in the\n"
            "background does not print as confetti. 0 keeps everything."
        )
        cut_form.addRow("Background above", self.bg_threshold)
        cut_form.addRow(self.bg_color_on)
        cut_form.addRow("Colour", color_row)
        cut_form.addRow("Colour tolerance", self.bg_tolerance)
        cut_form.addRow("Drop specks under", self.min_island)
        column.addWidget(cut_box)

        shape_box = QGroupBox("Shape")
        shape_form = QFormLayout(shape_box)
        self.logo_thickness = _spin(0.4, 10.0, 0.2, 3.0, " mm")
        self.logo_relief = QCheckBox("Tone relief (backlit logo)")
        self.logo_relief.setToolTip(
            "Off: one flat height, the usual badge or keychain.\n"
            "On: the kept area keeps the lithophane's tone-to-thickness\n"
            "relief, for a logo meant to be lit from behind."
        )
        self.logo_min_mm = _spin(0.1, 5.0, 0.1, 0.6, " mm")
        self.logo_min_mm.setEnabled(False)
        self.logo_relief.toggled.connect(self.logo_min_mm.setEnabled)
        shape_form.addRow("Thickness", self.logo_thickness)
        shape_form.addRow(self.logo_relief)
        shape_form.addRow("Relief minimum", self.logo_min_mm)
        column.addWidget(shape_box)

        geo_box = QGroupBox("Geometry")
        geo_form = QFormLayout(geo_box)
        self.logo_curve_radius = _spin(0.0, 500.0, 5.0, 0.0, " mm", 1)
        self.logo_curve_radius.setSpecialValueText("flat")
        self.logo_mirror = QCheckBox("Mirror")
        geo_form.addRow("Bend radius", self.logo_curve_radius)
        geo_form.addRow(self.logo_mirror)
        column.addWidget(geo_box)

        column.addStretch(1)
        return tab

    def _sync_color_swatch(self, text: str) -> None:
        colour = QColor(text.strip())
        if colour.isValid():
            self.bg_swatch.setStyleSheet(
                f"background: {colour.name()}; border: 1px solid {LINE};"
                " border-radius: 4px;"
            )
        else:
            self.bg_swatch.setStyleSheet(
                f"background: {FIELD}; border: 1px dashed {AMBER_PRESSED};"
                " border-radius: 4px;"
            )

    def _pick_background_color(self) -> None:
        current = QColor(self.bg_color.text().strip() or "#ffffff")
        chosen = QColorDialog.getColor(
            current if current.isValid() else QColor("#ffffff"),
            self,
            "Background colour to cut away",
        )
        if chosen.isValid():
            self.bg_color.setText(chosen.name())

    def _on_mode_changed(self, _index: int) -> None:
        if self._image_path:
            self.generate_preview()

    def _apply_interactor_style(self, *_args) -> None:
        r"""
        Swap between trackball (drag to turn) and joystick (click to spin)
        """
        drag = self.rotation_mode.currentIndex() == 1
        speed = self.rotation_speed.value()

        if drag:
            style = vtk.vtkInteractorStyleTrackballCamera()
            style.SetMotionFactor(10.0 * speed)
            self.interactor.SetTimerDuration(10)
        else:
            style = vtk.vtkInteractorStyleJoystickCamera()
            self.interactor.SetTimerDuration(max(1, min(100, round(10 / speed))))
        self.interactor.SetInteractorStyle(style)

    def _reset_view(self) -> None:
        camera = self.renderer.GetActiveCamera()
        cx, cy, cz = self._model_centre
        camera.SetFocalPoint(cx, cy, cz)
        camera.SetPosition(cx, cy, cz + max(self._light_reach, 1.0))
        camera.SetViewUp(0.0, 1.0, 0.0)
        self.renderer.ResetCamera()
        self.renderer.ResetCameraClippingRange()
        self.vtk_widget.GetRenderWindow().Render()

    def _on_opacity_changed(self, value: int) -> None:
        self.opacity_label.setText(f"{value}%")
        self.opacity_label.setMinimumWidth(38)
        if self.actor is not None:
            self.actor.GetProperty().SetOpacity(value / 100.0)
            self.vtk_widget.GetRenderWindow().Render()

    def open_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open image", "", "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)"
        )
        if not path:
            return
        self._image_path = path
        self.image_label.setText(os.path.basename(path))
        self.generate_button.setEnabled(True)
        self.generate_preview()

    def current_settings(self) -> LithophaneSettings:
        if self.tabs.currentIndex() == 1:
            return self._logo_settings()
        return self._lithophane_settings()

    def _logo_settings(self) -> LithophaneSettings:
        radius = self.logo_curve_radius.value()
        relief = self.logo_relief.isChecked()
        return LithophaneSettings(
            pitch_mm=self.logo_pitch.value(),
            longest_mm=self.logo_longest.value(),
            max_mm=self.logo_thickness.value(),
            min_mm=self.logo_min_mm.value() if relief else self.logo_thickness.value() / 2,
            cutout=True,
            bg_threshold=self.bg_threshold.value(),
            bg_color=self.bg_color.text().strip() if self.bg_color_on.isChecked() else None,
            bg_tolerance=self.bg_tolerance.value(),
            relief=relief,
            min_island_mm2=self.min_island.value(),
            mirror=self.logo_mirror.isChecked(),
            curve_radius=radius if radius > 0 else None,
        )

    def _lithophane_settings(self) -> LithophaneSettings:
        radius = self.curve_radius.value()
        return LithophaneSettings(
            pitch_mm=self.pitch.value(),
            longest_mm=self.longest.value(),
            min_mm=self.min_mm.value(),
            max_mm=self.max_mm.value(),
            curve=self.curve.currentText(),
            autolevel=self.autolevel.isChecked(),
            contrast=self.contrast.value(),
            smooth_sigma=self.smooth.value(),
            sharpen=self.sharpen.value(),
            invert=self.invert.isChecked(),
            mirror=self.mirror.isChecked(),
            border_mm=self.border.value(),
            curve_radius=radius if radius > 0 else None,
            back_segments=self.back_segments.value() or None,
        )

    def generate_preview(self) -> None:
        if not self._image_path or (self._worker and self._worker.isRunning()):
            return
        settings = self.current_settings()
        try:
            settings.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "LithoGen", str(exc))
            return

        self.generate_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.statusBar().showMessage("Generating...")
        self.badge.start()
        QApplication.setOverrideCursor(Qt.WaitCursor)

        self._worker = GenerateWorker(self._image_path, self._preview_stl, settings)
        self._worker.finished_ok.connect(self._on_generated)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_generated(self, result) -> None:
        QApplication.restoreOverrideCursor()
        self.badge.stop()
        self._result = result
        self.generate_button.setEnabled(True)
        self.save_button.setEnabled(True)
        self.info_label.setText(result.summary())
        self.info_label.setVisible(True)
        self.statusBar().showMessage(
            f"{result.mesh.triangle_count():,} triangles in {result.elapsed_s:.2f} s"
        )
        self.display_stl(self._preview_stl)

    def _on_failed(self, message: str) -> None:
        QApplication.restoreOverrideCursor()
        self.badge.stop()
        self.generate_button.setEnabled(True)
        self.statusBar().showMessage("Generation failed.")
        QMessageBox.critical(self, "LithoGen", f"Generation failed:\n{message}")

    def save_as(self) -> None:
        if not self._result or not self._image_path:
            return
        suggested = os.path.splitext(os.path.basename(self._image_path))[0] + ".3mf"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save lithophane", suggested, "3MF (*.3mf);;STL (*.stl)"
        )
        if not path:
            return
        from lithogen import write_mesh

        try:
            write_mesh(self._result.mesh, path, name=os.path.basename(path))
        except Exception as exc:
            QMessageBox.critical(self, "LithoGen", f"Could not save:\n{exc}")
            return
        self.statusBar().showMessage(
            f"Saved {path} ({os.path.getsize(path) / 1e6:.2f} MB)"
        )

    def display_stl(self, file_path: str) -> None:
        r"""
        Load an STL into the viewer and frame it
        :param file_path: path to the STL
        """
        reader = vtk.vtkSTLReader()
        reader.SetFileName(file_path)

        normals = vtk.vtkPolyDataNormals()
        normals.SetInputConnection(reader.GetOutputPort())
        normals.ConsistencyOn()
        normals.SplittingOff()
        normals.Update()

        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(normals.GetOutputPort())

        self.actor = vtk.vtkActor()
        self.actor.SetMapper(mapper)
        prop = self.actor.GetProperty()
        prop.SetColor(*MODEL_RGB)
        prop.SetOpacity(self.opacity.value() / 100.0)
        prop.SetSpecular(0.25)
        prop.SetSpecularPower(20)

        bounds = self.actor.GetBounds()
        self._model_centre = (
            (bounds[0] + bounds[1]) / 2.0,
            (bounds[2] + bounds[3]) / 2.0,
            (bounds[4] + bounds[5]) / 2.0,
        )
        span = max(bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4])
        self._light_reach = 2.0 * (span or 100.0)

        self.renderer.RemoveAllViewProps()
        self.renderer.AddActor(self.actor)
        self.renderer.ResetCamera()
        self._update_light()
        self.vtk_widget.GetRenderWindow().Render()

    @staticmethod
    def _enable_depth_peeling(render_window) -> None:
        r"""
        Order-independent transparency; needs alpha bit planes and no multisampling
        :param render_window: the VTK render window
        """
        render_window.SetAlphaBitPlanes(1)
        render_window.SetMultiSamples(0)

    def _add_lights(self) -> None:
        self.key_light = vtk.vtkLight()
        self.key_light.SetLightTypeToSceneLight()
        self.key_light.SetIntensity(1.0)
        self.key_light.SetColor(*BACKLIGHT_RGB)
        self.renderer.AddLight(self.key_light)
        self._update_light()

        fill = vtk.vtkLight()
        fill.SetLightTypeToCameraLight()
        fill.SetPosition(0.4, 0.4, 1)
        fill.SetFocalPoint(0, 0, 0)
        fill.SetIntensity(0.35)
        self.renderer.AddLight(fill)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self.interactor.Initialize()

    def closeEvent(self, event):  # noqa: N802
        if self._worker and self._worker.isRunning():
            self._worker.wait(5000)
        self.vtk_widget.GetRenderWindow().Finalize()
        self.interactor.TerminateApp()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app)
    window = LithoGenWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())

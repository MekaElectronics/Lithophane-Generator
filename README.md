# Lithophane Generator 
## Project Overview 
This project is a Python-based lithophane generator that converts an image into a printable 3D model. The tone of each pixel sets the plate thickness at that point: highlights are thin and let the light through, shadows are thick and block it. It comes with a command line tool and a desktop GUI with a live 3D preview.
## Features
- Converts images into a thickness map and a watertight mesh, exported as STL or 3MF (3MF files are much smaller)
- Desktop GUI (`gui.py`) with a 3D preview, light position, opacity and rotation controls, and hover tooltips on the settings
- Physically based tone-to-thickness curves (`beer`, `linear`, `gamma`)
- Image tuning: smoothing, denoise, sharpen, contrast, brightness, gamma, auto-levelling, invert and mirror
- Plate width, height or longest side in mm, with adjustable sampling pitch
- Flat border for stiffness and framing
- Curved plates (`--curve-radius`) so the edges stay lit
- Cut-out mode for logos and keychains: removes the background so the outline follows the design
- Triangle budget that coarsens the pitch to keep the file size in check
- Manifold check on the exported mesh
- Support for many image formats (jpg, png, bmp, tiff, webp, ...)
## Installation
### Prerequisites
- Python 3.9 or newer (developed with Python 3.14.3).
- Required Python packages: `numpy`, `scipy`, `Pillow`
- Optional: `matplotlib` for `--preview`, `PyQt5` and `vtk` for the GUI
### Steps to Install 
1. Clone the repository: ```git clone git@github.com:MekaElectronics/Lithophane-Generator.git ```
2. Install the required dependencies: ```pip install numpy scipy Pillow```
3. Optional, for the preview and the GUI: ```pip install matplotlib PyQt5 vtk```
## Usage 
### Command line
1. Prepare an image to convert.
2. Run the Python script: ```python LithoGen.py input_image.jpg --options```
2.1. Use ```--help``` to further understand the options used by the tool.
3. The output will be saved as a 3D model (`Output.stl` by default). The extension of `-o` picks the format (`.stl` or `.3mf`).

Examples:
- 100 mm wide plate with the default settings: ```python LithoGen.py photo.jpg```
- 150 mm tall, finer sampling, 3MF output: ```python LithoGen.py photo.jpg -o photo.3mf --height 150 -p 0.15```
- Framed and gently curved: ```python LithoGen.py photo.jpg --border 3 --curve-radius 120```
- Logo keychain with the background cut away: ```python LithoGen.py logo.png --cutout -s 40 -M 3```

### GUI
Run ```python gui.py``` to open the desktop front end. Hover over a setting to see what it does.
## Customization You can adjust the following settings: 
- Pixel size (`-p`) and plate size (`-W`, `-H`, `-s`), in mm
- Thinnest and thickest point (`-m`, `-M`), in mm
- Tone curve (`-c`) and its parameters (`--mu`, `--curve-gamma`)
- Smoothing, de-noise, sharpen, contrast, brightness and gamma
- Border width and thickness, and the curve radius
- Cut-out background threshold, colour and tolerance
## Other informations
The [ReleaseNotes.html](ReleaseNotes.html) contains more info on the product's current version and the known issues.
The script is always under development and I hope it helps all 3D printing enthusiasts !

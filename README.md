# Lithophane Generator 
## Project Overview 
This project is a Python-based lithophane generator that converts images into grayscale and generates a 3D model where each pixel's intensity determines the height of a cube, which can be used for 3D printing. 
## Features
- Converts images into grayscale
- Generates 3D models (cube heights based on pixel intensity) -
- Adjustable resolution for output -
- Support for different image formats
## Installation
### Prerequisites
- Python 3.x
- Required Python packages (e.g., `numpy`, `Pillow`, `matplotlib`)
### Steps to Install 
1. Clone the repository: ```git clone git@github.com:MekaElectronics/Lithophane-Generator.git ```
2. Install the required dependencies: ```pip install matplotlib numpy numpy-stl scipy```
## Usage 
1. Prepare an image to convert.
2. Run the Python script: ```python LithoGen.py input_image.jpg --options```
2.1. Use ```--help``` to further understand the options used by the tool.
3. The output will be saved as a 3D model (`Output.stl`).
## Customization You can adjust the following settings: 
- Pixel size
- Cube height range (the height result will be in mm)
- Gaussian filter coefficient.
## Other informations
The [ReleaseNotes.html](ReleaseNotes.html) contains more info on the product's current version and the known issues.
The script is always under development and I hope it helps all 3D printing enthusiasts !

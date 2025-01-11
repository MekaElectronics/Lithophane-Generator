from matplotlib import pyplot as plt
import numpy as np
from stl import mesh
from scipy.ndimage import gaussian_filter as GaussianFilter
import argparse
import sys

def ShowProgress(Current,Total, length = 40):
    Percent = Current / Total
    arrow = '█' * int(Percent * length)
    space = ' ' * (length - len(arrow))
    sys.stdout.write(f'\r|{arrow}{space}| {Percent*100:.2f}%')
    sys.stdout.flush()

def GrayscaleConversion(InputImage):
    """ 
    The function responsible for the grayscale conversion (vectorial)
    """
    (Row,Col,Channels) = InputImage.shape
    Grayscale = np.zeros((Row,Col,1))
    Grayscale = InputImage[:,:,0]*0.299 + InputImage[:,:,1]*0.587 + InputImage[:,:,2]*0.114
    return Grayscale

def ResizeImage(InputImage,Size=None,Reform=False):
    """
    The pixel size needs to be different from 1 as when creating the lithophane, 1 will be considered as 1mm.
    """
    if Size == None:
        PixelSizes =[0.2,0.1,0.05,0.025,0.02,0.01]
        Col = InputImage.shape[1]
        for Size in PixelSizes:
            if 80 <= (Col * Size) <= 120:
                PixelSize = Size
            else :
                PixelSize = 0.01
    else :
        PixelSize = Size
    if not Reform:
        Factor = int((1/PixelSize)/2.5)
        InputImage = InputImage[::Factor, ::Factor]
    return Size, InputImage

def MapIntensityToHeight(PixelIntensity, MinValue=0.5, MaxValue=3):
    """
    When creating the lithophane, the height of the pixel will be responsible for the color shading.
    (Any value between 0(black) and 255(white) needs to be in millimeters)
    """
    MaxPixelIntensity = 255
    return MaxValue - (PixelIntensity / MaxPixelIntensity) * (MaxValue - MinValue)

def CombineCubesIntoSTL(Cubes,OutputFileName="Output.stl"):
    """
    After creating all the cubes with the correct heights and coordinates, group them into one STL file.
    """
    CombinedMesh = mesh.Mesh(np.concatenate([Cube.data for Cube in Cubes]))
    CombinedMesh.save(OutputFileName)

def MakeBase(ImageWidth,ImageHeight,PixelSize):
    """
    As all the cubes will share one base (a flat base) it should be created by itself to reduce resources
    and quicken the generation speed by reducing the creation of the cubes' bottoms.
    """
    vertices = np.array([
        [0, 0, 0],
        [ImageWidth*PixelSize, 0, 0],
        [ImageWidth*PixelSize, ImageHeight*PixelSize, 0],
        [0, ImageHeight*PixelSize, 0],
    ])
    Face = np.array([[0,1,3],[1,2,3],])
    BottomMesh = mesh.Mesh(np.zeros(Face.shape[0], dtype=mesh.Mesh.dtype))
    for i, Triangle in enumerate(Face):
        for j in range(3):
            BottomMesh.vectors[i][j] = vertices[Triangle[j], :]
    return BottomMesh

def MakePixel(PixelSize,PixelIntensity, PixelPosition):
    """
    This function will be responsible of creating each and every pixel with the correct positions.
    """
    x, y = PixelPosition
    # This array will contain the points. (corners of the cube which add up to 8 corners)
    vertices = np.array([
        # The cube (Pixel) bottom.
        [x, y, 0],
        [x+PixelSize, y, 0],
        [x+PixelSize, y+PixelSize, 0],
        [x, y+PixelSize, 0],
        # The cube (Pixel) top.
        [x, y, PixelIntensity],
        [x+PixelSize, y, PixelIntensity],
        [x+PixelSize, y+PixelSize, PixelIntensity],
        [x, y+PixelSize, PixelIntensity],
    ])
    # Each cube face is divided into two triangles, this will help to create the faces using the coordinates of three points.
    Faces = np.array([
        [0,1,3],[1,2,3],    # Bottom face
        [0,1,4],[1,5,4],    # Side face
        [1,2,5],[2,6,5],    # Side face
        [2,3,6],[3,7,6],    # Side face
        [0,3,4],[3,7,4],    # Side face
        [4,5,7],[5,6,7],    # Top face
    ])
    PixelMesh = mesh.Mesh(np.zeros(Faces.shape[0], dtype=mesh.Mesh.dtype))
    for i, Face in enumerate(Faces):
        for j in range(3):
            PixelMesh.vectors[i][j] = vertices[Face[j], :]
    return PixelMesh

def MakeSTL(ImageDir,Max=3.0,Min=0.5,PSize=0.2,Blur=5,Base=True):
    """ 
    Changing the colors of the image to be grayscale for a correct implementation
    """
    InpImage = plt.imread(ImageDir)
    # The channel number represents the 3 colors : R, G and B, in grayscale colors, only one channel exists so
    # its parameter might not exist.
    if len(InpImage.shape) < 3 :
        GrayImage = InpImage
        print("Already in grayscale !")
    else :
        GrayImage = GrayscaleConversion(InpImage)
        print("Converted to grayscale !")
    GrayImage = GaussianFilter(GrayImage,sigma = Blur)
    plt.imshow(GrayImage,cmap='gray')
    plt.axis("off")
    plt.show()
    #####################################################################################################
    # Need to scale the image to an appropriate size as the unit of measure in images is pixel          #
    # whereas when creating an STL file, the unit automatically becomes millimeter.                     #
    # In other words, an image with a resolution of 1920x1080 will be ~2 meters wide without scaling !  #
    #####################################################################################################

    PixelSize,GrayImage = ResizeImage(GrayImage,Size=PSize)
    print(GrayImage.shape)
    Cubes = []
    if (Base):
        Cubes.append(MakeBase(GrayImage.shape[0],GrayImage.shape[1],PixelSize))
    for i in range(GrayImage.shape[0]):
        for j in range (GrayImage.shape[1]):
            Intensity = MapIntensityToHeight(GrayImage[i,j],Min,Max)
            if (Intensity == 0):
                continue
            else :
                Cubes.append(MakePixel(PixelSize,Intensity,(i*PixelSize,j*PixelSize)))
        ShowProgress(i,GrayImage.shape[0],40)
    
    FinalProgress = '|'+'█'*40+'| 100%  '
    sys.stdout.write(f'\r{FinalProgress}\n')
    sys.stdout.flush()
    print('Saving File...')
    CombineCubesIntoSTL(Cubes)

Parser = argparse.ArgumentParser("Create a 3D image, or a lithophane, from a given 2D image.")
Parser.add_argument("PATH", type=str,help="The directory of the 2D image.")
Parser.add_argument("-p","--pixelsize",type=float,default=0.2,help="The generated lithophane's pixel size.")
Parser.add_argument("-M","--max",type=float,default=3,help="The generated lithophane's maximum height (Black color).")
Parser.add_argument("-m","--min",type=float,default=0.5,help="The generated lithophane's minimum height (White color).")
Parser.add_argument("-g","--gaussian",type=float,default=5,help="Add a gaussian filter effect to the image (Blur)")
Parser.add_argument("-n", "--no-base", action="store_false", default=True, help="Generate a lithophane without the bottom, ideal for making frames.")
Args = Parser.parse_args()

MakeSTL(Args.PATH,Args.max,Args.min,Args.pixelsize,Args.gaussian,Args.no_base)
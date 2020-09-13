from PIL import Image, ImageOps
from colorthief import ColorThief
import subprocess


def get_magick(image):
    """ Here I use a custom imagemagick script to get ten colors (check the
    scripts folder)"""
    image.save('/tmp/tmp_palette.png')
    output = subprocess.check_output(['paleta', '/tmp/tmp_palette.png']).decode()[:-1]
    colors = output.split("\n")
    return [tuple([int(i) for i in color.split(',')]) for color in colors]


# return frame + palette (PIL object)
def getPalette(img):
    width, height = img.size
    bgc = (255, 255, 255)

    try:
        palette = get_magick(img)
        if len(palette) < 10:
            return img
    except ValueError:
        color_thief = ColorThief(img)
        palette = color_thief.get_palette(color_count=11, quality=1)

    # calculate dimensions and generate the palette
    # get a nice-looking size for the palette based on aspect ratio
    divisor = (height / width) * 5.5
    heightPalette = int(height / divisor)
    divPalette = int(width / len(palette))
    offPalette = int(divPalette * 0.925)
    bg = Image.new('RGB', (width - int(offPalette * 0.2), heightPalette), bgc)

    # append colors
    next_ = 0
    for color in range(len(palette)):
        if color == 0:
            imgColor = Image.new('RGB', (int(divPalette * 0.925), heightPalette), palette[color])
            bg.paste(imgColor, (0, 0))
            next_ += divPalette
        else:
            imgColor = Image.new('RGB', (offPalette, heightPalette), palette[color])
            bg.paste(imgColor, (next_, 0))
            next_ += divPalette
    Paleta = bg.resize((width, heightPalette))

    # draw borders and append the palette
    Original = img

    borders = int(width * 0.0075)
    bordersT = (borders, borders, borders, heightPalette + borders)

    borderedOriginal = ImageOps.expand(Original, border=bordersT, fill=bgc)
    borderedPaleta = ImageOps.expand(Paleta, border=(0, borders), fill=bgc)

    borderedOriginal.paste(borderedPaleta, (borders, height))
    return borderedOriginal

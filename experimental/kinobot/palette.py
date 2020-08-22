import sys
from PIL import Image, ImageOps
from colorthief import ColorThief


# return frame + palette (PIL object)
def getPalette(file, width, height):
    bgc = (255, 255, 255)

    # get the colors with color thief
    color_thief = ColorThief(file)
    palette = color_thief.get_palette(color_count=11)
    if len(palette) < 10:
        sys.exit('Bad palette')

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
            #imgColor = Image.new('RGB', (int(divPalette * 0.9), heightPalette), palette[color])
            imgColor = Image.new('RGB', (int(divPalette * 0.925), heightPalette), palette[color])
            bg.paste(imgColor, (0, 0))
            next_ += divPalette
        else:
            imgColor = Image.new('RGB', (offPalette, heightPalette), palette[color])
            bg.paste(imgColor, (next_, 0))
            next_ += divPalette
    Paleta = bg.resize((width, heightPalette))

    # draw borders and append the palette
    Original = file

    borders = int(width * 0.0075)
    bordersT = (borders, borders, borders, heightPalette + borders)

    borderedOriginal = ImageOps.expand(Original, border=bordersT, fill=bgc)
    borderedPaleta = ImageOps.expand(Paleta, border=(0, borders), fill=bgc)

    borderedOriginal.paste(borderedPaleta, (borders, height))
    return borderedOriginal

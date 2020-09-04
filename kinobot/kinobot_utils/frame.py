import cv2
import json
import sys
import numpy as np

# for tests
try:
    from kinobot_utils.randomorg import getRandom
    from kinobot_utils.palette import getPalette
except ModuleNotFoundError:
    from randomorg import getRandom
    from palette import getPalette

from pymediainfo import MediaInfo
from PIL import Image, ImageChops, ImageStat


# remove black borders if present
def trim(im):
    bg = Image.new(im.mode, im.size, im.getpixel((0, 0)))
    diff = ImageChops.difference(im, bg)
    diff = ImageChops.add(diff, diff) # , 2.0, -100)
    bbox = diff.getbbox()
    if bbox:
        cropped = im.crop(bbox)
        return cropped


def get_v(imagen):
    hsv = ImageStat.Stat(imagen.convert('HSV'))
    hue = hsv.mean[2]
    saturation = hsv.mean[1]
    return (hue + saturation) / 2


def isBW(imagen):
    hsv = ImageStat.Stat(imagen.convert('HSV'))
    if hsv.mean[1] > 20.0:
        return False
    else:
        return True


def image_colorfulness(image):
    " Big thanks to Adrian Rosebrock for this amazing snippet "
    (B, G, R) = cv2.split(image.astype("float"))
    rg = np.absolute(R - G)
    yb = np.absolute(0.5 * (R + G) - B)
    (rbMean, rbStd) = (np.mean(rg), np.std(rg))
    (ybMean, ybStd) = (np.mean(yb), np.std(yb))
    stdRoot = np.sqrt((rbStd ** 2) + (ybStd ** 2))
    meanRoot = np.sqrt((rbMean ** 2) + (ybMean ** 2))
    return stdRoot + (0.3 * meanRoot)


def convert2Pil(c2vI):
    image = cv2.cvtColor(c2vI, cv2.COLOR_BGR2RGB)
    return Image.fromarray(image)


class Frame:
    def __init__(self, movie):
        self.movie = movie
        self.capture = cv2.VideoCapture(self.movie)
        self.maxFrame = int(self.capture.get(7))
        self.mean = int(self.maxFrame * 0.03)

        try:
            mi = MediaInfo.parse(self.movie, output="JSON")
            self.DAR = float(json.loads(mi)['media']['track'][1]['DisplayAspectRatio'])
        except KeyError:
            sys.exit('Mediainfo failed')

        self.Numbers = []
        for _ in range(20):
            self.Numbers.append(getRandom(self.mean, self.maxFrame - self.mean))

    # return image (pil object) and add frame info attributes
    def needed_fixes(self, frame):
        # fix width
        width, height, lay = frame.shape
        fixAspect = (self.DAR / (width / height))
        width = int(width * fixAspect)
        # resize with fixed width (cv2)
        resized = cv2.resize(frame, (width, height))
        # trim image if black borders are present. Convert to PIL first
        trimed = convert2Pil(resized)
        # return the pil image
        return trim(trimed)

    def getFrame(self):
        # check if b/w
        self.capture.set(1, self.Numbers[0])
        ret, frame = self.capture.read()
        if isBW(convert2Pil(frame)):
            self.image = self.needed_fixes(frame)
            self.selected_frame = self.Numbers[0]
        else:
            initial = 0
            Best = []
            Frames = []
            for fr in self.Numbers:
                self.capture.set(1, fr)
                ret, frame = self.capture.read()
#                amount = image_colorfulness(frame)
                amount = get_v(convert2Pil(frame))
                if amount > initial:
                    initial = amount
                    print('Score {}'.format(initial))
                    Frames.append(fr)
                    Best.append(frame)
            final_image = self.needed_fixes(Best[-1])
            self.image = getPalette(final_image)
            self.selected_frame = Frames[-1]

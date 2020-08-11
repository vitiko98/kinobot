import cv2
import json
import numpy
import sys

from pymediainfo import MediaInfo
from kinobot.randomorg import getRandom
from PIL import Image, ImageChops


# remove black borders if present
def trim(im):
    bg = Image.new(im.mode, im.size, im.getpixel((0, 0)))
    diff = ImageChops.difference(im, bg)
    diff = ImageChops.add(diff, diff) # , 2.0, -100)
    bbox = diff.getbbox()
    if bbox:
        cropped = im.crop(bbox)
        cv2_obj = cv2.cvtColor(numpy.array(cropped), cv2.COLOR_RGB2BGR)
        return cv2_obj, cropped


def convert2Pil(c2vI):
    image = cv2.cvtColor(c2vI, cv2.COLOR_BGR2RGB)
    return Image.fromarray(image)


class Frame:
    def __init__(self, movie):
        self.movie = movie
        self.capture = cv2.VideoCapture(self.movie)
        self.maxFrame = int(self.capture.get(7))
        self.mean = int(self.maxFrame * 0.03)
        self.selectedFrame = getRandom(self.mean, self.maxFrame - self.mean)

    # return image (pil object) and add frame info attributes
    def getFrame(self):
        self.capture.set(1, self.selectedFrame)
        ret, frame = self.capture.read()

        # check DAR to fix aspect ratio on DVD sources
        try:
            mi = MediaInfo.parse(self.movie, output="JSON")
            DAR = float(json.loads(mi)['media']['track'][1]['DisplayAspectRatio'])
        except KeyError:
            sys.exit('Mediainfo failed')
        # fix width
        width, self.height, lay = frame.shape
        fixAspect = (DAR / (width / self.height))
        self.width = int(width * fixAspect)
        # resize with fixed width (cv2)
        resized = cv2.resize(frame, (self.width, self.height))
        # trim image if black borders are present. Convert to PIL first
        trimed = convert2Pil(resized)
        # get cv2 object to extract dimensions
        trimed, pil_image = trim(trimed)
        self.height, self.width, lay = trimed.shape
        return pil_image

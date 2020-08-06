import cv2
import json
import requests
from pymediainfo import MediaInfo
from kinobot.randomorg import getRandom
from PIL import Image, ImageStat, ImageChops
import sys

# remove black borders if present
def trim(im):
    bg = Image.new(im.mode, im.size, im.getpixel((0,0)))
    diff = ImageChops.difference(im, bg)
    diff = ImageChops.add(diff, diff)#, 2.0, -100)
    bbox = diff.getbbox()
    if bbox:
        return im.crop(bbox)

def convert2Pil(c2vI):
    image = cv2.cvtColor(c2vI, cv2.COLOR_BGR2RGB)
    return Image.fromarray(image)

class Frame:
    def __init__(self, movie):
        self.movie = movie
        self.capture = cv2.VideoCapture(self.movie)
        self.maxFrame = int(self.capture.get(7)) - 5000
        self.selectedFrame = getRandom(5000, self.maxFrame)

    # return image (pil object) and add frame info attributes
    def getFrame(self):
        self.capture.set(1, self.selectedFrame)
        ret, frame = self.capture.read()

        # check DAR to fix aspect ratio on DVD sources
        try:
            mi = MediaInfo.parse(self.movie, output="JSON")
            DAR = float(json.loads(mi)['media']['track'][1]['DisplayAspectRatio'])
        except:
            print('Mediainfo failed')
            sys.exit()
        # fix width
        width, self.height, lay = frame.shape
        fixAspect = (DAR / (width / self.height))
        self.width = int(width * fixAspect)
        resized = cv2.resize(frame, (self.width, self.height))

        return trim(convert2Pil(resized))

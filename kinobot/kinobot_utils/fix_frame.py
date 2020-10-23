import json
import logging
import subprocess

import cv2
from PIL import Image, ImageChops, ImageStat
from pymediainfo import MediaInfo

logger = logging.getLogger(__name__)


# remove black borders if present
def trim(im):
    bg = Image.new(im.mode, im.size, im.getpixel((0, 0)))
    diff = ImageChops.difference(im, bg)
    diff = ImageChops.add(diff, diff)  # , 2.0, -100)
    bbox = diff.getbbox()
    if bbox:
        cropped = im.crop(bbox)
        return cropped


def convert2Pil(c2vI):
    image = cv2.cvtColor(c2vI, cv2.COLOR_BGR2RGB)
    return Image.fromarray(image)


def get_dar(file):
    command = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        file,
    ]
    result = subprocess.run(command, stdout=subprocess.PIPE)
    return json.loads(result.stdout)["streams"][0]["display_aspect_ratio"].split(":")


def isBW(imagen):
    hsv = ImageStat.Stat(imagen.convert("HSV"))
    return hsv.mean[1]


def needed_fixes(file, frame, check_palette=True):
    logger.info("Checking DAR")
    try:
        logger.info("Using ffprobe")
        f, s = get_dar(file)
        DAR = float(f) / float(s)
    except:
        logger.error("ffprobe failed")
        logger.info("Using mediainfo. This will take a while")
        mi = MediaInfo.parse(file, output="JSON")
        DAR = float(json.loads(mi)["media"]["track"][1]["DisplayAspectRatio"])
    logger.info("Extracted display aspect ratio: {}".format(DAR))
    # fix width
    width, height, lay = frame.shape
    logger.info("Original dimensions: {}*{}".format(width, height))
    fixAspect = DAR / (width / height)
    width = int(width * fixAspect)
    # resize with fixed width (cv2)
    logger.info("Fixed dimensions: {}*{}".format(width, height))
    resized = cv2.resize(frame, (width, height))
    # trim image if black borders are present. Convert to PIL first
    trimed = convert2Pil(resized)
    # return the pil image
    if check_palette:
        if isBW(trimed) > 35:
            return trim(trimed), True
        else:
            return trim(trimed), False
    return trim(trimed)

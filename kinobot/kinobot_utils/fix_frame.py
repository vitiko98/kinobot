import cv2
import json
import numpy as np
import subprocess

from pymediainfo import MediaInfo
from PIL import Image, ImageChops


# remove black borders if present
def trim(im):
    bg = Image.new(im.mode, im.size, im.getpixel((0, 0)))
    diff = ImageChops.difference(im, bg)
    diff = ImageChops.add(diff, diff) # , 2.0, -100)
    bbox = diff.getbbox()
    if bbox:
        cropped = im.crop(bbox)
        return cropped


def convert2Pil(c2vI):
    image = cv2.cvtColor(c2vI, cv2.COLOR_BGR2RGB)
    return Image.fromarray(image)


def get_dar(file):
    command = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', file]
    result = subprocess.run(command, stdout=subprocess.PIPE)
    return json.loads(result.stdout)['streams'][0]['display_aspect_ratio'].split(":")


def image_colorfulness(image):
    " Big thanks to Adrian Rosebrock for this snippet "
    (B, G, R) = cv2.split(image.astype("float"))
    rg = np.absolute(R - G)
    yb = np.absolute(0.5 * (R + G) - B)
    (rbMean, rbStd) = (np.mean(rg), np.std(rg))
    (ybMean, ybStd) = (np.mean(yb), np.std(yb))
    stdRoot = np.sqrt((rbStd ** 2) + (ybStd ** 2))
    meanRoot = np.sqrt((rbMean ** 2) + (ybMean ** 2))
    print(stdRoot + (0.3 * meanRoot))
    return stdRoot + (0.3 * meanRoot)


def needed_fixes(file, frame, check_palette=True):
    print('Checking DAR. This may take a while...')
    try:
        f, s = get_dar(file)
        DAR = float(f) / float(s)
    except:
        print('Mediainfo!')
        mi = MediaInfo.parse(file, output="JSON")
        DAR = float(json.loads(mi)['media']['track'][1]['DisplayAspectRatio'])
    print('Ok')
    # fix width
    width, height, lay = frame.shape
    fixAspect = (DAR / (width / height))
    width = int(width * fixAspect)
    # resize with fixed width (cv2)
    resized = cv2.resize(frame, (width, height))
    # trim image if black borders are present. Convert to PIL first
    trimed = convert2Pil(resized)
    # return the pil image
    if check_palette:
        if image_colorfulness(frame) > 35:
            return trim(trimed), True
        else:
            return trim(trimed), False
    return trim(trimed)

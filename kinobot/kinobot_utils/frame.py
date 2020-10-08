import cv2
from PIL import Image, ImageStat

# for tests
try:
    from kinobot_utils.fix_frame import needed_fixes
    from kinobot_utils.palette import getPalette
    from kinobot_utils.randomorg import getRandom
except ModuleNotFoundError:
    from fix_frame import needed_fixes
    from palette import getPalette
    from randomorg import getRandom


def get_v(imagen):
    hsv = ImageStat.Stat(imagen.convert("HSV"))
    hue = hsv.mean[2]
    saturation = hsv.mean[1]
    return (hue + saturation) / 2


def isBW(imagen):
    hsv = ImageStat.Stat(imagen.convert("HSV"))
    if hsv.mean[1] > 25.0:
        return False
    else:
        return True


def convert2Pil(c2vI):
    image = cv2.cvtColor(c2vI, cv2.COLOR_BGR2RGB)
    return Image.fromarray(image)


class Frame:
    def __init__(self, movie):
        self.movie = movie
        self.capture = cv2.VideoCapture(self.movie)
        self.maxFrame = int(self.capture.get(7))
        self.mean = int(self.maxFrame * 0.03)
        self.Numbers = []
        for _ in range(2):
            self.Numbers.append(getRandom(self.mean, self.maxFrame - self.mean))

    def getFrame(self):
        # check if b/w
        self.capture.set(1, self.Numbers[0])
        ret, frame = self.capture.read()
        if isBW(convert2Pil(frame)):
            self.image = needed_fixes(self.movie, frame, False)
            self.selected_frame = self.Numbers[0]
        else:
            initial = 0
            Best = []
            Frames = []
            for fr in self.Numbers:
                self.capture.set(1, fr)
                ret, frame = self.capture.read()
                amount = get_v(convert2Pil(frame))
                if amount > initial:
                    initial = amount
                    print("Score {}".format(initial))
                    Frames.append(fr)
                    Best.append(frame)
            final_image = needed_fixes(self.movie, Best[-1], False)
            self.image = getPalette(final_image)
            self.selected_frame = Frames[-1]

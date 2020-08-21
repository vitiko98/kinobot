import cv2
import re

from PIL import Image, ImageFont, ImageDraw


def cleansub(text):
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', text)
    return cleantext


def convert2Pil(c2vI, width, height, hq=False):
    image = cv2.cvtColor(c2vI, cv2.COLOR_BGR2RGB)
    to_resize = Image.fromarray(image)
    if not hq:
        return to_resize.resize((int(width * 0.5), int(height * 0.5)))
    else:
        return to_resize


def get_gif(file, second, hq=True):
    capture = cv2.VideoCapture(file)
    fps = capture.get(cv2.CAP_PROP_FPS)
    frame_start = int(fps * second)
    frame_stop = int(fps * 3) + frame_start

    cv2s = []
    for i in range(frame_start, frame_stop, 3):
        capture.set(1, i)
        ret, frame = capture.read()
        cv2s.append(frame)
    height, width, lay = cv2s[0].shape

    pils = []
    for i in cv2s:
        pils.append(convert2Pil(i, width, height, hq=hq))
    return pils


# draw subtitles to frame
def get_subtitles(img, title):
    title = cleansub(title)
    draw = ImageDraw.Draw(img)
    w, h = img.size
    font = ImageFont.truetype("AlteHaasGroteskRegular.ttf", int(w * 0.033))
    off = w * 0.067
    txt_w, txt_h = draw.textsize(title, font)
    draw.text(((w - txt_w) / 2, h - txt_h - off), title,
              "white", font=font, align="center")
    return img


def sub_iterator(pils, content, sub_start, sub_end):
    lenght = len(pils) / 3
    sub_range = int((sub_end - sub_start) * lenght)
    new_pils = []
    try:
        for i in range(sub_range):
            new_pils.append(get_subtitles(pils[i], content['message']))
        for d in range(sub_range, len(pils)):
            new_pils.append(pils[d])
    except IndexError:
        pass
    return new_pils


def main(file, second=None, subtitle=None, gif=False):
    if gif:
        if subtitle and not second:
            pils = get_gif(file, subtitle['start'], hq=True)
            new_pils = sub_iterator(pils, subtitle,
                                    subtitle['start'], subtitle['end'])
        else:
            new_pils = get_gif(file, int(second), hq=True)
    else:
        if subtitle:
            pils = get_gif(file, subtitle['start'], hq=True)[0]
            new_pils = get_subtitles(pils, subtitle['message'])
        else:
            new_pils = get_gif(file, int(second), hq=True)[0]
    return new_pils
    # use imageio if list
    # imageio.mimsave('whatever.gif', list)

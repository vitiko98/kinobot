import requests
import random
import json

from PIL import Image, ImageOps, ImageFont, ImageDraw

FONT = "NotoSansCJK-Regular.ttc"


def get_dominant_colors(collage):
    two_colors = collage.quantize(colors=2)
    pal = two_colors.getpalette()[:6]
    return tuple(pal[:3]), tuple(pal[3:])


def get_image(url):
    r = requests.get(url, stream=True)
    r.raw.decode_content = True
    return Image.open(r.raw)


def get_collage(images):
    w, h = images[0].size
    new_images = [im.resize((w, h)) for im in images]
    collage_width = 3 * w
    collage_height = 2 * h
    new_image = Image.new("RGB", (collage_width, collage_height))
    cursor = (0, 0)
    for image in new_images:
        new_image.paste(image, cursor)
        y = cursor[1]
        x = cursor[0] + w
        if cursor[0] >= (collage_width - w):
            y = cursor[1] + h
            x = 0
        cursor = (x, y)
    return new_image.resize((1200, 1200))


def decorate_info(image, head, footnote, fg, new_w, new_h):
    h, w = image.size
    font = ImageFont.truetype(FONT, 37)
    font_foot = ImageFont.truetype(FONT, 33)
    draw = ImageDraw.Draw(image)
    text_h, text_w = draw.textsize(head, font)
    draw.text((int(new_h * 1.75), 39), head, fill=fg, font=font)
    draw.text(
        (int(new_h * 1.75), w - 98), footnote, fill=fg, font=font_foot
    )
    return image


def get_rec(json_path):
    with open(json_path) as f:
        dictionary = json.load(f)
        pick_four = random.sample(dictionary, 6)
        images = [get_image(im['poster']) for im in pick_four]
        " collage stuff "
        final = get_collage(images)
        w, h = final.size
        fg, bg = get_dominant_colors(final)
        decorators = ['The Certified Kino Bot Collection', 'kino.caretas.club']
        new_w = int(h * 0.23)
        new_h = 50
        collage = ImageOps.expand(final, border=(new_h, int(new_w / 2)), fill=bg)
        return decorate_info(collage, decorators[0], decorators[1], fg, new_w, new_h)

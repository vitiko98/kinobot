from PIL import Image, ImageOps, ImageFont, ImageDraw

FONT = "NotoSansCJK-Regular.ttc"


def prettify_list(Items):
    text_list = []
    for i, n in zip(Items, range(len(Items))):
        text_list.append('{}. {} ({})'.format(n, i['title'], i['year']))
    longest = max([len(i) for i in text_list])
    return "\n".join(text_list), longest


def get_dominant_colors(collage):
    two_colors = collage.quantize(colors=2)
    pal = two_colors.getpalette()[:6]
    return tuple(pal[:3]), tuple(pal[3:])


def get_collage_w_text(collage, w, h, new_h, new_w, fg, bg, text, text_length):
    new_image = Image.new("RGB", (h + int(text_length * (h * 0.01)), w + new_w), bg)
    new_image.paste(collage, (0, int(new_w / 2)))
    draw = ImageDraw.Draw(new_image)
    font = ImageFont.truetype(FONT, 23)
    draw.text((h + int(new_h / 2), int(new_w * 0.6)), text, fill=fg, spacing=1, font=font)
    return ImageOps.expand(new_image, border=(new_h, 0, new_h, 0), fill=bg)

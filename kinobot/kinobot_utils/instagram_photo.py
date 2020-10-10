from PIL import Image
import kinobot_utils.random_picks as random_picks


def square(im, min_size=200, fill_color=(0, 0, 0)):
    x, y = im.size
    size = max(min_size, x, y)
    new_im = Image.new("RGB", (size, size), fill_color)
    new_im.paste(im, (int((size - x) / 2), int((size - y) / 2)))
    resized = new_im.resize((1000, 1000))
    return resized


def get_photo(image):
    fg, bg = random_picks.get_dominant_colors(image)
    return square(image, min_size=200, fill_color=bg)

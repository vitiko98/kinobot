import io

from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont
import wand.image


def draw_pixel_grid(image):
    draw = ImageDraw.Draw(image)

    grid_color = "white"  # (255, 0, 0)
    grid_thickness = 1
    font_size = 30
    font = ImageFont.truetype("fonts/Arial.ttf", font_size)

    width, height = image.size

    x_interval = width // 15
    y_interval = height // 15

    for x in range(0, width, x_interval):
        draw.line([(x, 0), (x, height)], fill=grid_color, width=grid_thickness)
        draw.text((x + 2, 2), str(x), fill=grid_color, font=font)

    for y in range(0, height, y_interval):
        draw.line([(0, y), (width, y)], fill=grid_color, width=grid_thickness)
        draw.text((2, y + 2), str(y), fill=grid_color, font=font)

    return image


def get_colors(image, colors=10, dither="floyd_steinberg"):
    with io.BytesIO() as output:
        image.save(output, format="png")
        image_blob = output.getvalue()

    with wand.image.Image(blob=image_blob) as img:
        img.quantize(colors, colorspace_type=None, dither=dither)  # type: ignore
        img.unique_colors()

        with Image.open(io.BytesIO(img.make_blob("png"))).convert("RGB") as pil_img:  # type: ignore
            color_list = list(pil_img.getdata())

    return color_list


def create_palette_image(dominant_colors, palette_size=(100, 100)):
    num_colors = len(dominant_colors)
    palette_width, palette_height = palette_size

    # Create the color palette image
    palette_image = Image.new("RGB", (palette_width * num_colors, palette_height))

    draw = ImageDraw.Draw(palette_image)

    for i, color in enumerate(dominant_colors):
        draw.rectangle(
            [i * palette_width, 0, (i + 1) * palette_width, palette_height],
            fill=tuple(color),
        )

    return palette_image

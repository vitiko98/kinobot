import logging
from typing import Union

from PIL import Image

logger = logging.getLogger(__name__)


class Watermark:
    def __init__(self, watermark: str, image_size=5, x_y=(2, 3), put_alpha=120) -> None:
        self._watermark = watermark
        self._x_y = x_y
        self._put_alpha = put_alpha
        self._image_size = image_size

    def draw(self, path: str):
        image = Image.open(path)
        # image = image.convert("RGBA")

        max_size = int(
            max(
                image.width * (self._image_size / 100),
                image.height * (self._image_size / 100),
            )
        )
        logger.debug("Max size: %s", max_size)
        watermark = Image.open(self._watermark)
        watermark = watermark.convert("RGBA")

        watermark.thumbnail((max_size, max_size))

        # if max(watermark.size) > max_size:
        #    if watermark.width > watermark.height:
        #        new_size = max_size, watermark.height / (watermark.height / max_size)
        #    else:
        #        new_size = watermark.width / (watermark.width / max_size), max_size
        #
        #    watermark = watermark.resize((int(i) for i in new_size))  # type: ignore
        #    logger.debug("Resized: %s", new_size)

        # watermark.putalpha(50)

        x_y = int((self._x_y[0] / 100) * image.size[0]), int(
            (self._x_y[1] / 100) * image.size[1]
        )
        try:
            image.paste(watermark, x_y, watermark)
        except ValueError as error:
            logger.error("%s. Falling back to error to None mask", error)
            image.paste(watermark, x_y)

        return image

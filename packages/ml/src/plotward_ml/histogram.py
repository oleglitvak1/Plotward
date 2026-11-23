import io
import math

import pillow_heif
from PIL import Image, ImageOps

pillow_heif.register_heif_opener()


class ColorHistogramEmbedder:
    """A 512-bin RGB color histogram (8 bins per channel), L2-normalized.

    Not a real vision model: it only knows color. It exists so tests and local runs work
    without PyTorch, with the same dimension as the real model. Images of the same color
    are identical to it; different colors are orthogonal.
    """

    name = "color-histogram"
    version = "1"
    dim = 512

    def embed(self, data: bytes) -> list[float]:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
        image.thumbnail((64, 64))
        counts = [0.0] * self.dim
        for r, g, b in image.getdata():
            counts[(r >> 5) * 64 + (g >> 5) * 8 + (b >> 5)] += 1.0
        norm = math.sqrt(sum(c * c for c in counts)) or 1.0
        return [c / norm for c in counts]

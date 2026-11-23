import io
import math

import pytest
from PIL import Image
from plotward_ml import ColorHistogramEmbedder, create_embedder


def _png(color, size=(64, 48)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_vectors_have_the_declared_dimension_and_unit_length():
    e = ColorHistogramEmbedder()
    v = e.embed(_png((10, 200, 30)))
    assert len(v) == e.dim == 512
    assert math.sqrt(_dot(v, v)) == pytest.approx(1.0)


def test_same_color_is_identical_and_different_colors_are_orthogonal():
    e = ColorHistogramEmbedder()
    green, green_bigger, red = (
        e.embed(_png((10, 200, 30))),
        e.embed(_png((10, 200, 30), size=(300, 200))),
        e.embed(_png((220, 10, 10))),
    )
    assert _dot(green, green_bigger) == pytest.approx(1.0)
    assert _dot(green, red) == pytest.approx(0.0)


def test_factory_builds_the_histogram_embedder_and_rejects_unknown_kinds():
    assert isinstance(create_embedder("histogram"), ColorHistogramEmbedder)
    with pytest.raises(ValueError):
        create_embedder("nope")

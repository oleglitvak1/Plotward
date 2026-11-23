"""The ML boundary: image bytes in, unit-length vector out. Callers never see the model."""

from .base import Embedder, create_embedder
from .histogram import ColorHistogramEmbedder

__all__ = ["ColorHistogramEmbedder", "Embedder", "create_embedder"]

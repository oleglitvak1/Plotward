from typing import Protocol


class Embedder(Protocol):
    """Turns an image into a unit-length vector. `name` and `version` are stored with every
    vector, because vectors from different models cannot be compared."""

    name: str
    version: str
    dim: int

    def embed(self, data: bytes) -> list[float]: ...


def create_embedder(
    kind: str, *, model: str = "ViT-B-32", pretrained: str = "laion2b_s34b_b79k"
) -> Embedder:
    if kind == "open_clip":
        from .open_clip_embedder import OpenClipEmbedder  # imports torch; keep it lazy

        return OpenClipEmbedder(model, pretrained)
    if kind == "histogram":
        from .histogram import ColorHistogramEmbedder

        return ColorHistogramEmbedder()
    raise ValueError(f"unknown embedder {kind!r}; use 'open_clip' or 'histogram'")

import io

import pillow_heif
from PIL import Image, ImageOps

pillow_heif.register_heif_opener()


class OpenClipEmbedder:
    """CLIP image embeddings on CPU via open_clip. Weights download from Hugging Face on first
    use and are cached under HF_HOME."""

    def __init__(self, model: str = "ViT-B-32", pretrained: str = "laion2b_s34b_b79k"):
        import open_clip
        import torch

        self._torch = torch
        self._model, _, self._preprocess = open_clip.create_model_and_transforms(
            model, pretrained=pretrained, device="cpu"
        )
        self._model.eval()
        self.name = f"open_clip/{model}"
        self.version = pretrained
        self.dim = int(self._model.visual.output_dim)

    def embed(self, data: bytes) -> list[float]:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
        batch = self._preprocess(image).unsqueeze(0)
        with self._torch.no_grad():
            features = self._model.encode_image(batch)
            features = features / features.norm(dim=-1, keepdim=True)
        return features[0].tolist()

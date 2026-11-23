from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PLOTWARD_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://plotward:plotward@localhost:5432/plotward"
    data_dir: Path = Path("./data")
    api_key: str = ""
    max_upload_mb: int = 50
    garden_name: str = "My garden"
    garden_timezone: str = "America/Los_Angeles"

    # Embeddings (worker). Changing the model needs a migration if the dimension changes.
    embedder: str = "open_clip"  # or "histogram" for a dependency-free stand-in
    open_clip_model: str = "ViT-B-32"
    open_clip_pretrained: str = "laion2b_s34b_b79k"

    # Plant matching. Starting guesses, deliberately conservative: a wrong match silently
    # corrupts a plant's history, while a missed match only costs one extra question. Real CLIP
    # similarities are compressed (even unrelated images score ~0.8-0.9), so low bars match
    # almost anything. Tune with `python -m plotward_worker.report` once you have real photos.
    match_radius_m: float = 15.0  # GPS search radius; phone GPS is good to roughly 3-10 m
    match_min_similarity_near: float = 0.85  # cosine similarity needed when GPS agrees
    match_min_similarity_far: float = 0.93  # stricter when there is no GPS to back it up
    match_margin: float = 0.03  # best candidate must beat the runner-up by this much
    match_recent_photos: int = 5  # compare against each plant's latest N photos
    group_window_s: int = 60  # photos this close in time ...
    group_radius_m: float = 5.0  # ... and space are treated as one pass past the same plant

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()

import os
import tempfile
from pathlib import Path


class PhotoStore:
    """Content-addressed files on local disk: photos/<garden>/<hash[:2]>/<hash>/<name>."""

    def __init__(self, root: Path):
        self.root = root

    def key(self, garden_id: object, content_hash: str, name: str) -> str:
        return f"photos/{garden_id}/{content_hash[:2]}/{content_hash}/{name}"

    def write(self, key: str, data: bytes) -> None:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write then rename so a crash never leaves a half-written file under the final name.
        fd, tmp = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def read(self, key: str) -> bytes:
        return (self.root / key).read_bytes()

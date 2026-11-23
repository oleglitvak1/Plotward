"""Matching report: how photos were matched, and how similar photos look within and across
plants. Use it to choose the thresholds in `Settings` from your own photos.

    python -m plotward_worker.report
"""

import statistics
from collections import Counter
from itertools import combinations

from plotward_core.config import Settings, get_settings
from plotward_core.db import ensure_default_garden, garden_session, make_session_factory
from plotward_core.matching import cosine
from plotward_core.models import Photo, Plant
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

MAX_PHOTOS = 400  # pairwise comparison is quadratic


def _summary(values: list[float]) -> str:
    if not values:
        return "n/a"
    qs = statistics.quantiles(values, n=20) if len(values) > 1 else [values[0]] * 19
    return (
        f"n={len(values)} min={min(values):.3f} p5={qs[0]:.3f} "
        f"median={statistics.median(values):.3f} p95={qs[-1]:.3f} max={max(values):.3f}"
    )


def build_report(session: Session, settings: Settings) -> str:
    photos = list(session.scalars(select(Photo).order_by(Photo.received_at)))
    plants = list(session.scalars(select(Plant)))
    lines = [
        f"{len(photos)} photos, {len(plants)} plants "
        f"({sum(p.status == 'draft' for p in plants)} draft)"
    ]

    methods = Counter(p.match_method or "unmatched" for p in photos)
    lines.append("Matched by: " + ", ".join(f"{k}={v}" for k, v in sorted(methods.items())))
    scores = [p.match_score for p in photos if p.match_score is not None]
    lines.append("Match scores: " + _summary(scores))

    embedded = [p for p in photos if p.embedding is not None and p.plant_id is not None]
    if len(embedded) > MAX_PHOTOS:
        embedded = embedded[-MAX_PHOTOS:]
        lines.append(f"(similarity stats use the latest {MAX_PHOTOS} embedded photos)")
    same, different = [], []
    for a, b in combinations(embedded, 2):
        (same if a.plant_id == b.plant_id else different).append(
            cosine(list(a.embedding), list(b.embedding))
        )
    lines.append("Same plant:       " + _summary(same))
    lines.append("Different plants: " + _summary(different))
    lines.append(
        f"Current bars: near {settings.match_min_similarity_near}, "
        f"far {settings.match_min_similarity_far}, margin {settings.match_margin}"
    )
    lines.append(
        "These stats treat the current plant assignments as truth, so they are only as good as "
        "your confirmed answers. A good 'near' bar sits above most of 'Different plants' and "
        "below most of 'Same plant'."
    )
    return "\n".join(lines)


def main() -> None:
    settings = get_settings()
    factory: sessionmaker[Session] = make_session_factory()
    garden_id = ensure_default_garden(factory, settings)
    with garden_session(factory, garden_id) as session:
        print(build_report(session, settings))


if __name__ == "__main__":
    main()

"""Garden scoping: every ORM query on a garden table is filtered by garden_id.

A session gets its garden through `session.info["garden_id"]`. Queries touching a GardenScoped
table on a session with no garden raise instead of silently reading across gardens. Raw SQL via
`session.execute(text(...))` bypasses this; keep raw SQL out of application code.
"""

import uuid

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from .models import GardenScoped


class UnscopedQueryError(RuntimeError):
    """A garden-scoped table was queried without a garden on the session."""


class GardenMismatchError(RuntimeError):
    """An object for a different garden was added to a garden-scoped session."""


@event.listens_for(Session, "do_orm_execute")
def _scope_queries(state: ORMExecuteState) -> None:
    if not (state.is_select or state.is_update or state.is_delete):
        return
    if not any(issubclass(m.class_, GardenScoped) for m in state.all_mappers):
        return
    garden_id = state.session.info.get("garden_id")
    if garden_id is None:
        raise UnscopedQueryError("query on a garden-scoped table without a garden on the session")
    state.statement = state.statement.options(
        with_loader_criteria(
            GardenScoped, lambda cls: cls.garden_id == garden_id, include_aliases=True
        )
    )


@event.listens_for(Session, "before_flush")
def _stamp_inserts(session: Session, flush_context, instances) -> None:
    garden_id = session.info.get("garden_id")
    for obj in session.new:
        if not isinstance(obj, GardenScoped):
            continue
        if garden_id is None:
            raise UnscopedQueryError("insert on a garden-scoped table without a garden")
        if obj.garden_id is None:
            obj.garden_id = garden_id
        elif obj.garden_id != garden_id:
            raise GardenMismatchError(f"{obj!r} belongs to another garden")


def bind_garden(session: Session, garden_id: uuid.UUID) -> Session:
    session.info["garden_id"] = garden_id
    return session

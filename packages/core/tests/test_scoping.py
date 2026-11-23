import pytest
from plotward_core.db import garden_session
from plotward_core.models import Garden, Plant
from plotward_core.scoping import GardenMismatchError, UnscopedQueryError
from sqlalchemy import select


def test_queries_only_see_their_own_garden(session_factory, make_garden):
    a, b = make_garden("a"), make_garden("b")
    with garden_session(session_factory, a) as s:
        s.add(Plant(species="tomato"))
    with garden_session(session_factory, b) as s:
        s.add(Plant(species="basil"))
        s.add(Plant(species="mint"))
    with garden_session(session_factory, a) as s:
        assert [p.species for p in s.scalars(select(Plant))] == ["tomato"]
    with garden_session(session_factory, b) as s:
        assert sorted(p.species for p in s.scalars(select(Plant))) == ["basil", "mint"]


def test_inserts_are_stamped_with_the_session_garden(session_factory, garden_id):
    with garden_session(session_factory, garden_id) as s:
        plant = Plant(species="tomato")
        s.add(plant)
    assert plant.garden_id == garden_id


def test_inserting_into_another_garden_is_refused(session_factory, make_garden):
    a, b = make_garden("a"), make_garden("b")
    with pytest.raises(GardenMismatchError), garden_session(session_factory, a) as s:
        s.add(Plant(garden_id=b, species="tomato"))


def test_updates_and_deletes_cannot_touch_another_garden(session_factory, make_garden):
    a, b = make_garden("a"), make_garden("b")
    with garden_session(session_factory, b) as s:
        plant = Plant(species="basil")
        s.add(plant)
    from sqlalchemy import delete, update

    with garden_session(session_factory, a) as s:
        s.execute(update(Plant).values(species="hacked"))
        s.execute(delete(Plant))
    with garden_session(session_factory, b) as s:
        assert [p.species for p in s.scalars(select(Plant))] == ["basil"]


def test_a_query_without_a_garden_raises_instead_of_leaking(session_factory, garden_id):
    with garden_session(session_factory, garden_id) as s:
        s.add(Plant(species="tomato"))
    with session_factory() as unscoped, pytest.raises(UnscopedQueryError):
        unscoped.scalars(select(Plant)).all()


def test_garden_table_itself_is_not_scoped(session_factory, make_garden):
    make_garden("a"), make_garden("b")
    with session_factory() as s:
        assert len(s.scalars(select(Garden)).all()) == 2

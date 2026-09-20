from __future__ import annotations

from pathlib import Path

import pytest

from aeat_hub.db import create_schema, make_engine, session_factory
from aeat_hub.paths import DataLayout
from aeat_hub.seed import seed_cuentas, seed_valladolid


@pytest.fixture
def layout(tmp_path: Path) -> DataLayout:
    root = tmp_path / "data"
    item = DataLayout(root)
    item.ensure()
    return item


@pytest.fixture
def session(layout: DataLayout):
    engine = make_engine(layout)
    create_schema(engine)
    factory = session_factory(engine)
    with factory() as db:
        seed_cuentas(db)
        seed_valladolid(db)
        db.commit()
        yield db

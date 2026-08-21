from __future__ import annotations

import pytest

from sql_lab.exercises import get_static_exercise
from sql_lab.models import Exercise


@pytest.fixture
def exercise() -> Exercise:
    return get_static_exercise()

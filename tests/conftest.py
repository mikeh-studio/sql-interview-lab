from __future__ import annotations

import pytest

from data_interview_lab.exercises import get_static_exercise
from data_interview_lab.models import Exercise


@pytest.fixture
def exercise() -> Exercise:
    return get_static_exercise()

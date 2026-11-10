from datetime import datetime

import pytest


class FakeClock:
    """A settable clock returning naive local datetimes."""

    def __init__(self, start=datetime(2026, 11, 10, 9, 0, 0)):
        self.now = start

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Never touch the real per-user state file."""
    monkeypatch.setenv("FLASHDECK_HOME", str(tmp_path / "home"))
    return tmp_path / "home"

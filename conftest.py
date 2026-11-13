"""pytest fixtures for selftest.py: its tests share one folder and one database, in file order.
pytest needs the folder name to be a Python name (git clone gives grimoire); selftest.py runs in any folder."""

import pytest

from .selftest import make_env


@pytest.fixture(scope="session")
def env():
    return make_env()


@pytest.fixture(scope="session")
def tmp(env):
    return env[0]


@pytest.fixture(scope="session")
def db(env):
    return env[1]

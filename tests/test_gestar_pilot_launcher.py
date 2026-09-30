from __future__ import annotations

import os

import pytest

from tools import gestar_pilot


def test_pilot_rejects_incomplete_or_disabled_configuration(monkeypatch):
    for name in (
        "MIKE_ENV", "MIKE_GESTAR_COMMERCIAL_ENABLED", "MIKE_GESTAR_BASE_URL",
        "MIKE_GESTAR_BEARER_TOKEN", "MIKE_GESTAR_INSTALLATION_ID",
        "MIKE_GESTAR_BUSINESS_ID", "MIKE_GESTAR_TENANT_ID", "MIKE_GESTAR_DEV_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="true"):
        gestar_pilot._settings()

    monkeypatch.setenv("MIKE_ENV", "development")
    with pytest.raises(RuntimeError, match="true"):
        gestar_pilot._settings()


def test_pilot_does_not_import_gestar_or_prepare_resources():
    assert "GESTAR-mike-base" not in gestar_pilot.__file__
    assert not hasattr(gestar_pilot, "seed_gestar")
    assert os.getenv("MIKE_GESTAR_COMMERCIAL_ENABLED") is None

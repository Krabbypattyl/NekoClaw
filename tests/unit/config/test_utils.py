# -*- coding: utf-8 -*-
from pathlib import Path

from copaw.config import utils as config_utils


# pylint: disable=protected-access


def test_normalize_working_dir_bound_paths_rewrites_legacy_root(monkeypatch):
    legacy_root = Path("~/.copaw").expanduser().resolve()
    new_root = Path("~/.copaw-dev").expanduser().resolve()
    monkeypatch.setattr(config_utils, "WORKING_DIR", new_root)

    data = {
        "agents": {
            "profiles": {
                "default": {
                    "workspace_dir": str(
                        legacy_root / "workspaces" / "default",
                    ),
                },
            },
        },
    }

    normalized = config_utils._normalize_working_dir_bound_paths(data)

    assert normalized["agents"]["profiles"]["default"]["workspace_dir"] == str(
        new_root / "workspaces" / "default",
    )


def test_normalize_working_dir_bound_paths_keeps_current_custom_root(
    monkeypatch,
):
    new_root = Path("~/.copaw-dev").expanduser().resolve()
    monkeypatch.setattr(config_utils, "WORKING_DIR", new_root)

    data = {
        "agents": {
            "profiles": {
                "default": {
                    "workspace_dir": str(new_root / "workspaces" / "default"),
                },
            },
        },
    }

    normalized = config_utils._normalize_working_dir_bound_paths(data)

    assert normalized["agents"]["profiles"]["default"]["workspace_dir"] == str(
        new_root / "workspaces" / "default",
    )


def test_normalize_working_dir_bound_paths_repairs_repeated_custom_suffix(
    monkeypatch,
):
    new_root = Path("~/.copaw-dev").expanduser().resolve()
    monkeypatch.setattr(config_utils, "WORKING_DIR", new_root)

    drifted_root = Path(str(new_root) + "-dev-dev")
    data = {
        "agents": {
            "profiles": {
                "default": {
                    "workspace_dir": str(
                        drifted_root / "workspaces" / "default",
                    ),
                },
            },
        },
    }

    normalized = config_utils._normalize_working_dir_bound_paths(data)

    assert normalized["agents"]["profiles"]["default"]["workspace_dir"] == str(
        new_root / "workspaces" / "default",
    )

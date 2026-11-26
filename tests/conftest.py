import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def make(tmp_path, monkeypatch):
    """Fresh proxy with its own data folder. make(seed, approver) -> TetherProxy."""
    from tether.core import snapshot
    from tether.core.proxy import TetherProxy
    from tether.tools import mock_apps

    monkeypatch.setenv("TETHER_DATA_DIR", str(tmp_path))

    def _make(seed="clean", approver="approve"):
        monkeypatch.setenv("TETHER_APPROVER", approver)
        mock_apps.reset_state(seed)
        snapshot.reset_audit_log()
        return TetherProxy()

    return _make

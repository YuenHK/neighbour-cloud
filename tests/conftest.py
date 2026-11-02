from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_TEST_RUNTIME = tempfile.TemporaryDirectory(prefix="zhiwei-tests-")
_TEST_ROOT = Path(_TEST_RUNTIME.name)

# The API module creates its event store during import.  Force every pytest run
# onto disposable paths before any test module imports edge_hub.app, even when
# tests are launched from the deployed project directory.
os.environ["ZHIWEI_EVENT_DB"] = str(_TEST_ROOT / "events.sqlite3")
os.environ["ZHIWEI_DATA_ROOT"] = str(_TEST_ROOT / "data")
os.environ['ZHIWEI_ROBOT_DB'] = str(_TEST_ROOT / 'robot-control.sqlite3')
os.environ['ZHIWEI_EP_REGISTRY'] = str(_TEST_ROOT / 'ep-known.sqlite3')
os.environ['ZHIWEI_OPERATOR_KEY'] = 'unit-test-operator-only'
os.environ['ZHIWEI_EVENT_INGEST_KEY'] = 'unit-test-collector-only'
os.environ["ZHIWEI_SILICONFLOW_DISABLED"] = "1"


def pytest_sessionfinish() -> None:
    app_module = sys.modules.get("edge_hub.app")
    if app_module is not None:
        app_module.store.close()
        app_module.robot_control.close()
        app_module.service_desk.close()
        app_module.estate_store.close()
    _TEST_RUNTIME.cleanup()

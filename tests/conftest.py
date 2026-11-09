"""层测试以 flange 工具根为导入根；FLANGE_TOOL_ROOT 未设置时取同级 flange-layer。"""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

LAYER_ROOT = Path(__file__).resolve().parent.parent
TOOL_ROOT = Path(os.environ.get("FLANGE_TOOL_ROOT", LAYER_ROOT.parent / "flange-layer")).resolve()
if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))


def load_strategy(relative: str, name: str):
    spec = importlib.util.spec_from_file_location(name, LAYER_ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def distro():
    return load_strategy("strategies/distro/provider.py", "alpine_distro_provider")

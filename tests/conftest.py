import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(scope="session")
def samples(tmp_path_factory):
    from basedata.demo.samples import build_samples

    folder = tmp_path_factory.mktemp("samples")
    build_samples(folder)
    return folder


@pytest.fixture()
def demo_ctx(tmp_path):
    from basedata.demo import build_demo

    return build_demo(tmp_path / "samples", history=False)

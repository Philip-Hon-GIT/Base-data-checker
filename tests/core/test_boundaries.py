"""Sjekker at områdene bare importerer «nedover»: core ← indata ← harness ← ui ← selfcheck.

Kjernen kan ikke importere fra noe annet område, indata bare fra core, osv. Slik kan hvert område
endres på sin egen gren uten å dra med seg de andre.
"""

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "basedata"
ORDER = ["core", "indata", "harness", "ui", "selfcheck"]
ALLOWED = {area: set(ORDER[: i + 1]) for i, area in enumerate(ORDER)}


def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.level:
                raise AssertionError(f"{path}: bruk absolutte importer (basedata.<område>…), ikke relative")
            yield node.module, node.lineno
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno


def test_every_module_belongs_to_an_area():
    loose = [p.name for p in PACKAGE.glob("*.py") if p.name not in ("__init__.py", "__main__.py")]
    assert loose == [], f"Moduler utenfor et område: {loose}"
    assert sorted(p.name for p in PACKAGE.iterdir() if p.is_dir() and p.name != "__pycache__") == sorted(ORDER)


def test_areas_only_import_downwards():
    wrong = []
    for area in ORDER:
        for path in (PACKAGE / area).rglob("*.py"):
            for module, line in _imports(path):
                parts = module.split(".")
                if parts[0] != "basedata" or len(parts) < 2:
                    continue
                if parts[1] not in ALLOWED[area]:
                    wrong.append(f"{path.relative_to(PACKAGE)}:{line} importerer {module}")
    assert wrong == [], "Import mot pilen:\n" + "\n".join(wrong)

"""The generated stubs are fresh, match the runtime types and work with mypy."""

import ast
import importlib.util
import os
import subprocess
import sys

import pytest
from zeep.xsd import ComplexType

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TYPES_DIR = os.path.join(ROOT, "py_eudr", "types")
EUDR_NAMESPACE = "http://ec.europa.eu/tracesnt/certificate/eudr/"


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "generate_stubs", os.path.join(ROOT, "scripts", "generate_stubs.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("version", ["v3", "v4"])
def test_stubs_are_up_to_date(version):
    with open(os.path.join(TYPES_DIR, f"{version}.pyi"), encoding="utf-8") as fh:
        committed = fh.read()
    assert _load_generator().render(version) == committed, (
        "Stubs are stale: run `python scripts/generate_stubs.py`"
    )


def _stub_classes(version):
    with open(os.path.join(TYPES_DIR, f"{version}.pyi"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    classes = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes[node.name] = [
                item.target.id
                for item in node.body
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
            ]
    return classes


@pytest.mark.parametrize("version", ["v3", "v4"])
@pytest.mark.parametrize(
    "service,namespace_class",
    [("dds", "DdsTypes"), ("sd", "SdTypes"), ("verify", "VerifyTypes")],
)
def test_stubs_match_runtime_types(request, version, service, namespace_class):
    client = request.getfixturevalue(f"client_{version}")
    classes = _stub_classes(version)
    runtime = getattr(client.types, service)
    runtime_complex = {
        name
        for name, value in vars(runtime).items()
        if isinstance(value, ComplexType)
        and value.qname is not None
        and value.qname.namespace.startswith(EUDR_NAMESPACE)
    }
    assert set(classes[namespace_class]) == runtime_complex
    for name in classes[namespace_class]:
        elements = [element_name for element_name, _ in getattr(runtime, name).elements]
        assert classes[name] == elements, name


def test_typed_example_passes_mypy():
    pytest.importorskip("mypy")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--warn-unused-ignores",
            "--no-incremental",
            os.path.join(ROOT, "tests", "typing", "example.py"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

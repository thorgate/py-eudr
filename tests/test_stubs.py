"""The generated stubs are fresh, match the runtime types and work with mypy."""

import ast
import importlib.util
import os
import subprocess
import sys

import pytest
from zeep.xsd import ComplexType
from zeep.xsd.elements import Element

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
    """Class name -> [(field, optional, many)] from the stub's annotations."""
    with open(os.path.join(TYPES_DIR, f"{version}.pyi"), encoding="utf-8") as fh:
        source = fh.read()
    tree = ast.parse(source)
    classes = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            defaults = set()
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                    defaults = {
                        arg.arg
                        for arg, default in zip(
                            item.args.kwonlyargs, item.args.kw_defaults
                        )
                        if default is not None
                    }
            fields = []
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(
                    item.target, ast.Name
                ):
                    annotation = ast.get_source_segment(source, item.annotation) or ""
                    many = annotation.startswith("list[")
                    optional = item.target.id in defaults
                    # Attributes: single optional values are `X | None`, lists never None.
                    assert annotation.endswith("| None") == (optional and not many), (
                        node.name,
                        item.target.id,
                    )
                    fields.append((item.target.id, optional, many))
            classes[node.name] = fields
    return classes


def _runtime_fields(xsd_type):
    fields = []
    for _, particle in xsd_type.elements_nested:
        if isinstance(particle, Element):
            group = [(particle.name, particle)]
            group_optional = False
        else:
            group = particle.elements
            group_optional = (
                type(particle).__name__ == "Choice" or particle.min_occurs == 0
            )
        for name, element in group:
            many = element.max_occurs == "unbounded" or element.max_occurs > 1
            fields.append((name, group_optional or element.min_occurs == 0, many))
    return fields


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
    names = [field for field, _, _ in classes[namespace_class]]
    assert set(names) == runtime_complex
    for name in names:
        assert classes[name] == _runtime_fields(getattr(runtime, name)), name


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

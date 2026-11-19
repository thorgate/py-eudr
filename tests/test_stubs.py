"""The generated stubs are fresh, match the runtime types and work with mypy."""

import ast
import importlib.util
import os
import subprocess
import sys

import pytest
from conftest import namespaces
from lxml import etree
from payloads import dds_statement, sd_statement
from zeep.xsd import ComplexType
from zeep.xsd.elements import Element
from zeep.xsd.valueobjects import CompoundValue

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
    """Class name -> [(field, optional, many, annotation)] from the stub."""
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
                    fields.append((item.target.id, optional, many, annotation))
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
    names = [field for field, _, _, _ in classes[namespace_class]]
    assert set(names) == runtime_complex
    for name in names:
        stub_fields = [field[:3] for field in classes[name]]
        assert stub_fields == _runtime_fields(getattr(runtime, name)), name


def _compound_values(value):
    """All zeep objects in a (nested) value."""
    if isinstance(value, CompoundValue):
        yield value
        for key in value:
            yield from _compound_values(value[key])
    elif isinstance(value, list):
        for item in value:
            yield from _compound_values(item)


def _check_absent_fields(classes, obj):
    checked = 0
    name = obj._xsd_type.qname.localname
    for field, optional, many, annotation in classes[name]:
        if not optional or field not in obj:
            continue  # absent required fields are invalid anyway
        value = obj[field]
        if value is None:
            assert annotation.endswith("| None"), (name, field, annotation)
        elif value == []:
            assert many and annotation.startswith("list["), (name, field, annotation)
        checked += 1
    return checked


@pytest.mark.parametrize("version", ["v3", "v4"])
@pytest.mark.parametrize("service", ["dds", "sd", "verify"])
def test_stub_attributes_match_constructed_values(request, version, service):
    """Absent optional fields of zeep objects built without arguments fit the stubs."""
    client = request.getfixturevalue(f"client_{version}")
    runtime = getattr(client.types, service)
    classes = _stub_classes(version)
    checked = 0
    for name, _, _, _ in classes[f"{service.capitalize()}Types"]:
        checked += _check_absent_fields(classes, getattr(runtime, name)())
    assert checked


@pytest.mark.parametrize("version", ["v3", "v4"])
@pytest.mark.parametrize(
    "service,element,role,build",
    [
        ("dds", "SubmitDdsRequest", "OPERATOR", dds_statement),
        ("sd", "SubmitSdRequest", "MICRO_OPERATOR", sd_statement),
    ],
)
def test_stub_attributes_match_parsed_values(
    request, version, service, element, role, build
):
    """Round trip a sample statement through XML: optional fields absent from the
    XML (including lists inside an xs:choice) fit the stubs when parsed by zeep."""
    client = request.getfixturevalue(f"client_{version}")
    service_client = getattr(client, f"{service}_client")
    xsd_element = service_client.get_element(
        f"{{{namespaces(version)[service]}}}{element}"
    )
    node = etree.Element("root")
    xsd_element.render(node, xsd_element(operatorRole=role, statement=build(client)))
    parsed = xsd_element.parse(node[0], service_client.wsdl.types)
    classes = _stub_classes(version)
    objects = list(_compound_values(parsed.statement))
    assert sum(_check_absent_fields(classes, obj) for obj in objects)


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

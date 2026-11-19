#!/usr/bin/env python
"""Refresh the vendored EUDR WSDL/XSD files in ``py_eudr/schemas/``.

The EUDR web services are published by JAX-WS, which serves every document of a
service under the service URL with a query parameter (``?wsdl``, ``?wsdl=N``,
``?xsd=N``). This script starts from ``<Service>?wsdl`` for every supported
service, follows all ``wsdl:import``/``xs:import``/``xs:include`` locations of the
same service, and stores the documents verbatim:

    ?wsdl    -> <Service>.wsdl
    ?wsdl=N  -> wsdlN.wsdl
    ?xsd=N   -> xsdN.xsd

It prints which files were added, changed or removed, so a refresh is a plain
``git diff``. Usage::

    python scripts/fetch_schemas.py                # from acceptance (default)
    python scripts/fetch_schemas.py --production   # from production
    python scripts/fetch_schemas.py --check        # only report differences
"""

import argparse
import os
import sys
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import requests
from lxml import etree

HOSTS = {
    "acceptance": "acceptance.eudr.webcloud.ec.europa.eu",
    "production": "eudr.webcloud.ec.europa.eu",
}

SCHEMAS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_eudr", "schemas"
)

# Keep in sync with py_eudr.transport.service_directory().
SERVICES = {
    "EudrEchoService": "echo",
    "EUDRDueDiligenceStatementServiceV3": "v3/EUDRDueDiligenceStatementServiceV3",
    "EUDRSimplifiedDeclarationServiceV3": "v3/EUDRSimplifiedDeclarationServiceV3",
    "EUDRVerifyDeclarationServiceV3": "v3/EUDRVerifyDeclarationServiceV3",
    "EUDRDueDiligenceStatementServiceV4": "v4/EUDRDueDiligenceStatementServiceV4",
    "EUDRSimplifiedDeclarationServiceV4": "v4/EUDRSimplifiedDeclarationServiceV4",
    "EUDRVerifyDeclarationServiceV4": "v4/EUDRVerifyDeclarationServiceV4",
}

LOCATION_XPATH = "//*[local-name()='import' or local-name()='include']"


def file_name(service: str, url: str) -> str:
    query = parse_qs(urlparse(url).query, keep_blank_values=True)
    if "xsd" in query:
        return "xsd{}.xsd".format(int(query["xsd"][0]))
    if query.get("wsdl", [""])[0]:
        return "wsdl{}.wsdl".format(int(query["wsdl"][0]))
    return service + ".wsdl"


def same_service(url: str, service: str) -> bool:
    parsed = urlparse(url)
    return parsed.hostname in HOSTS.values() and parsed.path.endswith("/" + service)


def crawl(session: requests.Session, host: str, service: str) -> Dict[str, bytes]:
    """Download all documents of one service, keyed by local file name."""
    start = "https://{}/tracesnt/ws/{}?wsdl".format(host, service)
    queue: List[str] = [start]
    files: Dict[str, bytes] = {}
    while queue:
        url = queue.pop(0)
        name = file_name(service, url)
        if name in files:
            continue
        response = session.get(url, timeout=60)
        response.raise_for_status()
        try:
            document = etree.fromstring(response.content)
        except etree.XMLSyntaxError as exc:
            raise RuntimeError("{} did not return XML: {}".format(url, exc))
        files[name] = response.content
        for node in document.xpath(LOCATION_XPATH):
            location: Optional[str] = node.get("location") or node.get("schemaLocation")
            if location and same_service(location, service):
                queue.append(location)
    return files


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--production", action="store_true", help="fetch from production host"
    )
    parser.add_argument(
        "--check", action="store_true", help="do not write, exit 1 on differences"
    )
    parser.add_argument("--target", default=SCHEMAS_DIR, help="schemas directory")
    options = parser.parse_args(argv)

    host = HOSTS["production" if options.production else "acceptance"]
    session = requests.Session()
    changed = 0
    for service, directory in SERVICES.items():
        target = os.path.join(options.target, directory)
        files = crawl(session, host, service)
        existing = set(os.listdir(target)) if os.path.isdir(target) else set()
        for name in sorted(set(files) | existing):
            path = os.path.join(target, name)
            if name not in files:
                if name.endswith((".wsdl", ".xsd")):
                    print("removed  {}/{}".format(directory, name))
                    changed += 1
                    if not options.check:
                        os.remove(path)
                continue
            old = None
            if name in existing:
                with open(path, "rb") as fh:
                    old = fh.read()
            if old == files[name]:
                continue
            print("{}  {}/{}".format("changed" if old else "added  ", directory, name))
            changed += 1
            if not options.check:
                os.makedirs(target, exist_ok=True)
                with open(path, "wb") as fh:
                    fh.write(files[name])
    print("{} file(s) differ from {}".format(changed, host))
    return 1 if options.check and changed else 0


if __name__ == "__main__":
    sys.exit(main())

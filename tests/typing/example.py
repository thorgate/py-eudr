"""Type-checked usage example (checked by tests/test_stubs.py with mypy).

Each `# type: ignore[...]` marks a deliberate error that the stubs must catch; mypy runs
with --warn-unused-ignores, so the test fails if the stubs stop catching it.
"""

import datetime
import typing as t
from decimal import Decimal

from py_eudr import BodyIdentity, ClientV3, ClientV4


def v3_usage(client: ClientV3) -> None:
    types = client.types.dds
    statement = types.DueDiligenceStatementBaseType(
        activityType="DOMESTIC",
        geoLocationConfidential=False,
        countryOfActivity="EE",
        commodities=[
            types.DdsCommodityType(
                hsHeading="4401",
                descriptors=types.CommercialDescriptionType(
                    descriptionOfGoods="Logs",
                    goodsMeasure=types.GoodsMeasureType(
                        netWeight=1.5, percentageEstimationOrDeviation=5
                    ),
                ),
                producers=[
                    types.DdsProducerType(country="EE", geometryGeojson=b"{}"),
                    {"country": "EE", "geometryGeojson": b"{}"},
                ],
            )
        ],
    )
    with client.authenticated(username="u", authentication_key="k") as c:
        uuid: str = c.submit_dds("OPERATOR", statement, body_identity="OP1")
        for overview in c.get_dds([uuid]):
            reference: t.Optional[str] = overview.referenceNumber
            when: t.Optional[datetime.datetime] = overview.date
            print(reference, when, overview.status)
        withdrawn = c.withdraw_dds(uuid, body_identity=BodyIdentity(operator="OP1"))
        print(withdrawn.status)
        print(c.get_sd([uuid, (uuid, 2)]))
        print(c.verify_declaration("25EEABCDEFGHIJ", "ABCDEFGH").result)

    # Deliberate errors:
    types.DdsProducerType(country="EE", geometryGeojson=b"{}", colour="red")  # type: ignore[call-arg]
    types.DdsCommodityType(hsHeading=4401, descriptors={})  # type: ignore[arg-type]
    client.submit_dds("BOSS", statement)  # type: ignore[arg-type]
    types.GoodsMeasureType().netWeight.upper()  # type: ignore[union-attr]
    # V3 has no referenceNumberInfo
    print(client.get_dds(["x"])[0].referenceNumberInfo)  # type: ignore[attr-defined]


def v4_usage(client: ClientV4) -> None:
    types = client.types.sd
    location = types.SdProducerLocationType(cadastralIdentifier=["123"])
    statement = types.SimplifiedDeclarationBaseType(
        internalReferenceNumber="SD-1",
        activityType="DOMESTIC",
        geoLocationConfidential=False,
        commodities=[
            types.SdCommodityType(
                hsHeading="4401",
                descriptors=types.CommercialDescriptionType(
                    descriptionOfGoods="Logs",
                    goodsMeasure=types.GoodsMeasureType(netWeight=Decimal("1.5")),
                ),
                producers=[
                    types.SdProducerType(
                        producerCountry="EE", producerLocation=location
                    )
                ],
            )
        ],
    )
    sd_identifier: str = client.submit_sd("MICRO_OPERATOR", statement)
    info: t.Optional[str] = client.get_sd([sd_identifier])[0].referenceNumberInfo
    print(info, client.update_sd(sd_identifier, statement).version)

    # Deliberate errors:
    client.submit_sd("OPERATOR", statement)  # type: ignore[arg-type]
    types.SdProducerType(producerCountry="EE")  # type: ignore[call-arg]
    verify = client.types.verify
    verify.VerifyDeclarationRequestType(referenceNumber=1, verificationNumber="x")  # type: ignore[arg-type]

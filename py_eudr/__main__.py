"""Integration test CLI for the EUDR API (acceptance environment by default)."""

import argparse
import logging
import os
import random
import typing as t

from py_eudr.client import ClientV3, ClientV4

logger = logging.getLogger(__name__)

AnyClient = t.Union[ClientV3, ClientV4]


def main(args: t.Optional[t.Sequence[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Test EUDR connection")
    parser.add_argument("--username", "-u", required="EUDR_USERNAME" not in os.environ)
    parser.add_argument(
        "--authentication-key",
        "-a",
        required="EUDR_AUTHENTICATION_KEY" not in os.environ,
    )
    parser.add_argument("--client-id", "-c", required=False)
    parser.add_argument(
        "--v4", action="store_true", help="Use EUDR V4 API instead of V3"
    )
    parser.add_argument(
        "--production",
        action="store_true",
        help="Use the production environment instead of acceptance",
    )
    parser.add_argument(
        "--allow-production-writes",
        action="store_true",
        help="Allow submitting and withdrawing with --production",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--echo", "-e", action="store_true")
    group.add_argument("--retrieve", "-r", metavar="UUID", help="Get a DDS overview")
    group.add_argument(
        "--submit-random", "-s", action="store_true", help="Submit a random DDS"
    )
    group.add_argument("--retract", "-d", metavar="UUID", help="Withdraw a DDS")
    group.add_argument("--retrieve-sd", metavar="UUID", help="Get an SD overview")
    group.add_argument(
        "--submit-random-sd", action="store_true", help="Submit a random SD"
    )
    group.add_argument("--retract-sd", metavar="UUID", help="Withdraw an SD")
    group.add_argument(
        "--verify",
        nargs=2,
        metavar=("REFERENCE_NUMBER", "VERIFICATION_NUMBER"),
        help="Verify a DDS or SD",
    )
    options = parser.parse_args(args)
    writes = (
        options.submit_random
        or options.submit_random_sd
        or options.retract
        or options.retract_sd
    )
    if options.production and writes and not options.allow_production_writes:
        parser.error(
            "refusing to write to production without --allow-production-writes"
        )

    username = options.username or os.environ.get("EUDR_USERNAME", "")
    authentication_key = options.authentication_key or os.environ.get(
        "EUDR_AUTHENTICATION_KEY", ""
    )
    if not username or not authentication_key:
        parser.error(
            "username and authentication key must not be empty "
            "(--username/--authentication-key or EUDR_USERNAME/EUDR_AUTHENTICATION_KEY)"
        )
    client_id = options.client_id or os.environ.get("EUDR_CLIENT_ID")

    client_class = ClientV4 if options.v4 else ClientV3
    client: AnyClient = client_class(test=not options.production)
    with client.authenticated(
        username=username,
        authentication_key=authentication_key,
        client_id=client_id,
    ):
        if options.retrieve:
            logger.info("DDS overview: %s", client.get_dds([options.retrieve]))
        elif options.submit_random:
            submit_random(client)
        elif options.retract:
            logger.info("Withdrawal result: %s", client.withdraw_dds(options.retract))
        elif options.retrieve_sd:
            logger.info("SD overview: %s", client.get_sd([options.retrieve_sd]))
        elif options.submit_random_sd:
            submit_random_sd(client)
        elif options.retract_sd:
            logger.info("Withdrawal result: %s", client.withdraw_sd(options.retract_sd))
        elif options.verify:
            logger.info("Verification: %s", client.verify_declaration(*options.verify))
        else:
            logger.info("Echo response: %s", client.test_echo("Py-EUDR"))


# Random spot in a forest in Tallinn, Estonia. Real data would be a polygon of some sort.
RANDOM_GEOMETRY = """
    {
      "type": "FeatureCollection",
      "features": [
        {
          "type": "Feature",
          "properties": {},
          "geometry": {
            "coordinates": [
              24.641208189758743,
              59.42910392824197
            ],
            "type": "Point"
          }
        }
      ]
    }
    """


def random_goods_measure(types: t.Any) -> t.Any:
    return types.GoodsMeasureType(
        netWeight=random.randint(1, 10000) / 100,
        # Optional in the XSD, but required by the server for DDS
        # (EUDR-COMMODITIES-DESCRIPTOR-PERCENTAGE-ESTIMATION-MISSING).
        percentageEstimationOrDeviation=5,
    )


def random_description() -> str:
    return (
        f"Fir logs {random.randint(10, 20)}-{random.randint(25, 30)}cm, "
        f"{random.randint(3, 6)}m"
    )


def submit_random(client: AnyClient) -> None:
    # Version agnostic: V3 and V4 types share the same shape.
    types: t.Any = client.types.dds
    dds = types.DueDiligenceStatementBaseType(
        activityType="DOMESTIC",
        countryOfActivity="EE",
        geoLocationConfidential=False,
        commodities=[
            types.DdsCommodityType(
                position=1,
                hsHeading="4401",
                speciesInfo=[
                    types.SpeciesInformationType(
                        scientificName="Abies sibirica", commonName="Fir"
                    )
                ],
                descriptors=types.CommercialDescriptionType(
                    descriptionOfGoods=random_description(),
                    goodsMeasure=random_goods_measure(types),
                ),
                producers=[
                    types.DdsProducerType(
                        position=1,
                        country="EE",
                        name="Producer OÜ",
                        geometryGeojson=RANDOM_GEOMETRY.encode(),
                    )
                ],
            )
        ],
        internalReferenceNumber=f"TEST-{random.randint(10000, 99999)}",
    )
    logger.info("Submission result: %s", client.submit_dds("OPERATOR", dds))


def submit_random_sd(client: AnyClient) -> None:
    types: t.Any = client.types.sd
    sd = types.SimplifiedDeclarationBaseType(
        internalReferenceNumber=f"SD-{random.randint(10000, 99999)}",
        activityType="DOMESTIC",
        countryOfActivity="EE",
        geoLocationConfidential=False,
        commodities=[
            types.SdCommodityType(
                position=1,
                hsHeading="4401",
                descriptors=types.CommercialDescriptionType(
                    descriptionOfGoods=random_description(),
                    goodsMeasure=random_goods_measure(types),
                ),
                producers=[
                    types.SdProducerType(
                        producerPosition=1,
                        producerCountry="EE",
                        producerName="Producer OÜ",
                        producerLocation=types.SdProducerLocationType(
                            geometryGeojson=RANDOM_GEOMETRY.encode()
                        ),
                    )
                ],
            )
        ],
    )
    logger.info("Submission result: %s", client.submit_sd("MICRO_OPERATOR", sd))


if __name__ == "__main__":
    main()

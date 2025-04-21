import argparse
import base64
import logging
import os
import random

from py_eudr.client import Client


def main(*args):
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(
        description="Test EUDR connection",
    )
    parser.add_argument(
        "--username",
        "-u",
        required="EUDR_USERNAME" not in os.environ,
    )
    parser.add_argument(
        "--authentication-key",
        "-a",
        required="EUDR_AUTHENTICATION_KEY" not in os.environ,
    )
    parser.add_argument(
        "--client-id",
        "-c",
        required=False,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--echo", "-e", action="store_true")
    group.add_argument(
        "--retrieve",
        "-r",
    )
    group.add_argument("--submit-random", "-s", action="store_true")
    group.add_argument(
        "--retract",
        "-d",
    )
    options = parser.parse_args(*args or None)

    username = options.username or os.environ.get("EUDR_USERNAME", "")
    authentication_key = options.authentication_key or os.environ.get(
        "EUDR_AUTHENTICATION_KEY", ""
    )
    client_id = options.client_id or os.environ.get("EUDR_CLIENT_ID", "eudr-test")

    with Client().authenticated(
        username=username,
        authentication_key=authentication_key,
        client_id=client_id,
    ) as client:
        if options.retrieve:
            retrieve(client, options.retrieve)
        elif options.submit_random:
            submit_random(client)
        elif options.retract:
            retract(client, options.retract)
        else:
            echo(client)


def echo(client: Client):
    response = client.test_echo("Py-EUDR")
    logging.info("Echo response: %s", response)


def retrieve(client: Client, uuid: str):
    result = client.retrieval_client.service.getDdsInfo(uuid)
    logging.info("Retrieval result: %s", result)


def submit_random(client: Client):
    # Random spot in a forest in Tallinn, Estonia. Real data would be a polygon of some sort.
    geometry = """
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

    dds = client.types.DueDiligenceStatementBaseType(
        activityType="DOMESTIC",
        geoLocationConfidential=False,
        commodities=[
            client.types.CommodityType(
                hsHeading=4401,
                speciesInfo=[
                    client.types.SpeciesInformationType(
                        scientificName="Abies sibirica", commonName="Fir"
                    )
                ],
                descriptors=[
                    client.types.CommercialDescriptionType(
                        descriptionOfGoods=f"Fir logs {random.randint(10, 20)}-{random.randint(25, 30)}cm, {random.randint(3, 6)}m",
                        goodsMeasure=client.types.GoodsMeasureType(
                            netWeight=random.randint(1, 10000) / 100,
                        ),
                    )
                ],
                producers=[
                    client.types.ProducerType(
                        country="EE",
                        name="Producer OÜ",
                        geometryGeojson=base64.encodebytes(geometry.encode()).decode(),
                    )
                ],
            )
        ],
        internalReferenceNumber=f"TEST-{random.randint(10000, 99999)}",
    )
    result = client.submission_client.service.submitDds("OPERATOR", dds)
    logging.info("Submission result: %s", result)


def retract(client: Client, uuid: str):
    result = client.submission_client.service.retractDds(uuid)
    logging.info("Submission result: %s", result)


if __name__ == "__main__":
    main(None)

"""Sample statements built with the zeep types of a client (V3 or V4)."""

import typing as t

GEOJSON = (
    b'{"type":"FeatureCollection","features":[{"type":"Feature","properties":{},'
    b'"geometry":{"type":"Point","coordinates":[24.641208,59.429103]}}]}'
)


def dds_statement(client: t.Any, reference: str = "REF-1") -> t.Any:
    types = client.types.dds
    return types.DueDiligenceStatementBaseType(
        internalReferenceNumber=reference,
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
                    descriptionOfGoods="Fir logs, py-eudr test",
                    goodsMeasure=types.GoodsMeasureType(
                        netWeight=12.5, percentageEstimationOrDeviation=5
                    ),
                ),
                producers=[
                    types.DdsProducerType(
                        position=1,
                        country="EE",
                        name="Producer OÜ",
                        geometryGeojson=GEOJSON,
                    )
                ],
            )
        ],
    )


def sd_statement(client: t.Any, reference: str = "SD-1") -> t.Any:
    types = client.types.sd
    return types.SimplifiedDeclarationBaseType(
        internalReferenceNumber=reference,
        activityType="DOMESTIC",
        countryOfActivity="EE",
        geoLocationConfidential=False,
        commodities=[
            types.SdCommodityType(
                position=1,
                hsHeading="4401",
                descriptors=types.CommercialDescriptionType(
                    descriptionOfGoods="Fir logs, py-eudr test",
                    goodsMeasure=types.GoodsMeasureType(
                        netWeight=12.5, percentageEstimationOrDeviation=5
                    ),
                ),
                producers=[
                    types.SdProducerType(
                        producerPosition=1,
                        producerCountry="EE",
                        producerName="Producer OÜ",
                        producerLocation=types.SdProducerLocationType(
                            geometryGeojson=GEOJSON
                        ),
                    )
                ],
            )
        ],
    )

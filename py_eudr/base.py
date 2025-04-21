from zeep import Client as ZeepClient


from py_eudr.username_token import EUDRUsernameToken


class EchoClient(ZeepClient):
    service_url = (
        "https://acceptance.eudr.webcloud.ec.europa.eu/tracesnt/ws/EudrEchoService?wsdl"
    )

    def __init__(
        self,
        *,
        username: str = "",
        authentication_key: str = "",
        client_id: str = "",
    ):
        self.wsse = EUDRUsernameToken(
            username,
            authentication_key,
        )
        super().__init__(
            self.service_url,
            wsse=self.wsse,
        )
        self.set_default_soapheaders(
            {"webServiceClientId": client_id},
        )


class RetrievalClient(EchoClient):
    service_url = "https://acceptance.eudr.webcloud.ec.europa.eu/tracesnt/ws/EUDRRetrievalServiceV1?wsdl"


class SubmissionClient(EchoClient):
    service_url = "https://acceptance.eudr.webcloud.ec.europa.eu/tracesnt/ws/EUDRSubmissionServiceV1?wsdl"

import datetime


try:
    import zoneinfo
except ImportError:
    from backports import zoneinfo

from zeep.wsse.username import UsernameToken
from zeep.wsse.utils import WSU, ensure_id


class EUDRUsernameToken(UsernameToken):
    TIMESTAMP_TOKEN_TTL = 20

    def __init__(self, username, authentication_key):
        super().__init__(
            username=username,
            password=authentication_key,
            zulu_timestamp=True,
            use_digest=True,
        )

    def apply(self, envelope, headers):
        self.make_timestamp_token()
        return super().apply(envelope, headers)

    def make_timestamp_token(self):
        timestamp_token = WSU.Timestamp()
        today_datetime = datetime.datetime.now(zoneinfo.ZoneInfo("UTC")).replace(
            microsecond=0
        )
        expires_datetime = today_datetime + datetime.timedelta(
            seconds=self.TIMESTAMP_TOKEN_TTL
        )
        timestamp_elements = [
            WSU.Created(
                today_datetime.isoformat(sep="T", timespec="seconds").replace(
                    "+00:00", "Z"
                )
            ),
            WSU.Expires(
                expires_datetime.isoformat(sep="T", timespec="seconds").replace(
                    "+00:00", "Z"
                )
            ),
        ]
        timestamp_token.extend(timestamp_elements)
        ensure_id(timestamp_token)
        self.created = today_datetime
        self.timestamp_token = timestamp_token

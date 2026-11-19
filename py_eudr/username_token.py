import copy
import datetime

from zeep.wsse.username import UsernameToken
from zeep.wsse.utils import WSU, ensure_id


def _zulu(value: datetime.datetime) -> str:
    return value.isoformat(sep="T", timespec="seconds").replace("+00:00", "Z")


class EUDRUsernameToken(UsernameToken):
    """WS-Security UsernameToken (password digest) with a fresh wsu:Timestamp per request.

    One token is shared by all requests made with the same credentials, possibly
    concurrently, so ``apply`` never mutates it: the timestamp is built on a copy.
    """

    TIMESTAMP_TOKEN_TTL = 20

    def __init__(self, username, authentication_key):
        super().__init__(
            username=username,
            password=authentication_key,
            zulu_timestamp=True,
            use_digest=True,
        )

    def apply(self, envelope, headers):
        token = copy.copy(self)
        token.created, token.timestamp_token = self.make_timestamp_token()
        return UsernameToken.apply(token, envelope, headers)

    def make_timestamp_token(self):
        """Return ``(created, wsu:Timestamp element)`` for a new request."""
        created = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
        expires = created + datetime.timedelta(seconds=self.TIMESTAMP_TOKEN_TTL)
        timestamp_token = WSU.Timestamp()
        timestamp_token.extend(
            [WSU.Created(_zulu(created)), WSU.Expires(_zulu(expires))]
        )
        ensure_id(timestamp_token)
        return created, timestamp_token

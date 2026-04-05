from django.conf import settings
from google.auth.transport import requests
from google.oauth2 import id_token


class GoogleAuthError(Exception):
    pass


def verify_google_id_token(token):
    """
    Verify ID token and return decoded payload.
    Raises GoogleAuthError for any validation issue.
    """

    client_id = getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "")

    if not client_id:
        raise GoogleAuthError(
            "GOOGLE_OAUTH_CLIENT_ID is not configured in environment/settings."
        )

    try:
        payload = id_token.verify_oauth2_token(
            token,
            requests.Request(),
            audience=client_id,
        )
    except Exception as exc:
        raise GoogleAuthError("Invalid Google ID token.") from exc

    if payload.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
        raise GoogleAuthError("Invalid token issuer.")

    return payload

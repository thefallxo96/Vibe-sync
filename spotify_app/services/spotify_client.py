import time
import requests
from django.conf import settings

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE = "https://api.spotify.com/v1"

SCOPES = "user-read-currently-playing user-read-playback-state"


def get_login_url(state: str) -> str:
    """
    Build the Spotify authorize URL (Authorization Code flow).
    """
    if not settings.SPOTIFY_CLIENT_ID or not settings.SPOTIFY_REDIRECT_URI:
        raise RuntimeError("Missing SPOTIFY_CLIENT_ID or SPOTIFY_REDIRECT_URI in settings.")

    params = {
        "response_type": "code",
        "client_id": settings.SPOTIFY_CLIENT_ID,
        "scope": SCOPES,
        "redirect_uri": settings.SPOTIFY_REDIRECT_URI,
        "state": state,
        "show_dialog": "false",
    }
    req = requests.Request("GET", AUTH_URL, params=params).prepare()
    return req.url


def exchange_code_for_token(code: str) -> dict:
    """
    Exchange authorization code for access + refresh tokens.
    Returns payload with expires_at added.
    """
    if not settings.SPOTIFY_CLIENT_ID or not settings.SPOTIFY_CLIENT_SECRET or not settings.SPOTIFY_REDIRECT_URI:
        raise RuntimeError("Missing Spotify credentials in settings.")

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.SPOTIFY_REDIRECT_URI,
        "client_id": settings.SPOTIFY_CLIENT_ID,
        "client_secret": settings.SPOTIFY_CLIENT_SECRET,
    }
    r = requests.post(TOKEN_URL, data=data, timeout=15)
    r.raise_for_status()

    payload = r.json()
    payload["expires_at"] = int(time.time()) + int(payload.get("expires_in", 3600))
    return payload


def refresh_access_token(refresh_token: str) -> dict:
    """
    Use refresh token to get a new access token.
    """
    if not settings.SPOTIFY_CLIENT_ID or not settings.SPOTIFY_CLIENT_SECRET:
        raise RuntimeError("Missing Spotify credentials in settings.")

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": settings.SPOTIFY_CLIENT_ID,
        "client_secret": settings.SPOTIFY_CLIENT_SECRET,
    }
    r = requests.post(TOKEN_URL, data=data, timeout=15)
    r.raise_for_status()

    payload = r.json()
    payload["expires_at"] = int(time.time()) + int(payload.get("expires_in", 3600))
    return payload


def spotify_get(url: str, access_token: str) -> requests.Response:
    """
    Helper for GET calls to Spotify API.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    return requests.get(url, headers=headers, timeout=15)

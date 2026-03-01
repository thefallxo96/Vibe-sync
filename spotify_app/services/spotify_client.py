import time
import requests
from django.conf import settings

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE = "https://api.spotify.com/v1"

SCOPES = (
    "streaming user-read-playback-state user-modify-playback-state user-read-currently-playing "
    "playlist-modify-private playlist-modify-public "
    "user-read-recently-played user-top-read"
)


def spotify_get(url: str, access_token: str) -> requests.Response:
    headers = {"Authorization": f"Bearer {access_token}"}
    return requests.get(url, headers=headers, timeout=15)


def spotify_put(url: str, access_token: str, json: dict | None = None) -> requests.Response:
    headers = {"Authorization": f"Bearer {access_token}"}
    return requests.put(url, headers=headers, json=json, timeout=15)


def spotify_post(url: str, access_token: str, json: dict | None = None) -> requests.Response:
    headers = {"Authorization": f"Bearer {access_token}"}
    return requests.post(url, headers=headers, json=json, timeout=15)


def spotify_delete(url: str, access_token: str, json: dict | None = None) -> requests.Response:
    headers = {"Authorization": f"Bearer {access_token}"}
    return requests.delete(url, headers=headers, json=json, timeout=15)


def get_login_url(state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": settings.SPOTIFY_CLIENT_ID,
        "scope": SCOPES,
        "redirect_uri": settings.SPOTIFY_REDIRECT_URI,
        "state": state,
        "show_dialog": "true",
    }
    return requests.Request("GET", AUTH_URL, params=params).prepare().url


def exchange_code_for_token(code: str) -> dict:
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
    payload["expires_at"] = int(time.time()) + payload.get("expires_in", 3600)
    return payload


def refresh_access_token(refresh_token: str) -> dict:
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": settings.SPOTIFY_CLIENT_ID,
        "client_secret": settings.SPOTIFY_CLIENT_SECRET,
    }
    r = requests.post(TOKEN_URL, data=data, timeout=15)
    r.raise_for_status()
    payload = r.json()
    payload["expires_at"] = int(time.time()) + payload.get("expires_in", 3600)
    return payload


def get_now_playing(access_token: str) -> dict | None:
    r = spotify_get(f"{API_BASE}/me/player/currently-playing", access_token)
    if r.status_code == 204:
        return None
    r.raise_for_status()
    return r.json()


def get_player_state(access_token: str) -> dict | None:
    r = spotify_get(f"{API_BASE}/me/player", access_token)
    if r.status_code == 204:
        return None
    r.raise_for_status()
    return r.json()


def get_audio_features(track_id: str, access_token: str) -> dict | None:
    r = spotify_get(f"{API_BASE}/audio-features/{track_id}", access_token)
    if r.status_code == 403:
        return None
    r.raise_for_status()
    return r.json()


def spotify_get_audio_features_bulk(access_token: str, track_ids: list[str]) -> dict:
    if not track_ids:
        return {"audio_features": []}
    ids = ",".join(track_ids[:100])
    r = spotify_get(f"{API_BASE}/audio-features?ids={ids}", access_token)
    if r.status_code == 403:
        return {"audio_features": []}
    r.raise_for_status()
    return r.json()


def spotify_get_devices(access_token: str) -> dict:
    r = spotify_get(f"{API_BASE}/me/player/devices", access_token)
    r.raise_for_status()
    return r.json()


def spotify_transfer_playback(access_token: str, device_id: str, play: bool = True) -> None:
    body = {"device_ids": [device_id], "play": play}
    r = spotify_put(f"{API_BASE}/me/player", access_token, json=body)
    r.raise_for_status()


def spotify_play(access_token: str, device_id: str | None = None) -> None:
    url = f"{API_BASE}/me/player/play"
    if device_id:
        url += f"?device_id={device_id}"
    r = spotify_put(url, access_token)
    r.raise_for_status()


def spotify_play_uri(access_token: str, track_uri: str, device_id: str | None = None) -> None:
    url = f"{API_BASE}/me/player/play"
    if device_id:
        url += f"?device_id={device_id}"
    body = {"uris": [track_uri]}
    r = spotify_put(url, access_token, json=body)
    r.raise_for_status()


def spotify_play_uris(access_token: str, track_uris: list[str], device_id: str | None = None) -> None:
    url = f"{API_BASE}/me/player/play"
    if device_id:
        url += f"?device_id={device_id}"
    body = {"uris": track_uris}
    r = spotify_put(url, access_token, json=body)
    r.raise_for_status()


def spotify_pause(access_token: str, device_id: str | None = None) -> None:
    url = f"{API_BASE}/me/player/pause"
    if device_id:
        url += f"?device_id={device_id}"
    r = spotify_put(url, access_token)
    r.raise_for_status()


def spotify_next(access_token: str, device_id: str | None = None) -> None:
    url = f"{API_BASE}/me/player/next"
    if device_id:
        url += f"?device_id={device_id}"
    r = spotify_post(url, access_token)
    r.raise_for_status()


def spotify_previous(access_token: str, device_id: str | None = None) -> None:
    url = f"{API_BASE}/me/player/previous"
    if device_id:
        url += f"?device_id={device_id}"
    r = spotify_post(url, access_token)
    r.raise_for_status()


def spotify_set_volume(access_token: str, volume_percent: int, device_id: str | None = None) -> None:
    url = f"{API_BASE}/me/player/volume?volume_percent={volume_percent}"
    if device_id:
        url += f"&device_id={device_id}"
    r = spotify_put(url, access_token)
    r.raise_for_status()


def spotify_queue_track(access_token: str, track_uri: str, device_id: str | None = None) -> None:
    url = f"{API_BASE}/me/player/queue?uri={track_uri}"
    if device_id:
        url += f"&device_id={device_id}"
    r = spotify_post(url, access_token)
    r.raise_for_status()


def spotify_set_repeat(access_token: str, state: str, device_id: str | None = None) -> None:
    # state: off, track, context
    url = f"{API_BASE}/me/player/repeat?state={state}"
    if device_id:
        url += f"&device_id={device_id}"
    r = spotify_put(url, access_token)
    r.raise_for_status()


def spotify_get_me(access_token: str) -> dict:
    r = spotify_get(f"{API_BASE}/me", access_token)
    r.raise_for_status()
    return r.json()


def spotify_create_playlist(access_token: str, user_id: str, name: str) -> dict:
    url = f"{API_BASE}/users/{user_id}/playlists"
    body = {"name": name, "public": False, "description": "Created by VibeSync"}
    r = requests.post(url, headers={"Authorization": f"Bearer {access_token}"}, json=body, timeout=15)
    r.raise_for_status()
    return r.json()


def spotify_add_tracks(access_token: str, playlist_id: str, track_uri: str) -> None:
    url = f"{API_BASE}/playlists/{playlist_id}/tracks"
    body = {"uris": [track_uri]}
    r = requests.post(url, headers={"Authorization": f"Bearer {access_token}"}, json=body, timeout=15)
    r.raise_for_status()


def spotify_playlist_has_track(access_token: str, playlist_id: str, track_id: str) -> bool:
    offset = 0
    while offset < 200:
        url = f"{API_BASE}/playlists/{playlist_id}/tracks?fields=items(track(id))&limit=100&offset={offset}"
        r = spotify_get(url, access_token)
        r.raise_for_status()
        items = r.json().get("items", [])
        if any(i.get("track", {}).get("id") == track_id for i in items):
            return True
        if len(items) < 100:
            break
        offset += 100
    return False


def spotify_remove_track(access_token: str, playlist_id: str, track_uri: str) -> None:
    url = f"{API_BASE}/playlists/{playlist_id}/tracks"
    body = {"tracks": [{"uri": track_uri}]}
    r = spotify_delete(url, access_token, json=body)
    r.raise_for_status()


def spotify_get_recommendations(
    access_token: str,
    seed_tracks: list[str],
    seed_artists: list[str],
    seed_genres: list[str],
    params: dict,
) -> dict:
    url = f"{API_BASE}/recommendations"
    query = []
    if seed_tracks:
        query.append("seed_tracks=" + ",".join(seed_tracks))
    if seed_artists:
        query.append("seed_artists=" + ",".join(seed_artists))
    if seed_genres:
        query.append("seed_genres=" + ",".join(seed_genres))
    for k, v in params.items():
        query.append(f"{k}={v}")
    url += "?" + "&".join(query)
    r = spotify_get(url, access_token)
    r.raise_for_status()
    return r.json()


def spotify_get_available_genre_seeds(access_token: str) -> dict:
    r = spotify_get(f"{API_BASE}/recommendations/available-genre-seeds", access_token)
    if r.status_code == 404:
        return {"genres": []}
    r.raise_for_status()
    return r.json()


def spotify_get_recently_played(access_token: str, limit: int = 20) -> dict:
    url = f"{API_BASE}/me/player/recently-played?limit={limit}"
    r = spotify_get(url, access_token)
    r.raise_for_status()
    return r.json()


def spotify_get_top_tracks(access_token: str, time_range: str = "medium_term", limit: int = 20) -> dict:
    url = f"{API_BASE}/me/top/tracks?time_range={time_range}&limit={limit}"
    r = spotify_get(url, access_token)
    r.raise_for_status()
    return r.json()


def spotify_get_top_artists(access_token: str, time_range: str = "medium_term", limit: int = 20) -> dict:
    url = f"{API_BASE}/me/top/artists?time_range={time_range}&limit={limit}"
    r = spotify_get(url, access_token)
    r.raise_for_status()
    return r.json()


def spotify_search_tracks(access_token: str, query: str, limit: int = 10, market: str | None = None) -> dict:
    q = query.replace(" ", "%20")
    url = f"{API_BASE}/search?type=track&q={q}&limit={limit}"
    if market:
        url += f"&market={market}"
    r = spotify_get(url, access_token)
    r.raise_for_status()
    return r.json()

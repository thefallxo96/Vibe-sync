import secrets
import time
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.urls import reverse

from .models import Mood, MoodEntry
from .services.spotify_client import (
    get_login_url,
    exchange_code_for_token,
    refresh_access_token,
    spotify_get,
    get_now_playing,
    get_audio_features,
    get_player_state,
    spotify_play,
    spotify_pause,
    spotify_set_volume,
    spotify_get_devices,
    spotify_transfer_playback,
    spotify_get_me,
    spotify_create_playlist,
    spotify_add_tracks,
    API_BASE,
)


def home(request):
    authed = bool(request.session.get("spotify_access_token"))
    return render(request, "spotify_app/home.html", {"authed": authed})


def _get_or_create_mood(name: str) -> Mood:
    mood, _ = Mood.objects.get_or_create(name=name)
    return mood


def spotify_login(request):
    state = request.session.get("spotify_oauth_state")
    if not state:
        state = secrets.token_urlsafe(16)
        request.session["spotify_oauth_state"] = state

    request.session.modified = True
    request.session.save()
    return redirect(get_login_url(state))


def spotify_callback(request):
    code = request.GET.get("code")
    returned_state = request.GET.get("state")
    session_state = request.session.get("spotify_oauth_state")

    if not code:
        return JsonResponse({"error": "Missing authorization code"}, status=400)

    if not returned_state or not session_state:
        return JsonResponse({"error": "OAuth state missing. Use one tab + only 127.0.0.1."}, status=400)

    if returned_state != session_state:
        return JsonResponse({"error": "Invalid OAuth state. Start over from /spotify/ and click once."}, status=400)

    token_data = exchange_code_for_token(code)

    request.session["spotify_access_token"] = token_data["access_token"]
    request.session["spotify_refresh_token"] = token_data.get("refresh_token")
    request.session["spotify_expires_at"] = token_data["expires_at"]

    request.session.pop("spotify_oauth_state", None)
    request.session.modified = True
    request.session.save()

    return redirect(reverse("spotify_home"))


def spotify_logout(request):
    for k in ["spotify_access_token", "spotify_refresh_token", "spotify_expires_at", "spotify_oauth_state"]:
        request.session.pop(k, None)
    request.session.modified = True
    request.session.save()
    return redirect(reverse("spotify_home"))


def _get_access_token(request):
    token = request.session.get("spotify_access_token")
    refresh = request.session.get("spotify_refresh_token")
    expires_at = int(request.session.get("spotify_expires_at") or 0)

    if not token:
        return None

    if int(time.time()) > (expires_at - 60):
        if not refresh:
            return None
        new_data = refresh_access_token(refresh)
        request.session["spotify_access_token"] = new_data["access_token"]
        request.session["spotify_expires_at"] = new_data["expires_at"]
        token = new_data["access_token"]
        request.session.modified = True
        request.session.save()

    return token


def _get_device_id(token: str) -> str | None:
    devices = spotify_get_devices(token).get("devices", [])
    active = next((d for d in devices if d.get("is_active")), None)
    if active:
        return active.get("id")
    return devices[0].get("id") if devices else None


def api_token(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)
    return JsonResponse({"authenticated": True, "access_token": token})


def api_transfer(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)

    device_id = request.GET.get("device_id")
    if not device_id:
        return JsonResponse({"error": "Missing device_id"}, status=400)

    spotify_transfer_playback(token, device_id, play=True)
    return JsonResponse({"ok": True, "device_id": device_id})


def api_now_playing(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)

    payload = get_now_playing(token)
    if payload is None:
        player = get_player_state(token)
        return JsonResponse({"playing": False, "message": "Nothing is playing right now.", "player_state": player})

    item = payload.get("item") or {}

    track = {
        "id": item.get("id"),
        "name": item.get("name"),
        "artists": [a.get("name") for a in item.get("artists", [])],
        "album": (item.get("album") or {}).get("name"),
        "spotify_url": (item.get("external_urls") or {}).get("spotify"),
        "is_playing": payload.get("is_playing"),
        "image": ((item.get("album") or {}).get("images") or [{}])[0].get("url"),
        "progress_ms": payload.get("progress_ms"),
        "duration_ms": item.get("duration_ms"),
        "uri": item.get("uri"),
    }

    return JsonResponse({"playing": True, "track": track})


def _mood_from_features(f: dict) -> str:
    if not f:
        return "unknown"
    valence = float(f.get("valence") or 0.0)
    energy = float(f.get("energy") or 0.0)
    dance = float(f.get("danceability") or 0.0)
    tempo = float(f.get("tempo") or 0.0)

    if energy >= 0.75 and dance >= 0.65 and valence >= 0.55:
        return "hype"
    if energy >= 0.70 and valence <= 0.35:
        return "menacing"
    if valence <= 0.30 and energy <= 0.50:
        return "sad"
    if energy <= 0.45 and (tempo and tempo <= 110):
        return "chill"
    if valence >= 0.55 and energy <= 0.65:
        return "romantic"
    return "neutral"


def api_play(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)

    device_id = request.GET.get("device_id") or _get_device_id(token)
    if not device_id:
        return JsonResponse({"ok": False, "error": "No active Spotify device found."}, status=400)

    spotify_play(token, device_id=device_id)
    return JsonResponse({"ok": True, "action": "play", "device_id": device_id})


def api_pause(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)

    device_id = request.GET.get("device_id") or _get_device_id(token)
    if not device_id:
        return JsonResponse({"ok": False, "error": "No active Spotify device found."}, status=400)

    spotify_pause(token, device_id=device_id)
    return JsonResponse({"ok": True, "action": "pause", "device_id": device_id})


def api_volume(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)

    v = int(request.GET.get("v", 50))
    v = max(0, min(100, v))

    device_id = request.GET.get("device_id") or _get_device_id(token)
    if not device_id:
        return JsonResponse({"ok": False, "error": "No active Spotify device found."}, status=400)

    spotify_set_volume(token, v, device_id=device_id)
    return JsonResponse({"ok": True, "volume": v, "device_id": device_id})


def api_devices(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)
    return JsonResponse({"ok": True, "devices": spotify_get_devices(token)})


def api_add_to_app_mood(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)

    mood_name = request.GET.get("mood")
    if not mood_name:
        return JsonResponse({"error": "Missing mood"}, status=400)

    payload = get_now_playing(token)
    if not payload:
        return JsonResponse({"error": "Nothing playing"}, status=400)

    item = payload.get("item") or {}
    track_id = item.get("id")

    mood = _get_or_create_mood(mood_name)

    entry = MoodEntry.objects.create(
        mood=mood,
        track_id=track_id,
        track_name=item.get("name") or "",
        artists=", ".join(a.get("name") for a in item.get("artists", [])),
        album=(item.get("album") or {}).get("name") or "",
        image=((item.get("album") or {}).get("images") or [{}])[0].get("url") or "",
        spotify_url=(item.get("external_urls") or {}).get("spotify") or "",
    )

    return JsonResponse({"ok": True, "mood": mood.name, "entry_id": entry.id})


def api_add_to_spotify_playlist(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)

    mood_name = request.GET.get("mood")
    if not mood_name:
        return JsonResponse({"error": "Missing mood"}, status=400)

    payload = get_now_playing(token)
    if not payload:
        return JsonResponse({"error": "Nothing playing"}, status=400)

    item = payload.get("item") or {}
    track_id = item.get("id")
    track_uri = item.get("uri")

    mood = _get_or_create_mood(mood_name)

    if not mood.spotify_playlist_id:
        me = spotify_get_me(token)
        playlist = spotify_create_playlist(token, me["id"], f"VibeSync • {mood.name}")
        mood.spotify_playlist_id = playlist["id"]
        mood.save()

    spotify_add_tracks(token, mood.spotify_playlist_id, track_uri)
    return JsonResponse({"ok": True, "playlist_id": mood.spotify_playlist_id, "mood": mood.name})


def api_add_to_both(request):
    mood_name = request.GET.get("mood")
    if not mood_name:
        return JsonResponse({"error": "Missing mood"}, status=400)

    app_res = api_add_to_app_mood(request)
    if app_res.status_code != 200:
        return app_res

    return api_add_to_spotify_playlist(request)


def api_vibe(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)

    payload = get_now_playing(token)
    if payload is None:
        player = get_player_state(token)
        return JsonResponse({"playing": False, "message": "Nothing is playing right now.", "player_state": player})

    item = payload.get("item") or {}
    track_id = item.get("id")

    track = {
        "id": track_id,
        "name": item.get("name"),
        "artists": [a.get("name") for a in item.get("artists", [])],
        "album": (item.get("album") or {}).get("name"),
        "spotify_url": (item.get("external_urls") or {}).get("spotify"),
        "is_playing": payload.get("is_playing"),
        "image": ((item.get("album") or {}).get("images") or [{}])[0].get("url"),
        "progress_ms": payload.get("progress_ms"),
        "duration_ms": item.get("duration_ms"),
    }

    if not track_id:
        return JsonResponse({"playing": True, "track": track, "mood": "unknown", "audio_features": None})

    features = get_audio_features(track_id, token)
    if not features:
        return JsonResponse({
            "playing": True,
            "track": track,
            "mood": "unknown",
            "audio_features": None,
            "warning": "Audio features unavailable for this track."
        })

    mood = _mood_from_features(features)

    return JsonResponse({
        "playing": True,
        "track": track,
        "mood": mood,
        "audio_features": {
            "danceability": features.get("danceability"),
            "energy": features.get("energy"),
            "valence": features.get("valence"),
            "tempo": features.get("tempo"),
            "acousticness": features.get("acousticness"),
            "instrumentalness": features.get("instrumentalness"),
            "liveness": features.get("liveness"),
            "speechiness": features.get("speechiness"),
        }
    })

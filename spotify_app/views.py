import secrets
import time
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.urls import reverse
from django.db import models
from .services.spotify_client import (
    # ...
    spotify_next,
    spotify_previous,
    spotify_queue_track,
)


from .models import Mood, MoodEntry, TrackHistory
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
    spotify_remove_track,
    spotify_playlist_has_track,
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


def _log_history_if_new(request, track):
    last_id = request.session.get("last_track_id")
    if track.get("id") and track["id"] != last_id:
        TrackHistory.objects.create(
            track_id=track["id"],
            track_name=track.get("name") or "",
            artists=", ".join(track.get("artists") or []),
            album=track.get("album") or "",
            image=track.get("image") or "",
            spotify_url=track.get("spotify_url") or "",
        )
        request.session["last_track_id"] = track["id"]
        request.session.modified = True


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

def api_me(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)

    r = spotify_get(f"{API_BASE}/me", token)
    if r.status_code != 200:
        return JsonResponse({"error": "Failed to fetch profile", "details": r.text}, status=400)

    return JsonResponse({"authenticated": True, "profile": r.json()})



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

def api_next(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)

    device_id = request.GET.get("device_id") or _get_device_id(token)
    if not device_id:
        return JsonResponse({"ok": False, "error": "No active Spotify device found."}, status=400)

    spotify_next(token, device_id=device_id)
    return JsonResponse({"ok": True, "action": "next", "device_id": device_id})


def api_previous(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)

    device_id = request.GET.get("device_id") or _get_device_id(token)
    if not device_id:
        return JsonResponse({"ok": False, "error": "No active Spotify device found."}, status=400)

    spotify_previous(token, device_id=device_id)
    return JsonResponse({"ok": True, "action": "previous", "device_id": device_id})


def api_queue(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)

    track_uri = request.GET.get("uri")
    if not track_uri:
        return JsonResponse({"ok": False, "error": "Missing uri"}, status=400)

    device_id = request.GET.get("device_id") or _get_device_id(token)
    if not device_id:
        return JsonResponse({"ok": False, "error": "No active Spotify device found."}, status=400)

    spotify_queue_track(token, track_uri, device_id=device_id)
    return JsonResponse({"ok": True, "action": "queue", "uri": track_uri, "device_id": device_id})


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

    if MoodEntry.objects.filter(mood=mood, track_id=track_id).exists():
        return JsonResponse({"ok": True, "mood": mood.name, "duplicate": True})

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

    if spotify_playlist_has_track(token, mood.spotify_playlist_id, track_id):
        return JsonResponse({"ok": True, "mood": mood.name, "duplicate": True})

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


def api_remove_from_app_mood(request):
    mood_name = request.GET.get("mood")
    track_id = request.GET.get("track_id")
    if not mood_name or not track_id:
        return JsonResponse({"error": "Missing mood or track_id"}, status=400)

    mood = Mood.objects.filter(name=mood_name).first()
    if not mood:
        return JsonResponse({"ok": False, "error": "Mood not found"}, status=404)

    deleted, _ = MoodEntry.objects.filter(mood=mood, track_id=track_id).delete()
    return JsonResponse({"ok": True, "deleted": deleted})


def api_remove_from_spotify_playlist(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)

    mood_name = request.GET.get("mood")
    track_uri = request.GET.get("track_uri")
    if not mood_name or not track_uri:
        return JsonResponse({"error": "Missing mood or track_uri"}, status=400)

    mood = Mood.objects.filter(name=mood_name).first()
    if not mood or not mood.spotify_playlist_id:
        return JsonResponse({"ok": False, "error": "Playlist not found"}, status=404)

    spotify_remove_track(token, mood.spotify_playlist_id, track_uri)
    return JsonResponse({"ok": True, "playlist_id": mood.spotify_playlist_id})


def api_mood_board(request):
    moods = Mood.objects.prefetch_related("entries").all().order_by("name")
    data = []
    for m in moods:
        data.append({
            "name": m.name,
            "entries": [
                {
                    "track_name": e.track_name,
                    "artists": e.artists,
                    "album": e.album,
                    "image": e.image,
                    "spotify_url": e.spotify_url,
                    "added_at": e.added_at.isoformat(),
                    "track_id": e.track_id,
                }
                for e in m.entries.order_by("-added_at")
            ],
        })
    return JsonResponse({"moods": data})


def api_history(request):
    items = TrackHistory.objects.order_by("-played_at")[:20]
    return JsonResponse({
        "history": [
            {
                "track_name": i.track_name,
                "artists": i.artists,
                "album": i.album,
                "image": i.image,
                "spotify_url": i.spotify_url,
                "played_at": i.played_at.isoformat(),
            }
            for i in items
        ]
    })


def api_analytics(request):
    mood_counts = (
        MoodEntry.objects.values("mood__name")
        .order_by()
        .annotate(count=models.Count("id"))
        .order_by("-count")
    )

    artist_counts = (
        MoodEntry.objects.values("mood__name", "artists")
        .order_by()
        .annotate(count=models.Count("id"))
        .order_by("-count")[:50]
    )

    return JsonResponse({"moods": list(mood_counts), "artists": list(artist_counts)})


def api_goal_mood(request):
    goal = request.GET.get("goal")
    if not goal:
        return JsonResponse({"error": "Missing goal"}, status=400)

    entries = MoodEntry.objects.filter(mood__name__iexact=goal).order_by("-added_at")[:20]
    return JsonResponse({
        "goal": goal,
        "tracks": [
            {
                "track_name": e.track_name,
                "artists": e.artists,
                "album": e.album,
                "image": e.image,
                "spotify_url": e.spotify_url,
            }
            for e in entries
        ],
    })


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

    _log_history_if_new(request, track)

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

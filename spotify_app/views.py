import secrets
import time
import random
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.urls import reverse
from django.db import models
from .models import Mood, MoodEntry, TrackHistory
from .services.spotify_client import spotify_search_tracks
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
    spotify_play_uri,
    spotify_play_uris,
    spotify_next,
    spotify_previous,
    spotify_queue_track,
    spotify_get_recommendations,
    spotify_get_available_genre_seeds,
    spotify_get_audio_features_bulk,
    spotify_get_recently_played,
    spotify_get_top_tracks,
    spotify_get_top_artists,
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


def _recommend_params_for_mood(mood: str, intensity: int = 50) -> dict:
    t = max(0, min(100, intensity)) / 100.0
    m = (mood or "neutral").lower()
    if m == "hype":
        return {
            "limit": 25,
            "target_energy": 0.65 + 0.35 * t,
            "min_energy": 0.45 + 0.25 * t,
            "target_danceability": 0.55 + 0.35 * t,
            "min_danceability": 0.40 + 0.20 * t,
            "target_valence": 0.55 + 0.25 * t,
            "min_valence": 0.35 + 0.15 * t,
            "target_tempo": 115 + 35 * t,
            "min_popularity": int(35 + 35 * t),
        }
    if m == "menacing":
        return {
            "limit": 25,
            "target_energy": 0.55 + 0.45 * t,
            "min_energy": 0.35 + 0.30 * t,
            "target_valence": 0.35 - 0.25 * t,
            "max_valence": 0.55 - 0.20 * t,
            "target_loudness": -12 + 7 * t,
            "target_tempo": 95 + 40 * t,
            "min_popularity": int(20 + 30 * t),
        }
    if m == "sad":
        return {
            "limit": 25,
            "target_energy": 0.45 - 0.25 * t,
            "max_energy": 0.65 - 0.20 * t,
            "target_valence": 0.35 - 0.25 * t,
            "max_valence": 0.55 - 0.15 * t,
            "target_acousticness": 0.35 + 0.5 * t,
            "min_acousticness": 0.20 + 0.30 * t,
            "target_tempo": 110 - 30 * t,
            "max_popularity": int(85 - 25 * t),
        }
    if m == "chill":
        return {
            "limit": 25,
            "target_energy": 0.55 - 0.35 * t,
            "max_energy": 0.70 - 0.25 * t,
            "target_valence": 0.55 - 0.15 * t,
            "target_tempo": 120 - 35 * t,
            "target_acousticness": 0.3 + 0.35 * t,
            "max_popularity": int(90 - 20 * t),
        }
    if m == "romantic":
        return {
            "limit": 25,
            "target_energy": 0.6 - 0.25 * t,
            "target_valence": 0.6 + 0.25 * t,
            "min_valence": 0.45 + 0.20 * t,
            "target_acousticness": 0.25 + 0.45 * t,
            "target_tempo": 105 - 20 * t,
            "min_popularity": int(25 + 30 * t),
        }
    return {
        "limit": 25,
        "target_energy": 0.55,
        "target_valence": 0.5,
        "target_danceability": 0.5,
        "min_popularity": 20,
        "max_popularity": 95,
    }


def _weighted_genres_for_mood(mood: str, intensity: int) -> list[str]:
    t = max(0, min(100, intensity)) / 100.0
    m = (mood or "neutral").lower()
    low = {
        "hype": ["pop", "dance", "hip-hop", "electronic", "house"],
        "menacing": ["metal", "industrial", "rock", "techno", "dubstep"],
        "sad": ["acoustic", "piano", "soul", "folk", "ambient"],
        "chill": ["chill", "ambient", "jazz", "downtempo", "acoustic"],
        "romantic": ["r-n-b", "soul", "latin", "pop", "acoustic"],
        "neutral": ["pop", "indie", "alternative", "electronic", "rock"],
    }
    high = {
        "hype": ["edm", "trap", "dance", "electronic", "house"],
        "menacing": ["metal", "industrial", "techno", "dubstep", "rock"],
        "sad": ["acoustic", "piano", "singer-songwriter", "ambient", "soul"],
        "chill": ["ambient", "chill", "downtempo", "jazz", "acoustic"],
        "romantic": ["r-n-b", "latin", "soul", "pop", "acoustic"],
        "neutral": ["pop", "indie", "alternative", "electronic", "rock"],
    }
    base = low.get(m, low["neutral"])
    boost = high.get(m, high["neutral"])
    count_boost = max(1, min(4, round(t * 4)))
    picked = boost[:count_boost] + base[: (5 - count_boost)]
    seen = set()
    out = []
    for g in picked:
        if g not in seen:
            out.append(g)
            seen.add(g)
    return out[:5]


def _top_artist_genres(token: str, available: list[str]) -> list[str]:
    top_artists = spotify_get_top_artists(token, time_range="medium_term", limit=20).get("items", [])
    counts: dict[str, int] = {}
    for a in top_artists:
        for g in a.get("genres", []):
            if g not in available:
                continue
            counts[g] = counts.get(g, 0) + 1
    ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    return [g for g, _ in ranked][:5]


def _score_track(features: dict, params: dict) -> float:
    if not features:
        return 999.0
    score = 0.0
    for key, target in params.items():
        if not key.startswith("target_"):
            continue
        feat_key = key.replace("target_", "")
        val = features.get(feat_key)
        if val is None:
            continue
        score += abs(float(val) - float(target))
    return score


def _dedupe_by_artist(tracks: list[dict], max_items: int) -> list[dict]:
    seen = set()
    out = []
    for t in tracks:
        artists = t.get("artists") or []
        artist_id = (artists[0].get("id") if artists else None)
        if artist_id and artist_id in seen:
            continue
        if artist_id:
            seen.add(artist_id)
        out.append(t)
        if len(out) >= max_items:
            break
    return out


def api_recommend(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)

    mood = request.GET.get("mood", "neutral")
    intensity = int(request.GET.get("intensity", 50))
    limit = max(10, min(50, int(request.GET.get("limit", 25))))
    params = _recommend_params_for_mood(mood, intensity)
    weighted_genres = _weighted_genres_for_mood(mood, intensity)

    current_track = request.GET.get("current_track") or ""
    current_track = current_track.strip()

    try:
        me = spotify_get_me(token)
        market = me.get("country", "US")
        params["market"] = market

        available = spotify_get_available_genre_seeds(token).get("genres", [])
        mood_genres = [g for g in weighted_genres if g in available] if available else weighted_genres[:]
        personal_genres = _top_artist_genres(token, available) if available else []
        if not mood_genres:
            mood_genres = weighted_genres[:]

        random.shuffle(mood_genres)
        random.shuffle(personal_genres)

        t = max(0, min(100, intensity)) / 100.0
        mood_slots = max(2, min(4, round(2 + 2 * t)))
        personal_slots = max(1, 5 - mood_slots)
        seed_genres = (mood_genres[:mood_slots] + personal_genres[:personal_slots])[:5]

        recent = spotify_get_recently_played(token, limit=20)
        recent_items = recent.get("items", [])
        recent_tracks = [i.get("track") for i in recent_items if i.get("track")]
        recent_track_ids = [t.get("id") for t in recent_tracks if t and t.get("id")]
        recent_artist_ids = []
        for t in recent_tracks:
            recent_artist_ids.extend([a.get("id") for a in (t.get("artists") or []) if a.get("id")])

        seed_tracks = []
        seed_artists = []
        seed_source = "recent"

        if len(recent_track_ids) >= 2:
            seed_tracks = recent_track_ids[:2]
            seed_artists = recent_artist_ids[:2]
        else:
            top_tracks = spotify_get_top_tracks(token, time_range="short_term", limit=20).get("items", [])
            top_artists = spotify_get_top_artists(token, time_range="short_term", limit=20).get("items", [])
            seed_source = "top"
            seed_tracks = [t.get("id") for t in top_tracks if t.get("id")][:2]
            seed_artists = [a.get("id") for a in top_artists if a.get("id")][:2]

        seeds_count = len(seed_tracks) + len(seed_artists)
        seed_genres = seed_genres[: max(1, 5 - seeds_count)]

        rec = spotify_get_recommendations(
            token,
            seed_tracks=seed_tracks,
            seed_artists=seed_artists,
            seed_genres=seed_genres,
            params={**params, "limit": 50},
        )
        rec_tracks = rec.get("tracks", [])

        recent_set = set(recent_track_ids)
        if current_track:
            recent_set.add(current_track)

        filtered_tracks = [t for t in rec_tracks if t.get("id") not in recent_set]
        if filtered_tracks:
            rec_tracks = filtered_tracks

        rec_track_ids = [t.get("id") for t in rec_tracks if t.get("id")]
        features_bulk = spotify_get_audio_features_bulk(token, rec_track_ids) if rec_track_ids else {}
        features_map = {f.get("id"): f for f in features_bulk.get("audio_features", []) if f}

        if features_map:
            ranked = []
            for t in rec_tracks:
                f = features_map.get(t.get("id"))
                score = _score_track(f, params)
                jitter = random.uniform(0.0, 0.10 + 0.25 * (intensity / 100.0))
                ranked.append((score + jitter, t))
            ranked.sort(key=lambda x: x[0])
            ranked_tracks = [t for _, t in ranked]
        else:
            ranked_tracks = rec_tracks

        random.shuffle(ranked_tracks)
        diverse = _dedupe_by_artist(ranked_tracks, limit)

        why = (
            f"Matched mood {mood.title()} (intensity {intensity}). "
            f"Seeds: {seed_source} tracks/artists. "
            f"Genres: {', '.join(seed_genres)}. "
            f"Ranked by audio features."
        )
        tracks = [
            {
                "id": t.get("id"),
                "name": t.get("name"),
                "uri": t.get("uri"),
                "artists": [a.get("name") for a in t.get("artists", [])],
                "image": ((t.get("album") or {}).get("images") or [{}])[0].get("url"),
                "spotify_url": (t.get("external_urls") or {}).get("spotify"),
                "why": why,
            }
            for t in diverse
            if t.get("id")
        ]
        return JsonResponse({"ok": True, "mood": mood, "tracks": tracks, "source": "recommendations"})
    except Exception:
        top_tracks = spotify_get_top_tracks(token, time_range="medium_term", limit=30).get("items", [])
        track_ids = [t.get("id") for t in top_tracks if t.get("id")]
        features_bulk = spotify_get_audio_features_bulk(token, track_ids) if track_ids else {}
        features_map = {f.get("id"): f for f in features_bulk.get("audio_features", []) if f}

        if features_map:
            ranked = []
            for t in top_tracks:
                f = features_map.get(t.get("id"))
                score = _score_track(f, params)
                ranked.append((score, t))
            ranked.sort(key=lambda x: x[0])
            ranked_tracks = [t for _, t in ranked]
        else:
            ranked_tracks = top_tracks

        random.shuffle(ranked_tracks)
        diverse = _dedupe_by_artist(ranked_tracks, 15)

        why = f"Ranked your top tracks by mood features for {mood.title()} (intensity {intensity})."
        tracks = [
            {
                "id": t.get("id"),
                "name": t.get("name"),
                "uri": t.get("uri"),
                "artists": [a.get("name") for a in t.get("artists", [])],
                "image": ((t.get("album") or {}).get("images") or [{}])[0].get("url"),
                "spotify_url": (t.get("external_urls") or {}).get("spotify"),
                "why": why,
            }
            for t in diverse
            if t.get("id")
        ]
        return JsonResponse({"ok": True, "mood": mood, "tracks": tracks, "source": "top_tracks_fallback"})


# --- PLAYBACK + QUEUE ---
def api_play(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)
    device_id = request.GET.get("device_id") or _get_device_id(token)
    if not device_id:
        return JsonResponse({"ok": False, "error": "No active Spotify device found."}, status=400)
    spotify_play(token, device_id=device_id)
    return JsonResponse({"ok": True})

def api_pause(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)
    device_id = request.GET.get("device_id") or _get_device_id(token)
    if not device_id:
        return JsonResponse({"ok": False, "error": "No active Spotify device found."}, status=400)
    spotify_pause(token, device_id=device_id)
    return JsonResponse({"ok": True})

def api_next(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)
    device_id = request.GET.get("device_id") or _get_device_id(token)
    if not device_id:
        return JsonResponse({"ok": False, "error": "No active Spotify device found."}, status=400)
    spotify_next(token, device_id=device_id)
    return JsonResponse({"ok": True})

def api_previous(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)
    device_id = request.GET.get("device_id") or _get_device_id(token)
    if not device_id:
        return JsonResponse({"ok": False, "error": "No active Spotify device found."}, status=400)
    spotify_previous(token, device_id=device_id)
    return JsonResponse({"ok": True})

def api_queue(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)
    uri = request.GET.get("uri")
    if not uri:
        return JsonResponse({"error": "Missing uri"}, status=400)
    device_id = request.GET.get("device_id") or _get_device_id(token)
    if not device_id:
        return JsonResponse({"ok": False, "error": "No active Spotify device found."}, status=400)
    spotify_queue_track(token, uri, device_id=device_id)
    return JsonResponse({"ok": True})

def api_play_uri(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)
    uri = request.GET.get("uri")
    if not uri:
        return JsonResponse({"error": "Missing uri"}, status=400)
    device_id = request.GET.get("device_id") or _get_device_id(token)
    if not device_id:
        return JsonResponse({"ok": False, "error": "No active Spotify device found."}, status=400)
    spotify_play_uri(token, uri, device_id=device_id)
    return JsonResponse({"ok": True})

def api_play_uris(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)
    uris = request.GET.get("uris")
    if not uris:
        return JsonResponse({"error": "Missing uris"}, status=400)
    uri_list = [u for u in uris.split(",") if u]
    if not uri_list:
        return JsonResponse({"error": "No valid uris"}, status=400)
    device_id = request.GET.get("device_id") or _get_device_id(token)
    if not device_id:
        return JsonResponse({"ok": False, "error": "No active Spotify device found."}, status=400)
    spotify_play_uris(token, uri_list, device_id=device_id)
    return JsonResponse({"ok": True})

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
    return JsonResponse({"ok": True, "volume": v})


def api_devices(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)
    return JsonResponse({"ok": True, "devices": spotify_get_devices(token)})


# --- MOOD BOARDS / PLAYLISTS ---
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
        ]
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

import secrets
import time
import random
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.urls import reverse
from django.db import models
from .models import Mood, MoodEntry, TrackHistory, RecommendationSeen, RecommendationFeedback
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
    spotify_put,
    API_BASE,
)


def home(request):
    authed = bool(request.session.get("spotify_access_token"))
    return render(request, "spotify_app/home.html", {"authed": authed})


def _get_or_create_mood(name: str, spotify_user_id: str | None) -> Mood:
    mood, _ = Mood.objects.get_or_create(name=name, spotify_user_id=spotify_user_id)
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

    me = spotify_get_me(token_data["access_token"])
    if me and me.get("id"):
        request.session["spotify_user_id"] = me["id"]

    request.session.pop("spotify_oauth_state", None)
    request.session.modified = True
    request.session.save()
    return redirect(reverse("spotify_home"))


def spotify_logout(request):
    for k in ["spotify_access_token", "spotify_refresh_token", "spotify_expires_at", "spotify_oauth_state", "spotify_user_id"]:
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


def _get_spotify_user_id(request, token: str | None = None) -> str | None:
    user_id = request.session.get("spotify_user_id")
    if user_id:
        return user_id
    if not token:
        token = _get_access_token(request)
    if not token:
        return None
    me = spotify_get_me(token)
    user_id = me.get("id") if me else None
    if user_id:
        request.session["spotify_user_id"] = user_id
        request.session.modified = True
    return user_id


def _log_history_if_new(request, track):
    last_id = request.session.get("last_track_id")
    user_id = _get_spotify_user_id(request)
    if not user_id:
        return
    if track.get("id") and track["id"] != last_id:
        TrackHistory.objects.create(
            spotify_user_id=user_id,
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
    def lerp(a: float, b: float, x: float) -> float:
        return a + (b - a) * x
    if m == "hype":
        return {
            "limit": 25,
            # Low intensity = bouncy/upbeat, high intensity = aggressive/fast
            "target_energy": lerp(0.70, 0.95, t),
            "min_energy": lerp(0.55, 0.85, t),
            "target_danceability": lerp(0.70, 0.85, t),
            "min_danceability": lerp(0.55, 0.70, t),
            "target_valence": lerp(0.70, 0.55, t),
            "min_valence": lerp(0.50, 0.35, t),
            "target_tempo": lerp(115, 165, t),
            "min_tempo": lerp(100, 130, t),
            "target_loudness": lerp(-9, -5, t),
            "max_acousticness": lerp(0.45, 0.15, t),
            "min_popularity": int(35 + 35 * t),
        }
    if m == "perreo":
        return {
            "limit": 25,
            # Perreo = high groove, bass, mid tempo
            "target_energy": lerp(0.65, 0.90, t),
            "min_energy": lerp(0.50, 0.75, t),
            "target_danceability": lerp(0.75, 0.90, t),
            "min_danceability": lerp(0.60, 0.75, t),
            "target_valence": lerp(0.65, 0.55, t),
            "min_valence": lerp(0.45, 0.35, t),
            "target_tempo": lerp(90, 110, t),
            "min_tempo": lerp(80, 95, t),
            "target_loudness": lerp(-10, -6, t),
            "max_acousticness": lerp(0.35, 0.15, t),
            "min_popularity": int(30 + 35 * t),
        }
    if m == "menacing":
        return {
            "limit": 25,
            # Hard-hitting trap: aggressive, low valence, loud
            "target_energy": lerp(0.70, 0.97, t),
            "min_energy": lerp(0.55, 0.85, t),
            "target_valence": lerp(0.22, 0.08, t),
            "max_valence": lerp(0.32, 0.18, t),
            "target_loudness": lerp(-9, -4, t),
            "target_tempo": lerp(100, 160, t),
            "min_tempo": lerp(90, 125, t),
            "max_acousticness": lerp(0.35, 0.10, t),
            "target_speechiness": lerp(0.08, 0.25, t),
            "min_popularity": int(20 + 30 * t),
        }
    if m == "sad":
        return {
            "limit": 25,
            # Deep heartbreak: low valence, slow, softer
            "target_energy": lerp(0.28, 0.15, t),
            "max_energy": lerp(0.40, 0.25, t),
            "target_valence": lerp(0.18, 0.06, t),
            "max_valence": lerp(0.25, 0.15, t),
            "target_acousticness": lerp(0.60, 0.90, t),
            "min_acousticness": lerp(0.45, 0.70, t),
            "target_tempo": lerp(85, 60, t),
            "max_tempo": lerp(100, 80, t),
            "target_instrumentalness": lerp(0.10, 0.35, t),
            "max_popularity": int(85 - 25 * t),
        }
    if m == "chill":
        return {
            "limit": 25,
            # Smooth, smoky, slow vibe
            "target_energy": lerp(0.45, 0.25, t),
            "max_energy": lerp(0.55, 0.35, t),
            "target_valence": lerp(0.55, 0.45, t),
            "target_tempo": lerp(100, 70, t),
            "max_tempo": lerp(115, 90, t),
            "target_acousticness": lerp(0.30, 0.60, t),
            "min_acousticness": lerp(0.15, 0.35, t),
            "target_instrumentalness": lerp(0.03, 0.25, t),
            "max_popularity": int(90 - 20 * t),
        }
    if m == "romantic":
        return {
            "limit": 25,
            # Feel-good Latin/R&B with slow-grind moments
            "target_energy": lerp(0.60, 0.35, t),
            "max_energy": lerp(0.70, 0.50, t),
            "target_valence": lerp(0.78, 0.90, t),
            "min_valence": lerp(0.60, 0.75, t),
            "target_acousticness": lerp(0.20, 0.55, t),
            "min_acousticness": lerp(0.10, 0.35, t),
            "target_tempo": lerp(108, 80, t),
            "max_tempo": lerp(120, 95, t),
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
        "hype": ["reggaeton", "latin", "urbano latino", "dancehall", "hip-hop"],
        "perreo": ["reggaeton", "urbano latino", "latin hip hop", "trap latino", "dembow"],
        "menacing": ["trap", "hip-hop", "drill", "industrial", "dark trap"],
        "sad": ["sad", "heartbreak", "singer-songwriter", "piano", "acoustic"],
        "chill": ["chill", "r-n-b", "lofi", "ambient", "downtempo"],
        "romantic": ["latin", "r-n-b", "soul", "romantic", "alt r&b"],
        "neutral": ["indie", "alternative", "r-n-b", "pop", "electronic"],
    }
    high = {
        "hype": ["reggaeton", "latin", "dancehall", "trap", "edm"],
        "perreo": ["reggaeton", "urbano latino", "trap latino", "latin hip hop", "dembow"],
        "menacing": ["trap", "drill", "hip-hop", "industrial", "dark trap"],
        "sad": ["sad", "heartbreak", "piano", "acoustic", "singer-songwriter"],
        "chill": ["r-n-b", "chill", "lofi", "ambient", "downtempo"],
        "romantic": ["latin", "r-n-b", "soul", "romantic", "alt r&b"],
        "neutral": ["indie", "alternative", "r-n-b", "pop", "electronic"],
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


def _score_track(features: dict, params: dict, mood: str | None = None) -> float:
    if not features:
        return 999.0
    score = 0.0
    weights = {
        "energy": 2.0,
        "valence": 2.0,
        "tempo": 1.6,
        "danceability": 1.6,
        "acousticness": 1.2,
        "loudness": 1.0,
        "instrumentalness": 1.0,
        "speechiness": 1.0,
    }
    for key, target in params.items():
        if not key.startswith("target_"):
            continue
        feat_key = key.replace("target_", "")
        val = features.get(feat_key)
        if val is None:
            continue
        weight = weights.get(feat_key, 1.0)
        score += abs(float(val) - float(target)) * weight
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


def _get_artist_genres_bulk(token: str, artist_ids: list[str]) -> dict:
    if not artist_ids:
        return {}
    # Spotify API limit: 50 ids per request
    chunks = [artist_ids[i:i + 50] for i in range(0, len(artist_ids), 50)]
    out: dict[str, list[str]] = {}
    for chunk in chunks:
        url = f"{API_BASE}/artists?ids={','.join(chunk)}"
        r = spotify_get(url, token)
        if r.status_code != 200:
            continue
        data = r.json()
        for a in data.get("artists", []) or []:
            if a and a.get("id"):
                out[a["id"]] = a.get("genres", []) or []
    return out


def _filter_by_hard_limits(tracks: list[dict], features_map: dict, mood: str, intensity: int) -> list[dict]:
    m = (mood or "neutral").lower()
    t = max(0, min(100, intensity)) / 100.0
    if m not in ("perreo", "hype", "sad", "romantic", "menacing", "neutral"):
        return tracks

    filtered: list[dict] = []
    for tr in tracks:
        tid = tr.get("id")
        f = features_map.get(tid) if features_map else None
        if not f:
            continue
        energy = float(f.get("energy") or 0.0)
        dance = float(f.get("danceability") or 0.0)
        tempo = float(f.get("tempo") or 0.0)
        valence = float(f.get("valence") or 0.0)
        acoustic = float(f.get("acousticness") or 0.0)

        if m == "perreo":
            min_energy = 0.50 + 0.15 * t
            min_dance = 0.68 + 0.08 * t
            min_tempo = 80 + 10 * t
            max_tempo = 118 + 6 * t
            max_acoustic = 0.35
            min_valence = 0.35
        elif m == "hype":
            min_energy = 0.60 + 0.20 * t
            min_dance = 0.60 + 0.10 * t
            min_tempo = 100 + 10 * t
            max_tempo = 175
            max_acoustic = 0.35
            min_valence = 0.30
        elif m == "sad":
            min_energy = 0.0
            min_dance = 0.0
            min_tempo = 0.0
            max_tempo = 95 - 10 * t
            max_acoustic = 1.0
            min_valence = 0.0
            max_valence = 0.25 + 0.05 * (1 - t)
        elif m == "romantic":
            min_energy = 0.0
            min_dance = 0.0
            min_tempo = 0.0
            max_tempo = 105 - 10 * t
            max_acoustic = 1.0
            min_valence = 0.55
            max_valence = 1.0
        elif m == "menacing":
            min_energy = 0.70 + 0.15 * t
            min_dance = 0.50
            min_tempo = 100 + 15 * t
            max_tempo = 170
            max_acoustic = 0.30
            min_valence = 0.0
            max_valence = 0.25
        else:  # neutral
            # Neutral should avoid perreo/hype extremes
            min_energy = 0.25
            max_energy = 0.65
            min_dance = 0.35
            max_dance = 0.70
            min_tempo = 70
            max_tempo = 115
            exclude_dance = 0.78
            exclude_tempo = 95
            exclude_energy = 0.65

        if m == "sad":
            if valence <= max_valence and tempo <= max_tempo and energy <= (0.35 - 0.10 * t):
                filtered.append(tr)
            continue
        if m == "romantic":
            if valence >= min_valence and tempo <= max_tempo and energy <= (0.60 - 0.10 * t):
                filtered.append(tr)
            continue
        if m == "menacing":
            if (
                valence <= max_valence
                and tempo >= min_tempo
                and tempo <= max_tempo
                and energy >= min_energy
                and acoustic <= max_acoustic
            ):
                filtered.append(tr)
            continue
        if m == "neutral":
            if (
                energy >= min_energy
                and energy <= max_energy
                and dance >= min_dance
                and dance <= max_dance
                and tempo >= min_tempo
                and tempo <= max_tempo
                and not (dance >= exclude_dance and tempo >= exclude_tempo and energy >= exclude_energy)
            ):
                filtered.append(tr)
            continue

        if (
            energy >= min_energy
            and dance >= min_dance
            and tempo >= min_tempo
            and tempo <= max_tempo
            and acoustic <= max_acoustic
            and valence >= min_valence
        ):
            filtered.append(tr)

    return filtered


def api_recommend(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)

    user_id = _get_spotify_user_id(request, token)
    mood = request.GET.get("mood", "neutral")
    mood_key = (mood or "neutral").lower()
    mode = request.GET.get("mode", "blend").lower()
    intensity = int(request.GET.get("intensity", 50))
    limit = max(10, min(150, int(request.GET.get("limit", 25))))
    params = _recommend_params_for_mood(mood, intensity)
    weighted_genres = _weighted_genres_for_mood(mood, intensity)

    current_track = (request.GET.get("current_track") or "").strip()

    # Session-level repeat guard
    seen_ids = request.session.get("rec_seen_ids", [])
    if not isinstance(seen_ids, list):
        seen_ids = []
    last_mood = request.session.get("rec_last_mood")
    last_intensity = request.session.get("rec_last_intensity")
    last_mode = request.session.get("rec_last_mode")
    if last_mood != mood or last_intensity != intensity or last_mode != mode:
        seen_ids = []
        request.session["rec_seen_ids"] = []
        request.session["rec_last_mood"] = mood
        request.session["rec_last_intensity"] = intensity
        request.session["rec_last_mode"] = mode
        request.session.modified = True
    seen_set = set(seen_ids)
    if current_track:
        seen_set.add(current_track)
    history_ids = []
    if user_id:
        # Perreo needs more reach, so keep a shorter exclusion window
        history_limit = 40 if mood.lower() == "perreo" else 80
        seen_rec_limit = 120 if mood.lower() == "perreo" else 200
        global_seen_limit = 180 if mood.lower() == "perreo" else 300
        history_ids = list(
            TrackHistory.objects.filter(spotify_user_id=user_id)
            .order_by("-played_at")
            .values_list("track_id", flat=True)[:history_limit]
        )
        seen_set.update([i for i in history_ids if i])
        # Persistent seen recs (per mood+intensity) to prevent repeats across sessions/devices
        seen_rec_ids = list(
            RecommendationSeen.objects.filter(
                spotify_user_id=user_id, mood=mood, intensity=intensity, mode=mode
            )
            .order_by("-seen_at")
            .values_list("track_id", flat=True)[:seen_rec_limit]
        )
        seen_set.update([i for i in seen_rec_ids if i])
        # Global seen recs for this user, regardless of mood/intensity/mode
        global_seen_ids = list(
            RecommendationSeen.objects.filter(spotify_user_id=user_id)
            .order_by("-seen_at")
            .values_list("track_id", flat=True)[:global_seen_limit]
        )
        seen_set.update([i for i in global_seen_ids if i])
        # Feedback signals
        feedback_rows = list(
            RecommendationFeedback.objects.filter(spotify_user_id=user_id)
            .order_by("-created_at")
            .values_list("track_id", "value", "mood")[:400]
        )
        disliked_ids = {tid for tid, v, _m in feedback_rows if v == -1 and tid}
        liked_ids = {tid for tid, v, _m in feedback_rows if v == 1 and tid}
        seen_set.update(disliked_ids)
    else:
        liked_ids = set()
        disliked_ids = set()

    try:
        me = spotify_get_me(token)
        market = me.get("country", "US")
        params["market"] = market
        if user_id:
            params["market"] = market
        if user_id:
            params["seed_catalog"] = "personal"

        available = spotify_get_available_genre_seeds(token).get("genres", [])
        mood_genres = [g for g in weighted_genres if g in available] if available else weighted_genres[:]
        personal_genres = _top_artist_genres(token, available) if available else []
        if not mood_genres:
            mood_genres = weighted_genres[:]

        random.shuffle(mood_genres)
        random.shuffle(personal_genres)

        t = max(0, min(100, intensity)) / 100.0
        if mode == "vibe":
            mood_slots = 5
            personal_slots = 0
        elif mode == "personal":
            mood_slots = 0
            personal_slots = 5
        else:
            if mood_key in ("chill", "sad", "romantic", "menacing", "neutral"):
                # Lean harder on personal taste for these moods
                mood_slots = 0
                personal_slots = 5
            else:
                mood_slots = max(2, min(4, round(2 + 2 * t)))
                personal_slots = max(1, 5 - mood_slots)
        seed_genres = (mood_genres[:mood_slots] + personal_genres[:personal_slots])[:5]
        if mood_key in ("chill", "sad", "romantic", "menacing", "neutral") and not seed_genres:
            # Fallback to mood genres only if personal genres are missing
            seed_genres = mood_genres[:5]

        recent = spotify_get_recently_played(token, limit=20)
        recent_items = recent.get("items", [])
        recent_tracks = [i.get("track") for i in recent_items if i.get("track")]
        recent_track_ids = [t.get("id") for t in recent_tracks if t and t.get("id")]
        recent_artist_ids = []
        for t in recent_tracks:
            recent_artist_ids.extend([a.get("id") for a in (t.get("artists") or []) if a.get("id")])

        if mood_key in ("chill", "sad", "romantic", "menacing", "neutral"):
            top_tracks = spotify_get_top_tracks(token, time_range="medium_term", limit=40).get("items", [])
            top_artists = spotify_get_top_artists(token, time_range="medium_term", limit=40).get("items", [])
        else:
            top_tracks = spotify_get_top_tracks(token, time_range="short_term", limit=30).get("items", [])
            top_artists = spotify_get_top_artists(token, time_range="short_term", limit=30).get("items", [])

        seed_source = "mixed"

        seed_track_pool = []
        if mode != "moodboard":
            seed_track_pool += [t for t in recent_track_ids if t]
            seed_track_pool += [t.get("id") for t in top_tracks if t.get("id")]
        if user_id:
            mood_seed_ids = list(
                MoodEntry.objects.filter(spotify_user_id=user_id, mood__name__iexact=mood)
                .order_by("-added_at")
                .values_list("track_id", flat=True)[:30]
            )
            if mode in ("moodboard", "blend", "vibe"):
                seed_track_pool += [t for t in mood_seed_ids if t]

        seed_track_pool = [t for t in dict.fromkeys(seed_track_pool) if t not in seen_set]
        seed_artist_pool = []
        if mode != "moodboard":
            seed_artist_pool += [a for a in recent_artist_ids if a]
            seed_artist_pool += [a.get("id") for a in top_artists if a.get("id")]
        seed_artist_pool = list(dict.fromkeys(seed_artist_pool))

        seed_pool = []
        for g in (mood_genres + personal_genres):
            if g not in seed_pool:
                seed_pool.append(g)

        rec_tracks_all: list[dict] = []
        last_rec_error = None
        attempts = 7 if mood_key == "perreo" else 5
        rec_limit = 120 if mood_key == "perreo" else 100
        for _ in range(attempts):
            if seed_track_pool:
                seed_tracks = random.sample(seed_track_pool, k=min(3, len(seed_track_pool)))
            else:
                # Use top tracks as seeds if pool is empty
                seed_tracks = [t.get("id") for t in top_tracks[:5] if t.get("id")]
            seed_artists = random.sample(seed_artist_pool, k=min(2, len(seed_artist_pool))) if seed_artist_pool else []
            seeds_count = len(seed_tracks) + len(seed_artists)
            random.shuffle(seed_pool)
            seed_genres = seed_pool[: max(0, 5 - seeds_count)]

            # Small popularity jitter helps avoid identical results for same seeds
            local_params = dict(params)
            if "min_popularity" in local_params or "max_popularity" in local_params:
                base_pop = int(local_params.get("min_popularity", 30))
                jitter = random.randint(-12, 12)
                local_params["target_popularity"] = max(1, min(100, base_pop + 15 + jitter))

            try:
                rec = spotify_get_recommendations(
                    token,
                    seed_tracks=seed_tracks,
                    seed_artists=seed_artists,
                    seed_genres=seed_genres,
                    params={**local_params, "limit": rec_limit},
                )
                rec_tracks_all.extend(rec.get("tracks", []))
            except Exception as e:
                last_rec_error = str(e)
                continue

        rec_tracks = rec_tracks_all

        # Expand pool with mood-search terms for reach (perreo only)
        mood_terms = {
            "hype": ["hype", "turn up", "party", "club", "banger", "dance"],
            "perreo": ["reggaeton", "perreo", "dembow", "neo perreo", "latin club"],
            "menacing": ["dark", "aggressive", "industrial", "hard", "ominous"],
            "sad": ["sad", "heartbreak", "melancholy", "slow", "tearful"],
            "chill": ["chill", "lofi", "ambient", "relax", "downtempo"],
            "romantic": ["romantic", "love", "slow dance", "intimate", "r&b"],
            "neutral": ["indie", "alt", "groove", "vibes", "mix"],
        }
        if mood_key == "perreo" and len(rec_tracks) < max(80, limit * 3):
            for term in mood_terms.get(mood_key, mood_terms["neutral"]):
                try:
                    res = spotify_search_tracks(token, term, limit=25, market=market)
                    rec_tracks.extend(res.get("tracks", {}).get("items", []))
                except Exception:
                    continue

        # Only expand with search if the recommendations API failed or returned nothing
        if last_rec_error or not rec_tracks:
            # Prefer personalized recovery first
            personal_ids = [t.get("id") for t in top_tracks[:15] if t.get("id")]
            if personal_ids:
                try:
                    rec = spotify_get_recommendations(
                        token,
                        seed_tracks=personal_ids[:5],
                        seed_artists=[],
                        seed_genres=[],
                        params={**params, "limit": rec_limit},
                    )
                    rec_tracks.extend(rec.get("tracks", []))
                except Exception:
                    pass
            # Last resort search: only for perreo/hype
            if not rec_tracks and mood_key in ("perreo", "hype"):
                top_artist_names = [a.get("name") for a in top_artists if a.get("name")]
                search_terms = top_artist_names[:6] or mood_terms.get(mood_key, mood_terms["neutral"])
                for term in search_terms:
                    try:
                        res = spotify_search_tracks(token, term, limit=20, market=market)
                        rec_tracks.extend(res.get("tracks", {}).get("items", []))
                    except Exception:
                        continue

        # Dedupe by track id before filtering
        deduped = []
        seen_ids_local = set()
        for t in rec_tracks:
            tid = t.get("id")
            if not tid or tid in seen_ids_local:
                continue
            seen_ids_local.add(tid)
            deduped.append(t)
        rec_tracks = deduped

        recent_set = set(recent_track_ids)
        if history_ids:
            recent_set.update([i for i in history_ids if i])

        filtered_tracks = [
            t for t in rec_tracks
            if t.get("id") not in recent_set and t.get("id") not in seen_set
        ]
        if filtered_tracks:
            rec_tracks = filtered_tracks

        # Reduce repeats of the same artists from very recent plays/top artists
        exclude_artist_ids = set(recent_artist_ids[:40])
        exclude_artist_ids.update([a.get("id") for a in top_artists[:20] if a.get("id")])
        def has_excluded_artist(t: dict) -> bool:
            for a in t.get("artists", []) or []:
                if a.get("id") in exclude_artist_ids:
                    return True
            return False
        candidate_no_recent_artists = [t for t in rec_tracks if not has_excluded_artist(t)]
        if len(candidate_no_recent_artists) >= max(20, limit):
            rec_tracks = candidate_no_recent_artists

        rec_track_ids = list({t.get("id") for t in rec_tracks if t.get("id")})
        features_bulk = spotify_get_audio_features_bulk(token, rec_track_ids) if rec_track_ids else {}
        features_map = {f.get("id"): f for f in features_bulk.get("audio_features", []) if f}
        if features_map:
            cache = request.session.get("feature_cache", {})
            if not isinstance(cache, dict):
                cache = {}
            for tid, f in features_map.items():
                if not tid or not f:
                    continue
                cache[tid] = {
                    "danceability": f.get("danceability"),
                    "energy": f.get("energy"),
                    "valence": f.get("valence"),
                    "tempo": f.get("tempo"),
                    "acousticness": f.get("acousticness"),
                    "instrumentalness": f.get("instrumentalness"),
                    "liveness": f.get("liveness"),
                    "speechiness": f.get("speechiness"),
                }
            # Trim cache size
            if len(cache) > 300:
                for k in list(cache.keys())[: len(cache) - 300]:
                    cache.pop(k, None)
            request.session["feature_cache"] = cache
            request.session.modified = True

        if features_map:
            ranked = []
            for t in rec_tracks:
                tid = t.get("id")
                if not tid:
                    continue
                f = features_map.get(tid)
                score = _score_track(f, params, mood)
                if tid in liked_ids:
                    score -= 0.4
                jitter = random.uniform(0.0, 0.10 + 0.25 * (intensity / 100.0))
                ranked.append((score + jitter, t))
            ranked.sort(key=lambda x: x[0])
            ranked_tracks = [t for _, t in ranked]
        else:
            ranked_tracks = rec_tracks

        # Hard mood gating for perreo/hype/menacing/romantic/sad/neutral
        gated = _filter_by_hard_limits(ranked_tracks, features_map, mood, intensity)
        if gated:
            ranked_tracks = gated

        # Perreo: require artist genres to include reggaeton/urbano/latin
        if mood_key == "perreo":
            artist_ids = []
            for t in ranked_tracks:
                for a in t.get("artists", []) or []:
                    if a.get("id"):
                        artist_ids.append(a["id"])
            artist_ids = list(dict.fromkeys(artist_ids))
            artist_genres = _get_artist_genres_bulk(token, artist_ids)
            def is_perreo_artist(artists: list[dict]) -> bool:
                for a in artists or []:
                    genres = artist_genres.get(a.get("id"), [])
                    g = " ".join(genres).lower()
                    if (
                        "reggaeton" in g
                        or "urbano" in g
                        or "latin hip hop" in g
                        or "trap latino" in g
                        or "latin" in g
                        or "dembow" in g
                        or "dancehall" in g
                    ):
                        return True
                return False
            perreo_only = [t for t in ranked_tracks if is_perreo_artist(t.get("artists", []))]
            # If too few results, fallback to strong feature gate to keep perreo feel
            if len(perreo_only) >= max(6, limit // 2):
                ranked_tracks = perreo_only
            else:
                ranked_tracks = perreo_only or ranked_tracks

        # Add variety while keeping relevance by shuffling only top candidates
        top_slice = ranked_tracks[: min(80, len(ranked_tracks))]
        random.shuffle(top_slice)
        diverse = _dedupe_by_artist(top_slice, limit)
        if not diverse and rec_tracks:
            diverse = _dedupe_by_artist(rec_tracks, limit)

        # If still too small, use search-based expansion as last resort
        if len(diverse) < max(6, limit // 2):
            extra_tracks: list[dict] = []
            search_terms = []
            if mood_key == "perreo":
                for g in (seed_genres or []):
                    if g:
                        search_terms.append(f"{mood} {g}")
            if not search_terms:
                search_terms = [mood]
            random.shuffle(search_terms)
            for q in search_terms[:3]:
                try:
                    res = spotify_search_tracks(token, q, limit=15, market=market)
                    items = res.get("tracks", {}).get("items", [])
                    extra_tracks.extend(items)
                except Exception:
                    continue

            # Filter extras and rank by features
            extra_tracks = [
                t for t in extra_tracks
                if t.get("id") and t.get("id") not in seen_set
            ]
            extra_ids = list({t.get("id") for t in extra_tracks if t.get("id")})
            if extra_ids:
                extra_features = spotify_get_audio_features_bulk(token, extra_ids)
                extra_map = {f.get("id"): f for f in extra_features.get("audio_features", []) if f}
                ranked_extra = []
                for t in extra_tracks:
                    f = extra_map.get(t.get("id"))
                    if not f:
                        continue
                    score = _score_track(f, params, mood)
                    ranked_extra.append((score, t))
                ranked_extra.sort(key=lambda x: x[0])
                extra_sorted = [t for _, t in ranked_extra]
                # Append extras to fill remaining slots
                for t in extra_sorted:
                    if len(diverse) >= limit:
                        break
                    diverse.append(t)

        why = (
            f"Matched mood {mood.title()} (intensity {intensity}). "
            f"Seeds: {seed_source} tracks/artists. "
            f"Genres: {', '.join(seed_genres)}. "
            f"Ranked by audio features."
        )
        if diverse and user_id:
            new_ids = [t.get("id") for t in diverse if t.get("id")]
            if new_ids:
                # Persist seen recs
                RecommendationSeen.objects.bulk_create(
                    [
                        RecommendationSeen(
                            spotify_user_id=user_id,
                            track_id=tid,
                            mood=mood,
                            intensity=intensity,
                            mode=mode,
                        )
                        for tid in new_ids
                    ],
                    ignore_conflicts=True,
                )
                seen_ids.extend(new_ids)
                # Dedupe while preserving order, cap size
                deduped = []
                seen_local = set()
                for tid in seen_ids:
                    if tid in seen_local:
                        continue
                    seen_local.add(tid)
                    deduped.append(tid)
                request.session["rec_seen_ids"] = deduped[-200:]
                request.session.modified = True
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
        # Personalized fallback only (avoid generic mood keyword spam)
        top_tracks = spotify_get_top_tracks(token, time_range="medium_term", limit=40).get("items", [])
        recent = spotify_get_recently_played(token, limit=30)
        recent_items = recent.get("items", [])
        recent_tracks = [i.get("track") for i in recent_items if i.get("track")]
        pool = top_tracks + recent_tracks

        # Dedupe pool and exclude seen/history
        seen_local = set()
        deduped = []
        for t in pool:
            tid = t.get("id")
            if not tid or tid in seen_local or tid in seen_set:
                continue
            seen_local.add(tid)
            deduped.append(t)

        random.shuffle(deduped)
        pool = deduped

        track_ids = [t.get("id") for t in pool if t.get("id")]
        features_bulk = spotify_get_audio_features_bulk(token, track_ids) if track_ids else {}
        features_map = {f.get("id"): f for f in features_bulk.get("audio_features", []) if f}

        if features_map:
            ranked = []
            for t in pool:
                f = features_map.get(t.get("id"))
                score = _score_track(f, params, mood)
                ranked.append((score, t))
            ranked.sort(key=lambda x: x[0])
            ranked_tracks = [t for _, t in ranked]
        else:
            ranked_tracks = pool

        filtered_tracks = [t for t in ranked_tracks if t.get("id") not in seen_set]
        if filtered_tracks:
            ranked_tracks = filtered_tracks
        diverse = _dedupe_by_artist(ranked_tracks, 15)

        why = f"Ranked your listening history by mood features for {mood.title()} (intensity {intensity})."
        if diverse and user_id:
            new_ids = [t.get("id") for t in diverse if t.get("id")]
            if new_ids:
                RecommendationSeen.objects.bulk_create(
                    [
                        RecommendationSeen(
                            spotify_user_id=user_id,
                            track_id=tid,
                            mood=mood,
                            intensity=intensity,
                            mode=mode,
                        )
                        for tid in new_ids
                    ],
                    ignore_conflicts=True,
                )
                seen_ids.extend(new_ids)
                deduped = []
                seen_local = set()
                for tid in seen_ids:
                    if tid in seen_local:
                        continue
                    seen_local.add(tid)
                    deduped.append(tid)
                request.session["rec_seen_ids"] = deduped[-200:]
                request.session.modified = True
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
        return JsonResponse({"ok": True, "mood": mood, "tracks": tracks, "source": "personal_fallback"})


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

def api_seek(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)
    pos = int(request.GET.get("pos", 0))
    pos = max(0, pos)
    device_id = request.GET.get("device_id") or _get_device_id(token)
    if not device_id:
        return JsonResponse({"ok": False, "error": "No active Spotify device found."}, status=400)
    url = f"{API_BASE}/me/player/seek?position_ms={pos}&device_id={device_id}"
    spotify_put(url, token).raise_for_status()
    return JsonResponse({"ok": True, "position_ms": pos})


def api_devices(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)
    return JsonResponse({"ok": True, "devices": spotify_get_devices(token)})


def api_recommend_feedback(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)
    user_id = _get_spotify_user_id(request, token)
    if not user_id:
        return JsonResponse({"error": "Missing user id"}, status=400)

    track_id = (request.GET.get("track_id") or "").strip()
    mood = (request.GET.get("mood") or "").strip().lower()
    intensity = int(request.GET.get("intensity", 50))
    value = (request.GET.get("value") or "").strip().lower()
    if not track_id:
        return JsonResponse({"error": "Missing track_id"}, status=400)
    if value not in ("like", "dislike"):
        return JsonResponse({"error": "Invalid value"}, status=400)

    val = RecommendationFeedback.LIKE if value == "like" else RecommendationFeedback.DISLIKE
    RecommendationFeedback.objects.update_or_create(
        spotify_user_id=user_id,
        track_id=track_id,
        mood=mood,
        defaults={"intensity": intensity, "value": val},
    )
    return JsonResponse({"ok": True, "track_id": track_id, "value": value, "mood": mood})


# --- MOOD BOARDS / PLAYLISTS ---
def api_add_to_app_mood(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)
    user_id = _get_spotify_user_id(request, token)
    if not user_id:
        return JsonResponse({"error": "Missing user id"}, status=400)

    mood_name = request.GET.get("mood")
    if not mood_name:
        return JsonResponse({"error": "Missing mood"}, status=400)

    payload = get_now_playing(token)
    if not payload:
        return JsonResponse({"error": "Nothing playing"}, status=400)

    item = payload.get("item") or {}
    track_id = item.get("id")
    mood = _get_or_create_mood(mood_name, user_id)

    if MoodEntry.objects.filter(mood=mood, track_id=track_id, spotify_user_id=user_id).exists():
        return JsonResponse({"ok": True, "mood": mood.name, "duplicate": True})

    entry = MoodEntry.objects.create(
        mood=mood,
        spotify_user_id=user_id,
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
    user_id = _get_spotify_user_id(request, token)
    if not user_id:
        return JsonResponse({"error": "Missing user id"}, status=400)

    mood_name = request.GET.get("mood")
    if not mood_name:
        return JsonResponse({"error": "Missing mood"}, status=400)

    payload = get_now_playing(token)
    if not payload:
        return JsonResponse({"error": "Nothing playing"}, status=400)

    item = payload.get("item") or {}
    track_id = item.get("id")
    track_uri = item.get("uri")

    mood = _get_or_create_mood(mood_name, user_id)

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

    user_id = _get_spotify_user_id(request)
    mood = Mood.objects.filter(name=mood_name, spotify_user_id=user_id).first()
    if not mood:
        return JsonResponse({"ok": False, "error": "Mood not found"}, status=404)

    deleted, _ = MoodEntry.objects.filter(mood=mood, track_id=track_id, spotify_user_id=user_id).delete()
    return JsonResponse({"ok": True, "deleted": deleted})


def api_remove_from_spotify_playlist(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)
    user_id = _get_spotify_user_id(request, token)
    if not user_id:
        return JsonResponse({"error": "Missing user id"}, status=400)

    mood_name = request.GET.get("mood")
    track_uri = request.GET.get("track_uri")
    if not mood_name or not track_uri:
        return JsonResponse({"error": "Missing mood or track_uri"}, status=400)

    mood = Mood.objects.filter(name=mood_name, spotify_user_id=user_id).first()
    if not mood or not mood.spotify_playlist_id:
        return JsonResponse({"ok": False, "error": "Playlist not found"}, status=404)

    spotify_remove_track(token, mood.spotify_playlist_id, track_uri)
    return JsonResponse({"ok": True, "playlist_id": mood.spotify_playlist_id})


def api_mood_board(request):
    user_id = _get_spotify_user_id(request)
    moods = Mood.objects.filter(spotify_user_id=user_id).prefetch_related("entries").order_by("name")
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
                for e in m.entries.filter(spotify_user_id=user_id).order_by("-added_at")
            ],
        })
    return JsonResponse({"moods": data})


def api_history(request):
    user_id = _get_spotify_user_id(request)
    items = TrackHistory.objects.filter(spotify_user_id=user_id).order_by("-played_at")[:20]
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
    user_id = _get_spotify_user_id(request)
    mood_counts = (
        MoodEntry.objects.filter(spotify_user_id=user_id).values("mood__name")
        .order_by()
        .annotate(count=models.Count("id"))
        .order_by("-count")
    )
    artist_counts = (
        MoodEntry.objects.filter(spotify_user_id=user_id).values("mood__name", "artists")
        .order_by()
        .annotate(count=models.Count("id"))
        .order_by("-count")[:50]
    )
    return JsonResponse({"moods": list(mood_counts), "artists": list(artist_counts)})


def api_goal_mood(request):
    goal = request.GET.get("goal")
    if not goal:
        return JsonResponse({"error": "Missing goal"}, status=400)

    user_id = _get_spotify_user_id(request)
    entries = MoodEntry.objects.filter(spotify_user_id=user_id, mood__name__iexact=goal).order_by("-added_at")[:20]
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
        # Try cached features from recent recommendations
        cache = request.session.get("feature_cache", {})
        if isinstance(cache, dict) and track_id in cache:
            cached = cache.get(track_id)
            mood = _mood_from_features(cached)
            return JsonResponse({
                "playing": True,
                "track": track,
                "mood": mood,
                "audio_features": cached,
                "warning": "Using cached audio features for this track."
            })
        # Try any saved mood entry for this user
        user_id = _get_spotify_user_id(request, token)
        if user_id:
            entry = MoodEntry.objects.filter(spotify_user_id=user_id, track_id=track_id).select_related("mood").first()
            if entry and entry.mood:
                return JsonResponse({
                    "playing": True,
                    "track": track,
                    "mood": (entry.mood.name or "unknown").lower(),
                    "audio_features": None,
                    "warning": "Audio features unavailable; using saved mood."
                })
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

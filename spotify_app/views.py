import secrets
import time
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.urls import reverse

from .services.spotify_client import (
    get_login_url,
    exchange_code_for_token,
    refresh_access_token,
    spotify_get,
    API_BASE,
)

def home(request):
    authed = bool(request.session.get("spotify_access_token"))
    return render(request, "spotify_app/home.html", {"authed": authed})

def spotify_login(request):
    state = secrets.token_urlsafe(16)
    request.session["spotify_oauth_state"] = state
    return redirect(get_login_url(state))

def spotify_callback(request):
    code = request.GET.get("code")
    state = request.GET.get("state")

    if not code or state != request.session.get("spotify_oauth_state"):
        return JsonResponse({"error": "Invalid OAuth state"}, status=400)

    token_data = exchange_code_for_token(code)

    request.session["spotify_access_token"] = token_data["access_token"]
    request.session["spotify_refresh_token"] = token_data.get("refresh_token")
    request.session["spotify_expires_at"] = token_data["expires_at"]

    return redirect(reverse("spotify_home"))

def spotify_logout(request):
    for k in ["spotify_access_token", "spotify_refresh_token", "spotify_expires_at", "spotify_oauth_state"]:
        request.session.pop(k, None)
    return redirect(reverse("spotify_home"))

def _get_access_token(request):
    token = request.session.get("spotify_access_token")
    refresh = request.session.get("spotify_refresh_token")
    expires_at = int(request.session.get("spotify_expires_at") or 0)

    if not token:
        return None

    # refresh 60 seconds early
    if int(time.time()) > (expires_at - 60):
        if not refresh:
            return None
        new_data = refresh_access_token(refresh)
        request.session["spotify_access_token"] = new_data["access_token"]
        request.session["spotify_expires_at"] = new_data["expires_at"]
        token = new_data["access_token"]

    return token

def api_me(request):
    token = _get_access_token(request)
    if not token:
        return JsonResponse({"authenticated": False}, status=401)

    r = spotify_get(f"{API_BASE}/me", token)
    if r.status_code != 200:
        return JsonResponse({"error": "Failed to fetch profile", "details": r.text}, status=400)

    return JsonResponse({"authenticated": True, "profile": r.json()})

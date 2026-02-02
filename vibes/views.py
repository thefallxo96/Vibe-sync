import secrets
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.urls import reverse
from .services.spotify_client import get_login_url, exchange_code_for_token

def home(request):
    authed = bool(request.session.get("spotify_access_token"))
    return render(request, "vibes/home.html", {"authed": authed})

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

    return redirect(reverse("home"))

def spotify_logout(request):
    for k in ["spotify_access_token", "spotify_refresh_token", "spotify_expires_at", "spotify_oauth_state"]:
        request.session.pop(k, None)
    return redirect(reverse("home"))

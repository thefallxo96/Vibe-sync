from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="spotify_home"),
    path("login/", views.spotify_login, name="spotify_login"),
    path("callback/", views.spotify_callback, name="spotify_callback"),
    path("logout/", views.spotify_logout, name="spotify_logout"),

    path("api/token/", views.api_token, name="spotify_api_token"),
    path("api/transfer/", views.api_transfer, name="spotify_api_transfer"),

    path("api/now-playing/", views.api_now_playing, name="spotify_api_now_playing"),
    path("api/vibe/", views.api_vibe, name="spotify_api_vibe"),

    path("api/play/", views.api_play, name="spotify_api_play"),
    path("api/pause/", views.api_pause, name="spotify_api_pause"),
    path("api/volume/", views.api_volume, name="spotify_api_volume"),
    path("api/devices/", views.api_devices, name="spotify_api_devices"),

    path("api/mood/add-app/", views.api_add_to_app_mood, name="add_to_app_mood"),
    path("api/mood/add-spotify/", views.api_add_to_spotify_playlist, name="add_to_spotify_mood"),
    path("api/mood/add-both/", views.api_add_to_both, name="add_to_both_mood"),
]

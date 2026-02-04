from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="spotify_home"),
    path("login/", views.spotify_login, name="spotify_login"),
    path("callback/", views.spotify_callback, name="spotify_callback"),
    path("logout/", views.spotify_logout, name="spotify_logout"),

    path("api/token/", views.api_token, name="spotify_api_token"),
    path("api/transfer/", views.api_transfer, name="spotify_api_transfer"),
    path("api/me/", views.api_me, name="spotify_api_me"),

    path("api/now-playing/", views.api_now_playing, name="spotify_api_now_playing"),
    path("api/vibe/", views.api_vibe, name="spotify_api_vibe"),

    path("api/play/", views.api_play, name="spotify_api_play"),
    path("api/pause/", views.api_pause, name="spotify_api_pause"),
    path("api/next/", views.api_next, name="spotify_api_next"),
    path("api/previous/", views.api_previous, name="spotify_api_previous"),
    path("api/queue/", views.api_queue, name="spotify_api_queue"),
    path("api/play-uri/", views.api_play_uri, name="spotify_api_play_uri"),
    path("api/play-uris/", views.api_play_uris, name="spotify_api_play_uris"),
    path("api/volume/", views.api_volume, name="spotify_api_volume"),
    path("api/devices/", views.api_devices, name="spotify_api_devices"),

    path("api/mood/add-app/", views.api_add_to_app_mood, name="spotify_api_add_app"),
    path("api/mood/add-spotify/", views.api_add_to_spotify_playlist, name="spotify_api_add_spotify"),
    path("api/mood/add-both/", views.api_add_to_both, name="spotify_api_add_both"),
    path("api/mood/remove-app/", views.api_remove_from_app_mood, name="spotify_api_remove_app"),
    path("api/mood/remove-spotify/", views.api_remove_from_spotify_playlist, name="spotify_api_remove_spotify"),
    path("api/mood/board/", views.api_mood_board, name="spotify_api_mood_board"),

    path("api/history/", views.api_history, name="spotify_api_history"),
    path("api/analytics/", views.api_analytics, name="spotify_api_analytics"),
    path("api/goal/", views.api_goal_mood, name="spotify_api_goal"),
    path("api/recommend/", views.api_recommend, name="spotify_api_recommend"),
]

from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="spotify_home"),
    path("login/", views.spotify_login, name="spotify_login"),
    path("callback/", views.spotify_callback, name="spotify_callback"),
    path("logout/", views.spotify_logout, name="spotify_logout"),
    path("api/me/", views.api_me, name="spotify_api_me"),
]

# VibeSync

VibeSync is a full‑stack Django app that connects to Spotify, reads the currently playing track, infers a mood, and lets users save songs into mood boards and Spotify playlists. It also includes a Web Playback SDK player so playback can happen directly in the browser.

## Features
- Spotify OAuth + Web Playback SDK
- Now Playing + mood inference
- Mood board (app database)
- Auto‑created Spotify playlists per mood
- Add/remove tracks (app + Spotify)
- Playback controls (play/pause/volume)
- Mood glow UI + progress bar + history

## Tech Stack
- Django
- SQLite (default)
- Spotify Web API + Web Playback SDK
- Vanilla JS + HTML/CSS

## Quick Start
1. Create and activate a virtual environment.
2. Install dependencies.
3. Create `.env`.
4. Run migrations.
5. Start the server.

See **SETUP.md** for full step‑by‑step instructions.

## Project Structure
- `spotify_app/` Spotify auth, API endpoints, mood logic
- `vibes/` main UI templates
- `config/` Django settings and URL config

## Environment Variables
Required in `.env` (do not commit this file):


## Notes
- If you change Spotify scopes, logout and login again.
- Spotify Web Playback SDK requires a Premium account.


# VibeSync Setup Guide

## 1) Clone & enter the project
```bash
git clone <your-repo-url>
cd vibesync

2) Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate
3) Install dependencies
pip install -r requirements.txt
4) Create .env
cat > .env <<'EOF'
DJANGO_SECRET_KEY=dev-secret-change-me
DEBUG=True

SPOTIFY_CLIENT_ID=YOUR_CLIENT_ID
SPOTIFY_CLIENT_SECRET=YOUR_CLIENT_SECRET
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8000/spotify/callback/
EOF
5) Configure Spotify App
In the Spotify Developer Dashboard:

Add Redirect URI:
http://127.0.0.1:8000/spotify/callback/
Save changes.
6) Run migrations
python manage.py makemigrations
python manage.py migrate
7) Start server
python manage.py runserver
Open:

http://127.0.0.1:8000/
8) Authenticate
Click Connect Spotify, approve, then test Play / Pause / Vibe Check.

Troubleshooting
If playback fails with 401 or 403, log out and log in again.
If moods are “unknown,” the track has no audio features; choose a different track or use manual mood selection.
Make sure the Spotify app is active on a device.

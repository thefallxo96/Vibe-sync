from django.db import models

class Mood(models.Model):
    name = models.CharField(max_length=50, unique=True)
    spotify_playlist_id = models.CharField(max_length=120, blank=True, null=True)

    def __str__(self):
        return self.name


class MoodEntry(models.Model):
    mood = models.ForeignKey(Mood, on_delete=models.CASCADE, related_name="entries")
    track_id = models.CharField(max_length=64)
    track_name = models.CharField(max_length=200)
    artists = models.CharField(max_length=200)
    album = models.CharField(max_length=200, blank=True)
    image = models.URLField(blank=True)
    spotify_url = models.URLField(blank=True)
    added_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.mood.name} — {self.track_name}"

class TrackHistory(models.Model):
    track_id = models.CharField(max_length=64)
    track_name = models.CharField(max_length=200)
    artists = models.CharField(max_length=200)
    album = models.CharField(max_length=200, blank=True)
    image = models.URLField(blank=True)
    spotify_url = models.URLField(blank=True)
    played_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.track_name} — {self.artists}"

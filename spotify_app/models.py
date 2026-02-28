from django.db import models

class Mood(models.Model):
    name = models.CharField(max_length=50)
    spotify_user_id = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    spotify_playlist_id = models.CharField(max_length=120, blank=True, null=True)

    class Meta:
        unique_together = ("spotify_user_id", "name")

    def __str__(self):
        return self.name


class MoodEntry(models.Model):
    mood = models.ForeignKey(Mood, on_delete=models.CASCADE, related_name="entries")
    spotify_user_id = models.CharField(max_length=64, blank=True, null=True, db_index=True)
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
    spotify_user_id = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    track_id = models.CharField(max_length=64)
    track_name = models.CharField(max_length=200)
    artists = models.CharField(max_length=200)
    album = models.CharField(max_length=200, blank=True)
    image = models.URLField(blank=True)
    spotify_url = models.URLField(blank=True)
    played_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.track_name} — {self.artists}"


class RecommendationSeen(models.Model):
    spotify_user_id = models.CharField(max_length=64, db_index=True)
    track_id = models.CharField(max_length=64, db_index=True)
    mood = models.CharField(max_length=32, blank=True)
    intensity = models.IntegerField(default=50)
    mode = models.CharField(max_length=16, default="blend")
    seen_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("spotify_user_id", "track_id", "mood", "intensity", "mode")
        indexes = [
            models.Index(fields=["spotify_user_id", "seen_at"]),
            models.Index(fields=["spotify_user_id", "mood", "intensity", "mode", "seen_at"]),
        ]


class RecommendationFeedback(models.Model):
    LIKE = 1
    DISLIKE = -1
    FEEDBACK_CHOICES = [
        (LIKE, "like"),
        (DISLIKE, "dislike"),
    ]

    spotify_user_id = models.CharField(max_length=64, db_index=True)
    track_id = models.CharField(max_length=64, db_index=True)
    mood = models.CharField(max_length=32, blank=True)
    intensity = models.IntegerField(default=50)
    value = models.SmallIntegerField(choices=FEEDBACK_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("spotify_user_id", "track_id", "mood")
        indexes = [
            models.Index(fields=["spotify_user_id", "mood", "value", "created_at"]),
            models.Index(fields=["spotify_user_id", "value", "created_at"]),
        ]

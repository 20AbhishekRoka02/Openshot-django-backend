import uuid

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class CaptionServiceConfig(models.Model):
    COMPUTE_TYPE_CHOICES = [
        ("int8", "int8"),
        ("int8_float16", "int8_float16"),
        ("int8_float32", "int8_float32"),
        ("float16", "float16"),
        ("float32", "float32"),
        ("bfloat16", "bfloat16"),
    ]
    DEVICE_CHOICES = [
        ("auto", "Automatic"),
        ("cpu", "CPU"),
        ("cuda", "CUDA"),
    ]
    AUDIO_FORMAT_CHOICES = {
        "wav",
        "mp3",
        "m4a",
        "mp4",
        "webm",
        "ogg",
        "flac",
    }

    model_name = models.CharField(max_length=100, default="large-v3")
    compute_type = models.CharField(
        max_length=20, choices=COMPUTE_TYPE_CHOICES, default="int8"
    )
    device = models.CharField(max_length=10, choices=DEVICE_CHOICES, default="cpu")
    cpu_threads = models.PositiveSmallIntegerField(
        default=4,
        validators=[MinValueValidator(1), MaxValueValidator(256)],
    )
    model_workers = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(32)],
    )
    beam_size = models.PositiveSmallIntegerField(
        default=5, validators=[MinValueValidator(1), MaxValueValidator(10)]
    )
    vad_filter = models.BooleanField(
        default=True,
        help_text="Filter non-speech sections before transcription.",
    )
    condition_on_previous_text = models.BooleanField(
        default=True,
        help_text="Use preceding text as context for the next transcription window.",
    )
    default_language = models.CharField(
        max_length=20,
        default="en",
        help_text="Use a language code such as en, or auto for language detection.",
    )
    words_per_caption = models.PositiveSmallIntegerField(
        default=4, validators=[MinValueValidator(1), MaxValueValidator(100)]
    )
    max_line_chars = models.PositiveSmallIntegerField(
        default=24, validators=[MinValueValidator(1), MaxValueValidator(500)]
    )
    max_upload_size_mb = models.PositiveIntegerField(
        default=180,
        validators=[MinValueValidator(1), MaxValueValidator(2048)],
    )
    allowed_audio_formats = models.CharField(
        max_length=100,
        default="wav",
        help_text="Comma-separated extensions, e.g. wav,mp3. OpenShot uploads WAV.",
    )
    max_audio_duration_seconds = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(21600)],
        help_text="Leave blank to disable the duration limit.",
    )
    max_concurrent_jobs = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1), MaxValueValidator(32)]
    )
    audio_retention_days = models.PositiveSmallIntegerField(
        default=7, validators=[MinValueValidator(1), MaxValueValidator(3650)]
    )
    result_retention_days = models.PositiveSmallIntegerField(
        default=30, validators=[MinValueValidator(1), MaxValueValidator(3650)]
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Caption service configuration"
        verbose_name_plural = "Caption service configuration"

    def __str__(self):
        return "Caption service configuration"

    def clean(self):
        super().clean()
        formats = self.get_audio_formats()
        invalid_formats = formats - self.AUDIO_FORMAT_CHOICES
        if not formats:
            raise ValidationError(
                {"allowed_audio_formats": "Enter at least one audio file extension."}
            )
        if invalid_formats:
            raise ValidationError(
                {
                    "allowed_audio_formats": (
                        "Unsupported extensions: " + ", ".join(sorted(invalid_formats))
                    )
                }
            )
        self.allowed_audio_formats = ",".join(sorted(formats))
        self.model_name = self.model_name.strip()
        if not self.model_name:
            raise ValidationError({"model_name": "Enter a model name."})
        if self.device == "cpu" and self.compute_type in {
            "float16",
            "int8_float16",
            "bfloat16",
        }:
            raise ValidationError(
                {
                    "compute_type": (
                        "This compute type requires a compatible CUDA device."
                    )
                }
            )

    def get_audio_formats(self):
        return {
            extension.strip().lower().lstrip(".")
            for extension in self.allowed_audio_formats.split(",")
            if extension.strip()
        }

    def save(self, *args, **kwargs):
        self.pk = 1
        self.full_clean()
        return super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        config, _ = cls.objects.get_or_create(pk=1)
        return config

    def as_job_snapshot(
        self, language=None, words_per_caption=None, max_line_chars=None
    ):
        return {
            "model_name": self.model_name,
            "compute_type": self.compute_type,
            "device": self.device,
            "cpu_threads": self.cpu_threads,
            "model_workers": self.model_workers,
            "beam_size": self.beam_size,
            "vad_filter": self.vad_filter,
            "condition_on_previous_text": self.condition_on_previous_text,
            "language": language or self.default_language,
            "words_per_caption": words_per_caption or self.words_per_caption,
            "max_line_chars": max_line_chars or self.max_line_chars,
            "max_upload_size_mb": self.max_upload_size_mb,
            "allowed_audio_formats": self.allowed_audio_formats,
            "max_audio_duration_seconds": self.max_audio_duration_seconds,
            "max_concurrent_jobs": self.max_concurrent_jobs,
            "audio_retention_days": self.audio_retention_days,
            "result_retention_days": self.result_retention_days,
        }


def caption_audio_upload_to(instance, filename):
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "audio"
    return f"captions/{instance.job_id}/audio.{extension}"


class CaptionJob(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    job_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.QUEUED, db_index=True
    )
    audio = models.FileField(upload_to=caption_audio_upload_to)
    config_snapshot = models.JSONField(default=dict)
    result_text = models.TextField(blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    audio_deleted_at = models.DateTimeField(null=True, blank=True)
    result_deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.job_id} ({self.status})"

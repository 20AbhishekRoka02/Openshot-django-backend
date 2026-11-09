import uuid

import captions.models
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models
import django.utils.timezone


def create_default_config(apps, schema_editor):
    config_model = apps.get_model("captions", "CaptionServiceConfig")
    config_model.objects.get_or_create(pk=1)


def remove_default_config(apps, schema_editor):
    config_model = apps.get_model("captions", "CaptionServiceConfig")
    config_model.objects.filter(pk=1).delete()


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="CaptionJob",
            fields=[
                (
                    "job_id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("queued", "Queued"),
                            ("processing", "Processing"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                        ],
                        db_index=True,
                        default="queued",
                        max_length=12,
                    ),
                ),
                (
                    "audio",
                    models.FileField(upload_to=captions.models.caption_audio_upload_to),
                ),
                ("config_snapshot", models.JSONField(default=dict)),
                ("result_text", models.TextField(blank=True)),
                ("error", models.TextField(blank=True)),
                (
                    "created_at",
                    models.DateTimeField(db_index=True, default=django.utils.timezone.now),
                ),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("audio_deleted_at", models.DateTimeField(blank=True, null=True)),
                ("result_deleted_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="CaptionServiceConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "model_name",
                    models.CharField(default="large-v3", max_length=100),
                ),
                (
                    "compute_type",
                    models.CharField(
                        choices=[
                            ("int8", "int8"),
                            ("int8_float16", "int8_float16"),
                            ("int8_float32", "int8_float32"),
                            ("float16", "float16"),
                            ("float32", "float32"),
                            ("bfloat16", "bfloat16"),
                        ],
                        default="int8",
                        max_length=20,
                    ),
                ),
                (
                    "device",
                    models.CharField(
                        choices=[
                            ("auto", "Automatic"),
                            ("cpu", "CPU"),
                            ("cuda", "CUDA"),
                        ],
                        default="cpu",
                        max_length=10,
                    ),
                ),
                (
                    "cpu_threads",
                    models.PositiveSmallIntegerField(
                        default=4,
                        validators=[
                            MinValueValidator(1),
                            MaxValueValidator(256),
                        ],
                    ),
                ),
                (
                    "model_workers",
                    models.PositiveSmallIntegerField(
                        default=1,
                        validators=[
                            MinValueValidator(1),
                            MaxValueValidator(32),
                        ],
                    ),
                ),
                (
                    "beam_size",
                    models.PositiveSmallIntegerField(
                        default=5,
                        validators=[
                            MinValueValidator(1),
                            MaxValueValidator(10),
                        ],
                    ),
                ),
                (
                    "vad_filter",
                    models.BooleanField(
                        default=True,
                        help_text="Filter non-speech sections before transcription.",
                    ),
                ),
                (
                    "condition_on_previous_text",
                    models.BooleanField(
                        default=True,
                        help_text="Use preceding text as context for the next transcription window.",
                    ),
                ),
                (
                    "default_language",
                    models.CharField(
                        default="en",
                        help_text="Use a language code such as en, or auto for language detection.",
                        max_length=20,
                    ),
                ),
                (
                    "words_per_caption",
                    models.PositiveSmallIntegerField(
                        default=4,
                        validators=[
                            MinValueValidator(1),
                            MaxValueValidator(100),
                        ],
                    ),
                ),
                (
                    "max_line_chars",
                    models.PositiveSmallIntegerField(
                        default=24,
                        validators=[
                            MinValueValidator(1),
                            MaxValueValidator(500),
                        ],
                    ),
                ),
                (
                    "max_upload_size_mb",
                    models.PositiveIntegerField(
                        default=180,
                        validators=[
                            MinValueValidator(1),
                            MaxValueValidator(2048),
                        ],
                    ),
                ),
                (
                    "allowed_audio_formats",
                    models.CharField(
                        default="wav",
                        help_text="Comma-separated extensions, e.g. wav,mp3. OpenShot uploads WAV.",
                        max_length=100,
                    ),
                ),
                (
                    "max_audio_duration_seconds",
                    models.PositiveIntegerField(
                        blank=True,
                        help_text="Leave blank to disable the duration limit.",
                        null=True,
                        validators=[
                            MinValueValidator(1),
                            MaxValueValidator(21600),
                        ],
                    ),
                ),
                (
                    "max_concurrent_jobs",
                    models.PositiveSmallIntegerField(
                        default=1,
                        validators=[
                            MinValueValidator(1),
                            MaxValueValidator(32),
                        ],
                    ),
                ),
                (
                    "audio_retention_days",
                    models.PositiveSmallIntegerField(
                        default=7,
                        validators=[
                            MinValueValidator(1),
                            MaxValueValidator(3650),
                        ],
                    ),
                ),
                (
                    "result_retention_days",
                    models.PositiveSmallIntegerField(
                        default=30,
                        validators=[
                            MinValueValidator(1),
                            MaxValueValidator(3650),
                        ],
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Caption service configuration",
                "verbose_name_plural": "Caption service configuration",
            },
        ),
        migrations.RunPython(create_default_config, remove_default_config),
    ]

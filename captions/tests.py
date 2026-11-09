from datetime import timedelta
import tempfile
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from . import services
from .admin import CaptionServiceConfigAdmin
from .models import CaptionJob, CaptionServiceConfig


class CaptionApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.config = CaptionServiceConfig.load()

    def test_health_matches_openshot_contract(self):
        response = self.client.get("/api/v1/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "service": "ravi-api"})

    @patch("captions.views.start_job_thread")
    def test_create_job_uses_submitted_options_and_snapshots_admin_settings(
        self, start_job_thread
    ):
        self.config.model_name = "small"
        self.config.compute_type = "int8"
        self.config.default_language = "fr"
        self.config.max_audio_duration_seconds = 300
        self.config.save()

        response = self.client.post(
            "/api/v1/captions/jobs",
            {
                "audio": SimpleUploadedFile(
                    "clip.wav", b"wav-data", content_type="audio/wav"
                ),
                "language": "es",
                "words_per_caption": "5",
                "max_line_chars": "30",
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        job = CaptionJob.objects.get(pk=response.json()["job_id"])
        self.assertEqual(job.status, CaptionJob.Status.QUEUED)
        self.assertEqual(job.config_snapshot["model_name"], "small")
        self.assertEqual(job.config_snapshot["language"], "es")
        self.assertEqual(job.config_snapshot["words_per_caption"], 5)
        self.assertEqual(job.config_snapshot["max_line_chars"], 30)
        self.assertEqual(job.config_snapshot["max_audio_duration_seconds"], 300)
        self.assertEqual(job.config_snapshot["max_concurrent_jobs"], 1)
        self.assertEqual(job.config_snapshot["max_upload_size_mb"], 180)
        self.assertEqual(job.config_snapshot["allowed_audio_formats"], "wav")
        start_job_thread.assert_called_once_with(job.job_id)

    def test_create_rejects_unsupported_audio_format(self):
        response = self.client.post(
            "/api/v1/captions/jobs",
            {
                "audio": SimpleUploadedFile(
                    "clip.mp3", b"audio", content_type="audio/mpeg"
                )
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("audio", response.json())

    def test_create_rejects_upload_over_admin_limit(self):
        self.config.max_upload_size_mb = 1
        self.config.save()

        response = self.client.post(
            "/api/v1/captions/jobs",
            {
                "audio": SimpleUploadedFile(
                    "clip.wav",
                    b"x" * (1024 * 1024 + 1),
                    content_type="audio/wav",
                )
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("upload limit", str(response.json()).lower())

    def test_status_and_raw_webvtt_result(self):
        job = CaptionJob.objects.create(
            status=CaptionJob.Status.COMPLETED,
            config_snapshot={},
            result_text="WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello\n",
        )
        status_response = self.client.get(
            f"/api/v1/captions/jobs/{job.job_id}/"
        )
        result_response = self.client.get(
            f"/api/v1/captions/jobs/{job.job_id}/result/"
        )

        self.assertEqual(status_response.json()["status"], "completed")
        self.assertEqual(result_response.status_code, 200)
        self.assertEqual(result_response["Content-Type"], "text/vtt; charset=utf-8")
        self.assertTrue(result_response.content.startswith(b"WEBVTT"))

    def test_failed_job_includes_error(self):
        job = CaptionJob.objects.create(
            status=CaptionJob.Status.FAILED,
            config_snapshot={},
            error="Model unavailable",
        )

        response = self.client.get(f"/api/v1/captions/jobs/{job.job_id}/")

        self.assertEqual(response.json()["status"], "failed")
        self.assertEqual(response.json()["error"], "Model unavailable")

    def test_result_is_gone_after_retention_cleanup(self):
        job = CaptionJob.objects.create(
            status=CaptionJob.Status.COMPLETED,
            config_snapshot={},
            result_text="WEBVTT\n",
        )
        job.result_deleted_at = job.created_at
        job.save(update_fields=("result_deleted_at",))

        response = self.client.get(
            f"/api/v1/captions/jobs/{job.job_id}/result/"
        )

        self.assertEqual(response.status_code, 410)


class CaptionAdminTests(TestCase):
    def test_migration_creates_one_editable_singleton(self):
        self.assertEqual(CaptionServiceConfig.objects.count(), 1)
        model_admin = admin.site._registry[CaptionServiceConfig]
        request = SimpleNamespace()

        self.assertIsInstance(model_admin, CaptionServiceConfigAdmin)
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))

    def test_admin_renders_runtime_configuration_form(self):
        user = get_user_model().objects.create_superuser(
            username="admin", email="admin@example.com", password="test-password"
        )
        self.client.force_login(user)

        response = self.client.get(
            reverse("admin:captions_captionserviceconfig_change", args=[1])
        )

        self.assertEqual(response.status_code, 200)
        for field in (
            "model_name",
            "compute_type",
            "device",
            "beam_size",
            "max_upload_size_mb",
            "max_concurrent_jobs",
        ):
            self.assertContains(response, f'name="{field}"')

    def test_admin_changes_only_affect_future_job_snapshots(self):
        config = CaptionServiceConfig.load()
        old_snapshot = config.as_job_snapshot()
        job = CaptionJob.objects.create(config_snapshot=old_snapshot)
        config.model_name = "medium"
        config.max_upload_size_mb = 256
        config.save()
        new_snapshot = CaptionServiceConfig.load().as_job_snapshot()
        job.refresh_from_db()

        self.assertEqual(job.config_snapshot["model_name"], "large-v3")
        self.assertEqual(job.config_snapshot["max_upload_size_mb"], 180)
        self.assertEqual(new_snapshot["model_name"], "medium")

    def test_cpu_configuration_rejects_cuda_only_compute_type(self):
        config = CaptionServiceConfig.load()
        config.device = "cpu"
        config.compute_type = "float16"

        with self.assertRaisesMessage(
            ValidationError, "requires a compatible CUDA device"
        ):
            config.full_clean()


class CaptionWorkerTests(TestCase):
    def test_interrupted_jobs_are_marked_failed(self):
        queued = CaptionJob.objects.create(config_snapshot={})
        processing = CaptionJob.objects.create(
            status=CaptionJob.Status.PROCESSING,
            config_snapshot={},
        )
        completed = CaptionJob.objects.create(
            status=CaptionJob.Status.COMPLETED,
            config_snapshot={},
        )

        services.fail_interrupted_jobs()

        queued.refresh_from_db()
        processing.refresh_from_db()
        completed.refresh_from_db()
        self.assertEqual(queued.status, CaptionJob.Status.FAILED)
        self.assertIn("server restart", queued.error)
        self.assertEqual(processing.status, CaptionJob.Status.FAILED)
        self.assertEqual(completed.status, CaptionJob.Status.COMPLETED)

    def test_worker_stores_webvtt_on_success(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                job = CaptionJob.objects.create(
                    config_snapshot={
                        "model_name": "small",
                        "device": "cpu",
                        "compute_type": "int8",
                        "cpu_threads": 1,
                        "model_workers": 1,
                        "beam_size": 5,
                        "vad_filter": True,
                        "condition_on_previous_text": True,
                        "language": "en",
                        "words_per_caption": 2,
                        "max_line_chars": 24,
                        "max_audio_duration_seconds": None,
                        "max_concurrent_jobs": 1,
                    }
                )
                job.audio.save("input.wav", ContentFile(b"audio"), save=True)
                segment = SimpleNamespace(
                    start=0.0,
                    end=1.0,
                    text="Hello world",
                    words=[
                        SimpleNamespace(word="Hello", start=0.0, end=0.4),
                        SimpleNamespace(word=" world", start=0.4, end=1.0),
                    ],
                )
                model = SimpleNamespace(
                    transcribe=lambda *args, **kwargs: ([segment], None)
                )
                with (
                    patch("captions.services.validate_audio_duration"),
                    patch("captions.services.get_model", return_value=model),
                ):
                    services.process_caption_job(str(job.job_id))

                job.refresh_from_db()
                self.assertEqual(job.status, CaptionJob.Status.COMPLETED)
                self.assertIn("00:00:00.000 --> 00:00:01.000", job.result_text)
                self.assertIn("Hello world", job.result_text)

    def test_worker_records_transcription_errors(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                job = CaptionJob.objects.create(
                    config_snapshot={
                        "max_concurrent_jobs": 1,
                        "max_audio_duration_seconds": None,
                    }
                )
                job.audio.save("input.wav", ContentFile(b"audio"), save=True)
                with (
                    patch(
                        "captions.services.validate_audio_duration",
                        side_effect=ValueError("Invalid media"),
                    ),
                    self.assertLogs("captions.services", level="ERROR"),
                ):
                    services.process_caption_job(str(job.job_id))

                job.refresh_from_db()
                self.assertEqual(job.status, CaptionJob.Status.FAILED)
                self.assertEqual(job.error, "Invalid media")

    def test_configured_audio_duration_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            wav_path = Path(directory) / "short.wav"
            with wave.open(str(wav_path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes(b"\0\0" * 32000)

            with self.assertRaisesMessage(ValueError, "exceeds the configured"):
                services.validate_audio_duration(str(wav_path), 1)

    def test_cleanup_uses_retention_snapshot(self):
        old_date = timezone.now() - timedelta(days=2)
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                job = CaptionJob.objects.create(
                    status=CaptionJob.Status.COMPLETED,
                    created_at=old_date,
                    completed_at=old_date,
                    result_text="WEBVTT\n",
                    config_snapshot={
                        "audio_retention_days": 1,
                        "result_retention_days": 1,
                    },
                )
                job.audio.save("input.wav", ContentFile(b"audio"), save=True)
                waiting_job = CaptionJob.objects.create(
                    created_at=old_date,
                    config_snapshot={"audio_retention_days": 1},
                )
                waiting_job.audio.save("waiting.wav", ContentFile(b"audio"), save=True)

                audio_count, result_count = services.cleanup_expired_job_data()

                job.refresh_from_db()
                waiting_job.refresh_from_db()
                self.assertEqual((audio_count, result_count), (1, 1))
                self.assertFalse(job.audio)
                self.assertTrue(waiting_job.audio)
                self.assertEqual(job.result_text, "")
                self.assertIsNotNone(job.result_deleted_at)


class WebVttFormattingTests(TestCase):
    def test_wraps_caption_lines_and_formats_timestamp(self):
        lines = services.wrap_caption("This is a longer caption line", 10)

        self.assertEqual(lines, ["This is a", "longer", "caption", "line"])
        self.assertEqual(services.format_timestamp(61.234), "00:01:01.234")

    def test_builds_cues_by_words_per_caption(self):
        segment = SimpleNamespace(
            start=0.0,
            end=2.0,
            text="One two three",
            words=[
                SimpleNamespace(word="One", start=0.0, end=0.5),
                SimpleNamespace(word=" two", start=0.5, end=1.0),
                SimpleNamespace(word=" three", start=1.0, end=2.0),
            ],
        )

        result = services.transcription_to_webvtt([segment], 2, 24)

        self.assertEqual(result.count(" --> "), 2)
        self.assertIn("One two", result)
        self.assertIn("three", result)

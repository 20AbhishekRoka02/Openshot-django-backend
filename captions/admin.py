from django.contrib import admin

from .models import CaptionJob, CaptionServiceConfig


@admin.register(CaptionServiceConfig)
class CaptionServiceConfigAdmin(admin.ModelAdmin):
    fieldsets = [
        (
            "Speech recognition",
            {
                "fields": (
                    "model_name",
                    "compute_type",
                    "device",
                    "cpu_threads",
                    "model_workers",
                    "beam_size",
                    "vad_filter",
                    "condition_on_previous_text",
                )
            },
        ),
        (
            "Caption defaults",
            {
                "fields": (
                    "default_language",
                    "words_per_caption",
                    "max_line_chars",
                )
            },
        ),
        (
            "Limits and retention",
            {
                "fields": (
                    "max_upload_size_mb",
                    "allowed_audio_formats",
                    "max_audio_duration_seconds",
                    "max_concurrent_jobs",
                    "audio_retention_days",
                    "result_retention_days",
                )
            },
        ),
        ("Updated", {"fields": ("updated_at",)}),
    ]
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return not CaptionServiceConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CaptionJob)
class CaptionJobAdmin(admin.ModelAdmin):
    list_display = ("job_id", "status", "created_at", "started_at", "completed_at")
    list_filter = ("status",)
    search_fields = ("job_id", "error")
    readonly_fields = tuple(field.name for field in CaptionJob._meta.fields)
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

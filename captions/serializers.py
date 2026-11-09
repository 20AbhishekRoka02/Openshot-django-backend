from pathlib import Path

from rest_framework import serializers

from .models import CaptionServiceConfig


class CreateCaptionJobSerializer(serializers.Serializer):
    audio = serializers.FileField()
    language = serializers.CharField(required=False, allow_blank=False, max_length=20)
    words_per_caption = serializers.IntegerField(required=False, min_value=1, max_value=100)
    max_line_chars = serializers.IntegerField(required=False, min_value=1, max_value=500)

    def validate_audio(self, audio):
        config = self.context["config"]
        extension = Path(audio.name).suffix.lower().lstrip(".")
        if extension not in config.get_audio_formats():
            allowed = ", ".join(sorted(config.get_audio_formats()))
            raise serializers.ValidationError(
                f"Unsupported audio format. Allowed formats: {allowed}."
            )
        max_bytes = config.max_upload_size_mb * 1024 * 1024
        if audio.size > max_bytes:
            raise serializers.ValidationError(
                f"Audio exceeds the configured {config.max_upload_size_mb} MiB upload limit."
            )
        return audio

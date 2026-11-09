from django.core.management.base import BaseCommand

from captions.models import CaptionServiceConfig
from captions.services import get_model


class Command(BaseCommand):
    help = "Download and initialize the configured local Whisper model."

    def handle(self, *args, **options):
        config = CaptionServiceConfig.load()
        get_model(config.as_job_snapshot())
        self.stdout.write(
            self.style.SUCCESS(
                f"Initialized {config.model_name} on {config.device} "
                f"with {config.compute_type}."
            )
        )

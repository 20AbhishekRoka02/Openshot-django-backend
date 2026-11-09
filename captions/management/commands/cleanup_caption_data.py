from django.core.management.base import BaseCommand

from captions.services import cleanup_expired_job_data


class Command(BaseCommand):
    help = "Delete expired caption uploads and result text according to admin settings."

    def handle(self, *args, **options):
        audio_count, result_count = cleanup_expired_job_data()
        self.stdout.write(
            self.style.SUCCESS(
                f"Expired data cleaned: {audio_count} audio uploads, "
                f"{result_count} results."
            )
        )

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from .models import CaptionJob, CaptionServiceConfig
from .serializers import CreateCaptionJobSerializer
from .services import start_job_thread


@api_view(["GET"])
def health(request):
    return Response({"status": "ok", "service": "ravi-api"})


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def create_caption_job(request):
    config = CaptionServiceConfig.load()
    serializer = CreateCaptionJobSerializer(
        data=request.data, context={"config": config}
    )
    serializer.is_valid(raise_exception=True)
    values = serializer.validated_data

    job = CaptionJob(
        config_snapshot=config.as_job_snapshot(
            language=values.get("language"),
            words_per_caption=values.get("words_per_caption"),
            max_line_chars=values.get("max_line_chars"),
        ),
    )
    job.audio = values["audio"]
    job.save()
    start_job_thread(job.job_id)
    return Response({"job_id": str(job.job_id)}, status=status.HTTP_201_CREATED)


@api_view(["GET"])
def caption_job_status(request, job_id):
    job = get_object_or_404(CaptionJob, pk=job_id)
    result = {"job_id": str(job.job_id), "status": job.status}
    if job.status == CaptionJob.Status.FAILED:
        result["error"] = job.error or "Caption job failed."
    return Response(result)


@api_view(["GET"])
def caption_job_result(request, job_id):
    job = get_object_or_404(CaptionJob, pk=job_id)
    if job.status == CaptionJob.Status.FAILED:
        return Response(
            {"error": job.error or "Caption job failed."},
            status=status.HTTP_409_CONFLICT,
        )
    if job.status != CaptionJob.Status.COMPLETED:
        return Response(
            {"error": "Caption job is not complete."},
            status=status.HTTP_409_CONFLICT,
        )
    if job.result_deleted_at:
        return Response(
            {"error": "Caption result has expired."},
            status=status.HTTP_410_GONE,
        )
    return HttpResponse(job.result_text, content_type="text/vtt; charset=utf-8")

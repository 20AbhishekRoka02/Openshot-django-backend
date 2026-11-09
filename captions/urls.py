from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("captions/jobs", views.create_caption_job, name="caption-job-create"),
    path(
        "captions/jobs/<uuid:job_id>/",
        views.caption_job_status,
        name="caption-job-status",
    ),
    path(
        "captions/jobs/<uuid:job_id>/result/",
        views.caption_job_result,
        name="caption-job-result",
    ),
]

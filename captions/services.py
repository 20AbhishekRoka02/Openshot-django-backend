import logging
import threading
from functools import lru_cache
from datetime import timedelta

import av
from django.db import close_old_connections
from django.utils import timezone

from .models import CaptionJob

logger = logging.getLogger(__name__)

_slot_condition = threading.Condition()
_active_jobs = 0
_model_lock = threading.Lock()


def _load_model(model_name, device, compute_type, cpu_threads, model_workers):
    from faster_whisper import WhisperModel

    return WhisperModel(
        model_name,
        device=device,
        compute_type=compute_type,
        cpu_threads=cpu_threads,
        num_workers=model_workers,
    )


_cached_model = lru_cache(maxsize=1)(_load_model)


def get_model(config):
    with _model_lock:
        return _cached_model(
            config["model_name"],
            config["device"],
            config["compute_type"],
            config["cpu_threads"],
            config["model_workers"],
        )


def _acquire_processing_slot(maximum):
    global _active_jobs
    with _slot_condition:
        while _active_jobs >= maximum:
            close_old_connections()
            _slot_condition.wait(timeout=1)
        _active_jobs += 1


def _release_processing_slot():
    global _active_jobs
    with _slot_condition:
        _active_jobs -= 1
        _slot_condition.notify_all()


def start_job_thread(job_id):
    thread = threading.Thread(
        target=process_caption_job,
        args=(str(job_id),),
        name=f"caption-{job_id}",
        daemon=True,
    )
    thread.start()


def process_caption_job(job_id):
    close_old_connections()
    acquired_slot = False
    try:
        job = CaptionJob.objects.get(pk=job_id)
        if job.status != CaptionJob.Status.QUEUED:
            return
        _acquire_processing_slot(job.config_snapshot["max_concurrent_jobs"])
        acquired_slot = True
        job.status = CaptionJob.Status.PROCESSING
        job.started_at = timezone.now()
        job.save(update_fields=("status", "started_at"))

        config = job.config_snapshot
        validate_audio_duration(
            job.audio.path, config.get("max_audio_duration_seconds")
        )
        model = get_model(config)
        segments, _ = model.transcribe(
            job.audio.path,
            language=(
                None
                if config["language"].lower() == "auto"
                else config["language"]
            ),
            beam_size=config["beam_size"],
            condition_on_previous_text=config["condition_on_previous_text"],
            word_timestamps=True,
            vad_filter=config["vad_filter"],
        )
        vtt = transcription_to_webvtt(
            segments,
            config["words_per_caption"],
            config["max_line_chars"],
        )
        job.result_text = vtt
        job.status = CaptionJob.Status.COMPLETED
        job.completed_at = timezone.now()
        job.save(update_fields=("result_text", "status", "completed_at"))
    except Exception as exc:
        logger.exception("Caption job %s failed", job_id)
        CaptionJob.objects.filter(pk=job_id).update(
            status=CaptionJob.Status.FAILED,
            error=str(exc) or exc.__class__.__name__,
            completed_at=timezone.now(),
        )
    finally:
        if acquired_slot:
            _release_processing_slot()
        close_old_connections()


def validate_audio_duration(path, max_duration_seconds):
    if max_duration_seconds is None:
        return
    with av.open(path) as media:
        duration = media.duration
        if duration is None:
            stream_durations = [
                float(stream.duration * stream.time_base)
                for stream in media.streams.audio
                if stream.duration is not None and stream.time_base is not None
            ]
            duration = int(max(stream_durations, default=0) * av.time_base)
    duration_seconds = duration / av.time_base
    if duration_seconds > max_duration_seconds:
        raise ValueError(
            f"Audio duration ({duration_seconds:.1f}s) exceeds the configured "
            f"{max_duration_seconds}s limit."
        )


def transcription_to_webvtt(segments, words_per_caption, max_line_chars):
    words = []
    for segment in segments:
        segment_words = getattr(segment, "words", None) or []
        if segment_words:
            words.extend(
                {
                    "text": word.word,
                    "start": float(word.start),
                    "end": float(word.end),
                }
                for word in segment_words
            )
        else:
            tokens = (segment.text or "").split()
            if not tokens:
                continue
            duration = max(0.0, float(segment.end) - float(segment.start))
            token_duration = duration / len(tokens)
            words.extend(
                {
                    "text": f" {token}" if index else token,
                    "start": float(segment.start) + index * token_duration,
                    "end": float(segment.start) + (index + 1) * token_duration,
                }
                for index, token in enumerate(tokens)
            )

    cues = ["WEBVTT", ""]
    for index in range(0, len(words), words_per_caption):
        group = words[index : index + words_per_caption]
        text = "".join(word["text"] for word in group).strip()
        lines = wrap_caption(text, max_line_chars)
        cues.extend(
            (
                f"{format_timestamp(group[0]['start'])} --> "
                f"{format_timestamp(max(group[-1]['end'], group[0]['start'] + 0.001))}",
                "\n".join(lines),
                "",
            )
        )
    return "\n".join(cues)


def wrap_caption(text, max_line_chars):
    lines = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_line_chars:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def format_timestamp(seconds):
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{whole_seconds:02}.{milliseconds:03}"


def fail_interrupted_jobs():
    now = timezone.now()
    CaptionJob.objects.filter(
        status__in=(CaptionJob.Status.QUEUED, CaptionJob.Status.PROCESSING)
    ).update(
        status=CaptionJob.Status.FAILED,
        error="Caption processing was interrupted by a server restart. Please submit the job again.",
        completed_at=now,
    )


def cleanup_expired_job_data():
    now = timezone.now()
    audio_count = 0
    result_count = 0
    jobs = CaptionJob.objects.filter(config_snapshot__isnull=False)
    for job in jobs.iterator():
        settings = job.config_snapshot
        if (
            job.audio
            and job.audio_deleted_at is None
            and job.status
            in (CaptionJob.Status.COMPLETED, CaptionJob.Status.FAILED)
            and job.created_at
            < now - timedelta(days=settings.get("audio_retention_days", 7))
        ):
            job.audio.delete(save=False)
            job.audio_deleted_at = now
            job.save(update_fields=("audio", "audio_deleted_at"))
            audio_count += 1
        if (
            job.status == CaptionJob.Status.COMPLETED
            and job.result_deleted_at is None
            and job.completed_at
            < now - timedelta(days=settings.get("result_retention_days", 30))
        ):
            job.result_text = ""
            job.result_deleted_at = now
            job.save(update_fields=("result_text", "result_deleted_at"))
            result_count += 1
    return audio_count, result_count

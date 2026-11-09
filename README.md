# Ravi Caption API

A Django REST API for OpenShot's Ravi caption-generation integration. It stores
jobs in SQLite, audio under local media storage, and transcribes locally with
faster-whisper. The default configuration uses the `large-v3` model on CPU with
`int8` compute.

## API

| Method | Path | Behavior |
|---|---|---|
| `GET` | `/api/v1/health/` | Returns `{"status":"ok","service":"ravi-api"}` |
| `POST` | `/api/v1/captions/jobs` | Accepts multipart `audio`, optional `language`, `words_per_caption`, and `max_line_chars`; returns `job_id` |
| `GET` | `/api/v1/captions/jobs/{job_id}/` | Returns job status and an error for failed jobs |
| `GET` | `/api/v1/captions/jobs/{job_id}/result/` | Returns raw WebVTT with `text/vtt` content type after completion |

Jobs move through `queued`, `processing`, `completed`, and `failed`. The API
does not require authentication headers, matching the current OpenShot client.
Keep the API behind a firewall, VPN, or trusted network; do not expose it
directly to the public internet.

## Runtime configuration

After applying migrations and creating a Django superuser, open `/admin/` and
edit **Caption service configuration**. A data migration creates the one
configuration record; the Admin does not allow creating duplicates or deleting
it. API jobs are visible as read-only records.

Admin-editable settings:

- **Speech recognition:** model name, compute type, device, CPU threads, model
  workers, beam size, voice-activity filtering, and previous-text context.
- **Caption defaults:** language, words per caption, and maximum characters
  per line. Values supplied by OpenShot override the corresponding defaults
  for that job.
- **Limits:** maximum upload size in MiB, allowed comma-separated extensions,
  optional maximum audio duration in seconds, and maximum concurrent jobs.
- **Retention:** days to keep uploaded audio and completed WebVTT results.

Initial defaults are `large-v3`, `int8`, CPU, 4 CPU threads, 1 model worker,
beam size 5, voice-activity filtering and previous-text context enabled,
English (or `auto` for language detection), 4 words per caption, 24 characters
per line, 180 MiB per upload, WAV only, no duration limit, 1 concurrent job,
7 days of audio retention, and 30 days of result retention. Model and compute
compatibility depends on host hardware and the installed CTranslate2 runtime;
failures are reported in job status.

Configuration is snapshotted when a job is submitted. Editing caption/model
settings or retention does not change existing jobs. The upload cap and
accepted formats are enforced on each new request; concurrency is bounded by
the value snapshotted per job. If the upload cap is changed, update the Nginx
`client_max_body_size` value as well. The sample Nginx limit is 190 MiB to
allow multipart overhead for the default 180 MiB file cap.

The in-process worker requires one Gunicorn worker process. Multiple request
threads are safe, but do not increase Gunicorn's `--workers` above 1. Jobs
interrupted by a service restart are marked failed when the Django WSGI/ASGI
application starts; submit them again.

## Ubuntu systemd deployment

The included service assumes the application is installed in
`/opt/ravi-api`, runs as the `ravi` system user, and uses `/var/lib/ravi-api`
for persistent SQLite/media files.

1. Install Python, virtualenv support, and Nginx:

   ```sh
   sudo apt update
   sudo apt install -y python3 python3-venv python3-dev build-essential nginx
   ```

2. Copy the project to `/opt/ravi-api` and create the runtime environment:

   ```sh
   sudo useradd --system --home /opt/ravi-api --shell /usr/sbin/nologin ravi
   sudo install -d -o ravi -g ravi /opt/ravi-api /var/lib/ravi-api
   cd /opt/ravi-api
   sudo -u ravi python3 -m venv .venv
   sudo -u ravi .venv/bin/pip install -r requirements.txt
   ```

   The first transcription downloads the configured Whisper model. Ensure the
   VM has sufficient memory and disk space for `large-v3` and model caching.
   The supplied dependencies use the CPU runtime; GPU use requires a compatible
   CUDA/CTranslate2 environment and matching Admin device/compute settings.

3. Create `/etc/ravi-api.env` with a strong unique secret and deployment host
   settings. Use [`.env.example`](./.env.example) as a template, replace its
   example secret, and keep `DJANGO_DEBUG=false`. Restrict file permissions:

   ```sh
   sudo cp /opt/ravi-api/.env.example /etc/ravi-api.env
   /opt/ravi-api/.venv/bin/python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
   sudoedit /etc/ravi-api.env
   sudo chown root:ravi /etc/ravi-api.env
   sudo chmod 640 /etc/ravi-api.env
   ```

4. Apply migrations and create an Admin user:

   ```sh
   sudo -u ravi sh -c 'set -a; . /etc/ravi-api.env; set +a; exec /opt/ravi-api/.venv/bin/python manage.py migrate'
   sudo -u ravi sh -c 'set -a; . /etc/ravi-api.env; set +a; exec /opt/ravi-api/.venv/bin/python manage.py createsuperuser'
   sudo -u ravi sh -c 'set -a; . /etc/ravi-api.env; set +a; exec /opt/ravi-api/.venv/bin/python manage.py collectstatic --noinput'
   sudo -u ravi sh -c 'set -a; . /etc/ravi-api.env; set +a; exec /opt/ravi-api/.venv/bin/python manage.py warm_caption_model'
   ```

   The environment file is shell-compatible. Avoid putting the secret key in
   shell history. Warming the default model downloads and verifies it before
   the API accepts caption jobs; this can take time and requires model-sized
   disk space and RAM.

5. Install the systemd units and Nginx site from `deploy/`, update the Nginx
   `server_name`, TLS certificate paths, and trusted client CIDRs, then enable
   the service and cleanup timer:

   ```sh
   sudo cp deploy/ravi-api.service /etc/systemd/system/
   sudo cp deploy/ravi-cleanup.service deploy/ravi-cleanup.timer /etc/systemd/system/
   sudo cp deploy/nginx-ravi-api.conf /etc/nginx/sites-available/ravi-api
   sudo ln -s /etc/nginx/sites-available/ravi-api /etc/nginx/sites-enabled/ravi-api
   sudo nginx -t
   sudo systemctl daemon-reload
   sudo systemctl enable --now ravi-api ravi-cleanup.timer
   sudo systemctl reload nginx
   ```

   The sample Nginx config accepts 180 MiB uploads and restricts both the API
   and Admin to private IP ranges. Replace those ranges with the network/VPN
   CIDRs used by OpenShot clients and administrators.

6. Check service health locally and in logs:

   ```sh
   curl -fsS https://ravi.example.com/api/v1/health/
   sudo journalctl -u ravi-api -f
   ```

## Local development and tests

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
python manage.py test captions
python manage.py test captions.tests.CaptionApiTests.test_health_matches_openshot_contract
```

`python manage.py check` runs Django's project checks. The local server also
requires only one process because background jobs use in-process threads.

"""
ASGI config for videoback project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'videoback.settings')

application = get_asgi_application()

from captions.services import fail_interrupted_jobs

fail_interrupted_jobs()

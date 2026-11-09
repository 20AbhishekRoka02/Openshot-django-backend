"""
WSGI config for videoback project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'videoback.settings')

application = get_wsgi_application()

from captions.services import fail_interrupted_jobs

fail_interrupted_jobs()

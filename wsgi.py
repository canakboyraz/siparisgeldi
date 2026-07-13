"""Gunicorn giriş noktası: gunicorn wsgi:application

NOT: Birden fazla gunicorn worker'ı varsa scheduler'ı burada BAŞLATMA
(aksi halde her worker ayrı polling yapar). Prod'da RUN_SCHEDULER=0 verip
worker.py'yi tek bir ayrı süreç olarak çalıştırın.
"""
from app import create_app

application = create_app()

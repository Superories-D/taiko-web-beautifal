import multiprocessing
import os


bind = os.getenv("TAIKO_WEB_BIND", "0.0.0.0:80")
worker_class = "gthread"
workers = int(
    os.getenv(
        "TAIKO_WEB_GUNICORN_WORKERS",
        max(2, min(4, multiprocessing.cpu_count())),
    )
)
threads = int(os.getenv("TAIKO_WEB_GUNICORN_THREADS", "8"))
timeout = int(os.getenv("TAIKO_WEB_GUNICORN_TIMEOUT", "60"))
keepalive = int(os.getenv("TAIKO_WEB_GUNICORN_KEEPALIVE", "5"))

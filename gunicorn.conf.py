import multiprocessing
import os


bind = os.getenv("TAIKO_WEB_BIND", "0.0.0.0:80")
worker_class = "gthread"
workers = int(
    os.getenv(
        "TAIKO_WEB_GUNICORN_WORKERS",
        max(1, min(2, multiprocessing.cpu_count())),
    )
)
threads = int(os.getenv("TAIKO_WEB_GUNICORN_THREADS", "4"))
timeout = int(os.getenv("TAIKO_WEB_GUNICORN_TIMEOUT", "60"))
graceful_timeout = int(os.getenv("TAIKO_WEB_GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.getenv("TAIKO_WEB_GUNICORN_KEEPALIVE", "5"))
max_requests = int(os.getenv("TAIKO_WEB_GUNICORN_MAX_REQUESTS", "2000"))
max_requests_jitter = int(os.getenv("TAIKO_WEB_GUNICORN_MAX_REQUESTS_JITTER", "200"))

FROM python:3.13.2-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app
EXPOSE 80
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:app", "--access-logfile", "-"]

FROM python:3.13.2
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt
ENV PYTHONUNBUFFERED 1
EXPOSE 80
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:app", "--access-logfile", "-"]

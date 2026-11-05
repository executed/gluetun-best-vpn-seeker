FROM python:3.12-slim-bookworm

WORKDIR /app

# Ensure base directories exist
RUN mkdir -p /app/data/target-env-gluetun/servers

RUN python -m pip install --no-cache-dir \
    flask requests cryptography apscheduler

COPY . /app

EXPOSE 43999
CMD ["python", "app.py"]
FROM python:3.12-slim-bookworm

WORKDIR /app
RUN pip install --no-cache-dir flask requests

COPY app.py /app/app.py
EXPOSE 43988

CMD ["python", "app.py"]
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.22
FROM ${BUILD_FROM}

RUN apk add --no-cache python3

COPY app /app

ENV BOOKS_DATA=/data BOOKS_PORT=8099
CMD ["python3", "-u", "/app/server.py"]

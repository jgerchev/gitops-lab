# Registry index digest verified against Docker Hub (see README).
FROM python:3.13.5-alpine3.22@sha256:37b14db89f587f9eaa890e4a442a3fe55db452b69cca1403cc730bd0fbdc8aaf
ARG RELEASE
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY --chown=10001:10001 server.py /app/server.py
COPY --chown=10001:10001 releases/${RELEASE}/version.txt /app/version.txt
USER 10001:10001
EXPOSE 8080
CMD ["python", "/app/server.py"]

# builder/Dockerfile
FROM python:3-slim
COPY starlink-feed-build.py /app/
CMD ["sh","-c","while true; do python /app/starlink-feed-build.py || echo FAILED; sleep 21600; done"]

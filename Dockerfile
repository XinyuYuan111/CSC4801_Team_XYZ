# Complete runnable environment for TalentMatch (Flask + SQLite + waitress).
# Build:  docker build -t team-xyz .
# Start:  docker run -d --name team-xyz -p 127.0.0.1:8080:8080 team-xyz
# No external database image or runtime download is required (FP-SUB-1).
FROM python:3.12.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# Install locked dependencies (runtime and test).
COPY requirements.lock requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

# Copy source and run as an unprivileged user.
RUN useradd --create-home --uid 10001 student
COPY --chown=student:student . .
RUN mkdir -p /app/data && chown student:student /app/data
USER student

# Writable SQLite location and the application port. SECRET_KEY is optional:
# omit it to generate an ephemeral key (sessions expire on container restart).
ENV DATABASE=/app/data/app.sqlite3 PORT=8080
EXPOSE 8080

# Initialize the schema (idempotent) on start, then serve via waitress.
# Seed and test commands run with docker exec; see INSTALL.md.
CMD ["sh", "-c", "python manage.py init-db && python manage.py run --host 0.0.0.0 --port 8080"]

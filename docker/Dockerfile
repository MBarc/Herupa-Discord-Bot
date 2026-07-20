# Herupa's runtime image: Python + voice/audio system deps + pip packages,
# with the voice-recv DAVE patch baked in. The bot CODE is NOT baked in -
# docker-compose bind-mounts the repo at /app, so deploying a cog edit is
# still just "copy the file" (cogwatch hot-reloads inside the container).
# Rebuild this image only when requirements.txt or the patch changes:
#
#   docker compose -f docker/docker-compose.yml build
#
FROM python:3.11-slim-bookworm

# ffmpeg (music + mock playback), libopus (Discord voice), git (pip installs
# the voice-recv fork straight from GitHub), tzdata (Eastern-time schedules)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libopus0 git tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY Herupa/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# Overlay the DAVE patch onto the installed voice-recv package
# (see patches/voice_recv-dave/README.md for what it fixes and why)
COPY patches/voice_recv-dave/opus.py patches/voice_recv-dave/router.py /tmp/vrpatch/
RUN SITE=$(python -c "import discord.ext.voice_recv, os; print(os.path.dirname(discord.ext.voice_recv.__file__))") \
    && cp /tmp/vrpatch/opus.py /tmp/vrpatch/router.py "$SITE/" \
    && rm -rf /tmp/vrpatch

ENV PYTHONUNBUFFERED=1
WORKDIR /app/Herupa
CMD ["python", "bot.py"]

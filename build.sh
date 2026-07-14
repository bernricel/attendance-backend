#!/usr/bin/env bash
set -o errexit

# Install dependencies during Render build.
pip install -r requirements.txt

# Keep Render PostgreSQL schema in sync before the new app starts.
python manage.py migrate --noinput

# Collect static files for WhiteNoise production serving.
python manage.py collectstatic --noinput

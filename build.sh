#!/usr/bin/env bash
set -o errexit

# Install dependencies during Render build.
pip install -r requirements.txt

# Collect static files for WhiteNoise production serving.
python manage.py collectstatic --noinput

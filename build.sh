#!/usr/bin/env bash
# Exit immediately if a command exits with a non-zero status
set -o errexit

# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Build React / TypeScript Frontend
cd frontend
npm install
npm run build
cd ..

# 3. Collect static files for WhiteNoise
python manage.py collectstatic --no-input

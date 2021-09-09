FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY grafanasync.py /app/
COPY homedashboard.json /app/
ENV HOME_DASHBOARD_FILE=/app/homedashboard.json

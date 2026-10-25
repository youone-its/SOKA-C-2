# Satu image untuk VM (fcfs_worker.py) dan broker (fcfs_broker.py).
# Build dari root proyek: docker build -t fcfs-k8s:dev -f k8s/Dockerfile fcfs
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp/matplotlib

# PyCloudSim tidak dibutuhkan: eksekusi di cluster tidak memakai simulator.
RUN pip install --no-cache-dir "matplotlib>=3.8,<4"

WORKDIR /app
COPY workload.py fcfs_datacenter.py fcfs_scheduler.py fcfs_worker.py fcfs_broker.py ./

USER 10001
EXPOSE 8080
CMD ["python", "fcfs_worker.py"]

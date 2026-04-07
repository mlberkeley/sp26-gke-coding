FROM python:3.11

WORKDIR /app

# Copy your tests and agent code
COPY sp26_gke/ /app/sp26_gke/

# Install dependencies
RUN pip install --upgrade pip
RUN pip install "langchain==0.3.27" "langchain_google_genai==2.0.10"
RUN pip install "kubernetes==35.0.0"


ENV PYTHONPATH=/app
CMD ["python3", "/app/sp26_gke/workflows/orchestrator_job.py"]

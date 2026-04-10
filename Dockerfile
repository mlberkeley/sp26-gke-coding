FROM python:3.11

WORKDIR /app

# Copy your tests and agent code
COPY sp26_gke/ /app/sp26_gke/

# Install dependencies
RUN pip install --upgrade pip
RUN pip install langchain langchain_google_genai langgraph kubernetes

ENV PYTHONPATH=/app
CMD ["python3", "/app/sp26_gke/workflows/gke_agent_job.py"]

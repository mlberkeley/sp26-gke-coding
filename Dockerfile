FROM python:3.11

WORKDIR /app

# Copy your tests and agent code
COPY tests/ /app/tests/
COPY sp26_gke/ /app/sp26_gke/

# Install dependencies
RUN pip install --upgrade pip
RUN pip install langchain langchain_google_genai langgraph kubernetes

ENV PYTHONPATH=/app
ENV GOOGLE_API_KEY="AIzaSyC6_7_-NjjxRO8LK5HY186KbmiJiyIUJXE"
CMD ["python3", "/app/sp26_gke/workflows/gke_agent_job.py"]

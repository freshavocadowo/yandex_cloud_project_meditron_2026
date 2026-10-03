FROM python:3.12.11-slim
WORKDIR /app
COPY pyproject.toml requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY src ./src
RUN pip install --no-cache-dir --no-build-isolation --no-deps .
COPY app.py ./
COPY config/.env.example ./config/.env.example
COPY participant-kit-realistic-v2-100/documents ./participant-kit-realistic-v2-100/documents
EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--browser.gatherUsageStats=false"]

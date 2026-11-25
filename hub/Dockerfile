FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HF_HOME=/data/models
WORKDIR /app
COPY requirements.txt requirements-voice.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-voice.txt
COPY app ./app
COPY roles ./roles
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

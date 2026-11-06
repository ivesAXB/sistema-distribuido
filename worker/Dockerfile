# Nó WORKER (processamento)
FROM python:3.12-slim
LABEL org.safra.papel="worker"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY comum ./comum
COPY worker/app ./app
RUN useradd -m safra
USER safra
CMD ["python", "-m", "app.main"]

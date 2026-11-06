# Nó MANAGER (coordenador)
FROM python:3.12-slim
LABEL org.safra.papel="manager"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY manager/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY comum ./comum
COPY manager/app ./app
RUN useradd -m safra
USER safra
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/saude')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

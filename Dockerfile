# Dockerfile para o microsserviço público anotae-mcp-receita
FROM python:3.11-slim

# Instalação de dependências essenciais do sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copia e instala dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia código fonte da aplicação e scripts
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY main.py .

# Cria diretório para montagem do volume de dados DuckDB
RUN mkdir -p /app/data

# Usuário não-root para segurança
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Pré-instala extensões DuckDB para evitar download em runtime sob read_only
RUN python -c "import duckdb; conn = duckdb.connect(); conn.execute('INSTALL fts;')"

ENV HOST=0.0.0.0
ENV PORT=8005
ENV DUCKDB_PATH=/app/data/rmc_empresas.duckdb
ENV PYTHONUNBUFFERED=1

EXPOSE 8005

# Healthcheck nativo
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8005/health || exit 1

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8005"]

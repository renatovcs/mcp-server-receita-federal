#!/usr/bin/env bash
# =============================================================================
# Script de Configuração do Atualizador Automático no Oracle Cloud (OCI)
# =============================================================================

set -e

PROJECT_DIR="/home/ubuntu/anotae/data"  # Ajuste para o diretório no seu servidor
VENV_DIR="$PROJECT_DIR/.venv"

echo "=== Configurando ambiente no Oracle Cloud ==="

# 1. Dependências do sistema (Oracle Linux ou Ubuntu)
if command -v apt-get &> /dev/null; then
    sudo apt-get update && sudo apt-get install -y python3 python3-pip python3-venv unzip
elif command -v dnf &> /dev/null; then
    sudo dnf install -y python3 python3-pip unzip
fi

# 2. Criação do Ambiente Virtual Python
if [ ! -d "$VENV_DIR" ]; then
    echo "Criando ambiente virtual Python..."
    python3 -m venv "$VENV_DIR"
fi

# 3. Instalação das bibliotecas necessárias
echo "Instalando dependências (DuckDB)..."
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install duckdb

# Torna o script executável
chmod +x "$PROJECT_DIR/src/atualizador_receita_cron.py"

echo ""
echo "=== Sucesso! Para agendar no cron, execute: crontab -e ==="
echo "E cole a seguinte linha para rodar todo domingo às 03:00 da manhã:"
echo ""
echo "0 3 * * 0 $VENV_DIR/bin/python $PROJECT_DIR/src/atualizador_receita_cron.py >> $PROJECT_DIR/receita/cron.log 2>&1"
echo ""

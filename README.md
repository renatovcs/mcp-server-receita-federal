# 🏢 anotae-mcp-receita

Servidor público e independente de **Model Context Protocol (MCP)** com transporte **SSE (Server-Sent Events)** para consulta analítica de dados abertos da Receita Federal (empresas ativas na Região Metropolitana de Curitiba - RMC).

---

## 📌 1. Visão Geral e Arquitetura

O `anotae-mcp-receita` foi desenvolvido para permitir que agentes de inteligência artificial (LangGraph, assistentes LLM, Claude Desktop, Cursor, etc.) busquem e recomendem prestadores de serviços formais com base em dados cadastrais públicos.

### 🛡️ Princípios Arquiteturais:
1. **Isolamento de Domínio Total:** O microsserviço não possui acesso ao banco transacional (PostgreSQL) nem a regras de negócio da aplicação principal. Trata-se de um serviço independente de catálogo público.
2. **DuckDB Singleton em Modo `read_only=True`:** A conexão com o arquivo DuckDB é inicializada uma única vez no evento de `lifespan` da aplicação ASGI FastAPI e compartilhada entre as requisições. Não há custo de abrir/fechar conexões por chamada.
3. **Segurança contra Injeção SQL:** Todas as consultas utilizam estritamente *Prepared Statements* (bind variables com `?`). Interpolação de strings em SQL é proibida no código.
4. **Busca Textual Otimizada via Full-Text Search (FTS BM25):** Cláusulas lentas como `ILIKE` foram eliminadas em favor da extensão nativa FTS do DuckDB, com stemmer em português (`portuguese`) e normalização automática de acentos (`strip_accents=1`). As buscas em 756 mil registros executam em ~100 milissegundos.

---

## 📁 2. Estrutura do Repositório

```text
anotae-mcp-receita/
├── data/
│   ├── rmc_empresas.duckdb              # Base DuckDB (756k empresas ativas + índice FTS)
│   └── empresas_ativas_rmc.parquet      # Dataset colunar original em Parquet
├── scripts/
│   └── create_fts_index.py              # Script utilitário para criação/reconstrução do índice FTS
├── src/
│   ├── __init__.py
│   ├── config.py                        # Configurações com tipagem Pydantic
│   ├── database.py                      # Conexão Singleton DuckDB (read_only)
│   ├── tools.py                         # Implementação das ferramentas com prepared statements
│   └── server.py                        # Instância do MCPServer e registro das tools
├── tests/
│   ├── __init__.py
│   └── test_tools.py                    # Testes automatizados das ferramentas
├── Dockerfile                           # Containerização leve Python 3.11-slim
├── docker-compose.yml                   # Orquestração do container com volume read-only
├── main.py                              # Entrada da aplicação FastAPI ASGI + SSE
├── requirements.txt                     # Dependências do projeto
├── .env.example                         # Exemplo de variáveis de ambiente
└── README.md                            # Esta documentação
```

---

## 🛠️ 3. Ferramentas (MCP Tools) Expostas

### 1. `search_providers_by_service`
Busca empresas ativas através do índice Full-Text Search BM25 na descrição do CNAE principal.
* **Argumentos:**
  * `query` *(string, obrigatório)*: Termo ou atividade buscada (ex: `"ar condicionado"`, `"eletricista"`, `"refrigeração"`).
  * `municipio` *(string, opcional)*: Município da RMC para filtragem (ex: `"Curitiba"`, `"São José dos Pinhais"`, `"Pinhais"`).
  * `limit` *(integer, opcional, padrão 15, máx 100)*: Limite de registros retornados.
* **Ordenação:** Relevância textual (`score DESC`) e experiência de mercado (`idade_anos DESC`).

### 2. `get_provider_details`
Retorna a ficha cadastral completa de uma empresa através do CNPJ.
* **Argumentos:**
  * `cnpj` *(string, obrigatório)*: CNPJ formatado (`00.000.000/0000-00`) ou numérico (`00000000000000`).
* **Retorno:** Razão social, nome fantasia, natureza jurídica, capital social, idade em anos, CNAE principal e secundários, endereço completo, telefone e e-mail.

### 3. `list_available_cities`
Lista os municípios cobertos pela base da RMC e a contagem de empresas ativas em cada localidade.
* **Argumentos:** Nenhum.
* **Retorno:** Lista com `municipio` e `total_empresas`.

---

## 🚀 4. Executando Localmente

### Pré-requisitos:
* Python 3.10+
* Virtualenv configurado

```bash
# 1. Clonar ou navegar até a pasta
cd anotae-mcp-receita

# 2. Criar e ativar o ambiente virtual
python3 -m venv .venv
source .venv/bin/activate

# 3. Instalar as dependências
pip install -r requirements.txt

# 4. Iniciar o servidor FastAPI / MCP SSE
python main.py
# ou: uvicorn main:app --host 0.0.0.0 --port 8005
```

O servidor estará disponível em:
* **Healthcheck:** `http://localhost:8005/health`
* **MCP SSE Endpoint:** `http://localhost:8005/sse`
* **MCP Messages Endpoint:** `http://localhost:8005/messages`

---

## 🐳 5. Executando com Docker

```bash
# Construir e iniciar o container
docker compose up -d --build

# Verificar logs
docker compose logs -f

# Testar o healthcheck
curl http://localhost:8005/health
```

---

## 🧪 6. Executando os Testes

```bash
python -m unittest tests/test_tools.py
```

---

## 🔍 7. Reconstrução do Índice Full-Text Search (FTS)

O arquivo `data/rmc_empresas.duckdb` já se encontra indexado. Caso o arquivo de dados seja atualizado com um novo lote da Receita Federal, você pode reconstruir o índice executando:

```bash
python scripts/create_fts_index.py --db-path ./data/rmc_empresas.duckdb --rebuild
```

---

## 🔌 8. Como Integrar com Clientes MCP

### Configuração no Claude Desktop (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "anotae-receita": {
      "url": "http://localhost:8005/sse"
    }
  }
}
```

### Configuração no LangGraph / LangChain Python:
```python
from langchain_mcp_adapters.client import MultiServerMCPClient

async with MultiServerMCPClient(
    {"receita": {"url": "http://localhost:8005/sse", "transport": "sse"}}
) as client:
    tools = client.get_tools()
    # injetar tools no agente LangGraph
```

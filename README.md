# 🏢 anotae-mcp-receita

Servidor público de **Model Context Protocol (MCP)** com transporte **SSE (Server-Sent Events)** para consulta analítica de dados abertos da Receita Federal. 

Permite que agentes de Inteligência Artificial (LangGraph, assistentes LLM, Cursor, Claude Desktop, etc.) busquem e validem prestadores de serviços e empresas ativas com base em dados cadastrais oficiais e busca semântica/textual BM25.

---

## 🌐 Endpoints Oficiais (Em Produção)

* **MCP SSE Endpoint (para clientes e agentes):**
  ```text
  https://mcp-receita.anotae.app.br/sse?token=anotae-receita-dev-key-123
  ```
* **Status / Healthcheck (JSON via navegador ou curl):**
  ```text
  https://mcp-receita.anotae.app.br/health
  ```
* **Métricas Prometheus:**
  ```text
  https://mcp-receita.anotae.app.br/metrics
  ```
* **Cobertura Atual:** **+2.328.000 empresas ativas**
  * **Rio de Janeiro (RJ):** ~1.571.000 empresas ativas
  * **Paraná (PR):** ~756.000 empresas ativas

---

## 🔌 Como Conectar ao MCP Server

### 1. Cursor IDE

1. Abra as configurações do Cursor (`Ctrl + Shift + J` ou ícone de engrenagem).
2. Vá em **Features** ➔ **MCP Servers** ➔ **+ Add New MCP Server**.
3. Preencha:
   * **Name:** `receita-federal`
   * **Type:** `sse`
   * **Server URL:** `https://mcp-receita.anotae.app.br/sse?token=anotae-receita-dev-key-123`

*(Ou adicione direto no seu arquivo `.cursor/mcp.json`:)*
```json
{
  "mcpServers": {
    "receita-federal": {
      "url": "https://mcp-receita.anotae.app.br/sse?token=anotae-receita-dev-key-123"
    }
  }
}
```

---

### 2. Claude Desktop

Abra seu arquivo `claude_desktop_config.json`:
* **Linux:** `~/.config/Claude/claude_desktop_config.json`
* **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
* **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

Adicione o servidor na chave `mcpServers`:
```json
{
  "mcpServers": {
    "receita-federal": {
      "url": "https://mcp-receita.anotae.app.br/sse",
      "env": {
        "AUTHORIZATION": "Bearer anotae-receita-dev-key-123"
      }
    }
  }
}
```

---

### 3. VS Code (Extensões Cline / Roo Code / Continue)

No arquivo de configuração de MCP (`cline_mcp_settings.json`):
```json
{
  "mcpServers": {
    "receita-federal": {
      "url": "https://mcp-receita.anotae.app.br/sse?token=anotae-receita-dev-key-123",
      "disabled": false,
      "autoApprove": []
    }
  }
}
```

---

### 4. LangChain & LangGraph (Python)

Instale o adaptador oficial:
```bash
pip install langchain-mcp-adapters langgraph langchain-openai
```

Código de exemplo para conectar seu agente:
```python
import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

async def main():
    async with MultiServerMCPClient(
        {
            "receita_federal": {
                "url": "https://mcp-receita.anotae.app.br/sse",
                "transport": "sse",
                "headers": {
                    "X-API-Key": "anotae-receita-dev-key-123"
                }
            }
        }
    ) as client:
        # Carrega as tools dinamicamente do servidor MCP
        tools = client.get_tools()
        print(f"Ferramentas prontas: {[t.name for t in tools]}")

        # Configura o agente
        model = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        agent = create_react_agent(model, tools)

        # Consulta de exemplo
        prompt = "Encontre 3 empresas ativas de energia solar no Rio de Janeiro e informe o CNPJ e bairro."
        response = await agent.ainvoke({"messages": [("user", prompt)]})
        print(response["messages"][-1].content)

if __name__ == "__main__":
    asyncio.run(main())
```

---

### 5. Teste Visual Interativo (MCP Inspector)

Você pode inspecionar e testar as ferramentas visualmente pelo terminal sem precisar abrir um LLM:

```bash
npx @modelcontextprotocol/inspector "https://mcp-receita.anotae.app.br/sse?token=anotae-receita-dev-key-123"
```

---

## 🛠️ Ferramentas (MCP Tools) Disponíveis

### 1. `search_providers_by_service`
Busca empresas ativas utilizando índice Full-Text Search (FTS BM25) na descrição da atividade econômica principal (CNAE).
* **Parâmetros:**
  * `query` *(string, obrigatório)*: Atividade ou termo do serviço (ex: `"energia solar"`, `"ar condicionado"`, `"eletricista"`).
  * `uf` *(string, opcional)*: Estado/UF para filtragem (ex: `"RJ"` ou `"PR"`).
  * `municipio` *(string, opcional)*: Nome da cidade (ex: `"Niterói"`, `"Curitiba"`, `"Rio de Janeiro"`).
  * `limit` *(integer, opcional, padrão 15, máx 100)*: Quantidade máxima de registros retornados.
* **Ordenação:** Relevância textual (`score DESC`) e experiência de mercado (`idade_anos DESC`).

### 2. `get_provider_details`
Retorna a ficha cadastral completa de uma empresa ativa através do CNPJ.
* **Parâmetros:**
  * `cnpj` *(string, obrigatório)*: CNPJ formatado (`00.000.000/0000-00`) ou apenas numérico (`00000000000000`).
* **Retorno:** Razão social, nome fantasia, natureza jurídica, capital social, idade em anos, CNAE principal e secundários, endereço completo, telefone e e-mail.

### 3. `list_available_cities`
Lista os municípios cobertos pela base e a contagem de empresas ativas em cada localidade.
* **Parâmetros:**
  * `uf` *(string, opcional)*: Filtra apenas as cidades do estado especificado (ex: `"RJ"` ou `"PR"`).
* **Retorno:** Lista contendo `municipio`, `uf` e `total_empresas`.

---

## 📌 Exemplos de Prompts para o Assistente

Conectado ao seu MCP, você pode fazer perguntas naturais ao assistente:

* *"Encontre 5 empresas ativas de instalação de ar condicionado em Curitiba."*
* *"Procure empresas de energia solar no Rio de Janeiro e me passe os dados cadastrais da primeira colocada."*
* *"Quais municípios do estado do Rio de Janeiro estão disponíveis e quantas empresas cada um tem?"*
* *"Consulte os detalhes completos da empresa de CNPJ 00.000.000/0001-00."*

---

## 🚀 Executando Localmente (Desenvolvimento)

### Pré-requisitos
* Python 3.10+
* Virtualenv

```bash
# 1. Clonar o repositório
git clone https://github.com/renatovcs/mcp-server-receita-federal.git
cd mcp-server-receita-federal

# 2. Criar e ativar o ambiente virtual
python3 -m venv .venv
source .venv/bin/activate

# 3. Instalar dependências
pip install -r requirements.txt

# 4. Iniciar o servidor
python main.py
```

Endpoints locais:
* **Healthcheck:** `http://localhost:8005/health`
* **MCP SSE:** `http://localhost:8005/sse`

---

## 🐳 Executando com Docker

```bash
# Iniciar o container
docker compose up -d --build

# Verificar logs
docker compose logs -f

# Testar healthcheck
curl http://localhost:8005/health
```

---

## 🧪 Executando os Testes Automatizados

A suíte valida as consultas FTS em múltiplas regiões (PR e RJ) e o tempo de resposta:

```bash
python -m unittest tests/test_tools.py
```

---

## 📁 Estrutura do Repositório

```text
mcp-server-receita-federal/
├── data/
│   ├── empresas_ativas.duckdb            # Base unificada com 2.3M de empresas e índice FTS BM25
│   ├── empresas_ativas_rmc.parquet       # Dataset colunar Parquet (Curitiba/PR)
│   └── empresas_ativas_rmrj.parquet      # Dataset colunar Parquet (Rio de Janeiro/RJ)
├── scripts/
│   ├── unificar_bases.py                 # Pipeline de consolidação e criação do índice FTS BM25
│   └── create_fts_index.py               # Utilitário para reconstrução de índices
├── src/
│   ├── config.py                         # Configurações Pydantic
│   ├── database.py                       # Conexão Singleton DuckDB (modo read_only)
│   ├── tools.py                          # Implementação das ferramentas com Prepared Statements
│   └── server.py                         # Instância do MCPServer e registro das rotas
├── tests/
│   └── test_tools.py                     # Suíte de testes unitários e integração
├── Dockerfile                            # Imagem leve baseada em Python 3.11-slim
├── docker-compose.yml                    # Orquestração do container
├── main.py                               # Entrada FastAPI ASGI + SSE
├── requirements.txt                      # Dependências do microsserviço
└── README.md                             # Esta documentação
```

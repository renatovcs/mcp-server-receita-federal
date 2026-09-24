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

## 🌟 Arquitetura e Recursos de Produção

Este projeto foi construído seguindo as melhores práticas de Engenharia de Software e está pronto para ambientes de nível Enterprise:

1. **Tipagem Forte e Pydantic:** Todas as ferramentas retornam modelos de dados rigorosos (Pydantic BaseModel), que geram automaticamente um JSON Schema completo. Isso impede que Agentes LLM "alucinem" propriedades inexistentes.
2. **Segurança (API Key / Token):** O acesso MCP é bloqueado por padrão, exigindo uma chave de autenticação passada via Query Parameter (`?token=...`) ou HTTP Headers (`X-API-Key` / `Authorization`).
3. **Observabilidade e Métricas (APM):** 
   - Os logs da aplicação são exportados em formato **JSON estruturado** usando a biblioteca `structlog`, prontos para Datadog ou AWS CloudWatch.
   - Um endpoint `/metrics` expõe a saúde em tempo real do sistema para o **Prometheus** e **Grafana**.
4. **Cache em Memória (RAM):** Consultas recentes, detalhes de CNPJs frequentes e agregados por município são armazenados em memória (via `cachetools`), respondendo em ~1 milissegundo e economizando recursos de CPU do DuckDB.
5. **Automação de Deploy (CI/CD):** Integração e Entrega Contínuas já configuradas via **GitHub Actions**. Atualizações sobem para o servidor Oracle sem toque manual.

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

### 4. `analyze_market_competition`
Executa uma análise de inteligência de mercado agregando dados reais sobre um segmento.
* **Parâmetros:**
  * `query` *(string, obrigatório)*: Segmento ou nicho de mercado (ex: `"energia solar"`, `"construtora"`).
  * `uf` *(string, opcional)*: Foca a análise em um Estado (ex: `"RJ"` ou `"PR"`).
  * `municipio` *(string, opcional)*: Foca a análise em um município (ex: `"Curitiba"`).
* **Retorno:** Relatório detalhado com o total de empresas concorrentes, média de capital social no setor, média de tempo de mercado (idade das empresas) e os 5 bairros com maior concentração deste serviço.

### 5. `get_biggest_companies_by_capital`
Busca os líderes de mercado e empresas de grande porte em um segmento, ordenadas pelo Capital Social.
* **Parâmetros:**
  * `query` *(string, obrigatório)*: Segmento ou nicho (ex: `"energia solar"`, `"tecnologia"`).
  * `uf` *(string, opcional)*: Filtrar por Estado.
  * `municipio` *(string, opcional)*: Filtrar por Município.
  * `limit` *(integer, opcional, padrão 5)*: Quantidade de empresas a retornar.
* **Retorno:** Lista de empresas (CNPJ, Razão Social, Capital Social, Idade, etc.) ordenadas do maior capital para o menor.

### 6. `search_company_by_name`
Busca uma empresa ativa diretamente pelo seu nome exato ou parte dele (Razão Social ou Nome Fantasia).
* **Parâmetros:**
  * `name` *(string, obrigatório)*: Nome da empresa (ex: `"Oficina do João"`, `"Tech Solutions LTDA"`).
  * `uf` *(string, opcional)*: Limitar a busca a um Estado (ex: `"PR"` ou `"RJ"`).
  * `limit` *(integer, opcional, padrão 15)*: Quantidade de empresas a retornar.
* **Retorno:** Lista de empresas correspondentes.

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

---

## 🤖 CI/CD Automático (GitHub Actions)

Este repositório conta com um fluxo de **Continuous Deployment (CD)** configurado em `.github/workflows/deploy.yml`. 
Toda vez que você fizer um `git push` na branch `main`, o GitHub conectará automaticamente no seu servidor Oracle via SSH e fará o deploy da nova versão.

Para que isso funcione, adicione as seguintes **Secrets** no seu repositório no GitHub (*Settings > Secrets and variables > Actions*):

* `SSH_HOST`: O IP público do seu servidor (ex: `141.148.38.30`)
* `SSH_USERNAME`: O usuário de acesso (ex: `ubuntu`)
* `SSH_PRIVATE_KEY`: O conteúdo da sua chave privada (geralmente em `~/.ssh/id_rsa` ou `~/.ssh/id_ed25519`)


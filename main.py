"""
Ponto de entrada do microsserviço anotae-mcp-receita.
Servidor ASGI FastAPI com transporte MCP SSE (Server-Sent Events) e conexão DuckDB Singleton via lifespan.
"""

from contextlib import asynccontextmanager
import logging
from typing import AsyncGenerator
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn

from src.config import settings
from src.database import db_manager
from src.server import mcp_server
from mcp.server.transport_security import TransportSecuritySettings

# Configuração de Logs Estruturados
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("anotae_mcp.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Gerenciamento do ciclo de vida da aplicação ASGI.
    Instancia a conexão DuckDB globalmente como Singleton em modo read_only=True.
    """
    logger.info(f"Iniciando serviço {settings.SERVICE_NAME} v{settings.SERVICE_VERSION}...")
    try:
        db_manager.initialize(settings.DUCKDB_PATH)
        logger.info("Banco DuckDB pronto para processar requisições analíticas.")
    except Exception as e:
        logger.critical(f"Falha fatal ao inicializar banco de dados: {e}")
        raise

    yield

    logger.info("Executando encerramento gracioso do serviço...")
    db_manager.close()
    logger.info("Serviço encerrado com sucesso.")


# Criação da aplicação FastAPI com Lifespan ASGI
app = FastAPI(
    title=settings.SERVICE_NAME,
    version=settings.SERVICE_VERSION,
    description="Servidor MCP público para busca analítica de prestadores e empresas ativas da Receita Federal na RMC.",
    lifespan=lifespan,
)


@app.get("/health", tags=["Monitoramento"])
async def health_check() -> JSONResponse:
    """
    Endpoint de sondagem de saúde (Liveness/Readiness Probe).
    Informa o estado da conexão DuckDB e contagem de registros disponíveis.
    """
    is_connected = db_manager.is_connected
    status_code = 200 if is_connected else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "healthy" if is_connected else "unhealthy",
            "service": settings.SERVICE_NAME,
            "version": settings.SERVICE_VERSION,
            "database": {
                "engine": "DuckDB",
                "connected": is_connected,
                "read_only": True,
                "total_empresas_ativas": db_manager.total_empresas,
                "path": str(settings.DUCKDB_PATH),
            },
            "endpoints": {
                "mcp_sse": "/sse",
                "mcp_messages": "/messages",
                "health": "/health",
            },
        },
    )


# Acopla a aplicação Starlette SSE do MCP Server às rotas da aplicação ASGI
# O MCP Server expõe /sse (Stream de eventos SSE) e /messages (POST para recepção de comandos JSON-RPC)
# Desativa a validação rígida de localhost para permitir conexões via IP público ou domínio remoto
app.mount(
    "",
    mcp_server.sse_app(
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        )
    ),
)


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
        log_level="info",
    )

"""
Ponto de entrada do microsserviço anotae-mcp-receita.
Servidor ASGI FastAPI com transporte MCP SSE (Server-Sent Events) e conexão DuckDB Singleton via lifespan.
"""

from contextlib import asynccontextmanager
import logging
from typing import AsyncGenerator
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn
import secrets

from src.config import settings
from src.database import db_manager
from src.server import mcp_server
from mcp.server.transport_security import TransportSecuritySettings
import structlog
from prometheus_fastapi_instrumentator import Instrumentator

# Configuração de Logs Estruturados em JSON
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
)
logging.basicConfig(format="%(message)s", level=logging.INFO)
logger = structlog.get_logger("anotae_mcp.main")


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

# Instrumentação do Prometheus (Métricas)
Instrumentator().instrument(app).expose(app)


from urllib.parse import parse_qsl
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.responses import Response


class PureASGIAuthMiddleware:
    """
    Middleware ASGI nativo de alta performance para autenticação de API Key.
    Não utiliza BaseHTTPMiddleware, eliminando erros de buffering em streams SSE (Server-Sent Events).
    Permite autenticação via token na URL, header X-API-Key ou Authorization.
    Permite mensagens POST com session_id já autenticado na conexão SSE e desativa probes de OAuth.
    """
    def __init__(self, app: ASGIApp, api_key: str):
        self.app = app
        self.api_key = api_key

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        method = scope.get("method", "")

        # 1. Rotas públicas ou preflight CORS
        if path == "/health" or method == "OPTIONS":
            return await self.app(scope, receive, send)

        # 2. Retorna 404 para probes de OAuth (evita que o MCP Inspector v2.8.0 tente Dynamic Client Registration)
        if path.startswith("/.well-known/") or path in ("/register", "/oauth/register"):
            response = Response(
                status_code=404,
                content=b'{"detail": "OAuth registration not supported"}',
                media_type="application/json"
            )
            return await response(scope, receive, send)

        # 3. Extrai query parameters
        query_string = scope.get("query_string", b"").decode("latin-1")
        query_params = dict(parse_qsl(query_string))

        # 4. Extrai headers
        headers = dict(scope.get("headers", []))
        token = query_params.get("token")
        if not token:
            token = headers.get(b"x-api-key", b"").decode("latin-1") or None
        if not token:
            auth_header = headers.get(b"authorization", b"").decode("latin-1")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ", 1)[1]

        # 5. Validação da chave de autenticação
        is_token_valid = token and secrets.compare_digest(token, self.api_key)

        # 6. Se for mensagem POST MCP (/messages) com session_id, permite
        # (O session_id só é gerado se o cliente conectou em /sse com token válido)
        if path.startswith("/messages") and method == "POST" and "session_id" in query_params:
            return await self.app(scope, receive, send)

        # 7. Se for /sse ou qualquer outra requisição sem token válido -> 401
        if not is_token_valid:
            response = Response(
                status_code=401,
                content=b'{"detail": "Unauthorized. Invalid or missing API Key (token)."}',
                media_type="application/json",
            )
            return await response(scope, receive, send)

        return await self.app(scope, receive, send)


app.add_middleware(PureASGIAuthMiddleware, api_key=settings.API_KEY)


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
                "memory_limit": db_manager.memory_limit,
                "threads": db_manager.threads,
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

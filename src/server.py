"""
Servidor MCP (Model Context Protocol) para consulta de dados abertos da Receita Federal.
Registra as ferramentas padronizadas para consumo por agentes e clientes MCP.
"""

from typing import Any, Dict, List, Optional
from mcp.server.mcpserver import MCPServer

from src.config import settings
from src.tools import (
    get_provider_details as db_get_provider_details,
    list_available_cities as db_list_available_cities,
    search_providers_by_service as db_search_providers_by_service,
)

# Cria a instância do servidor MCP com metadados do serviço
mcp_server = MCPServer(
    name=settings.SERVICE_NAME,
    instructions="Servidor MCP público para busca analítica de prestadores e empresas ativas da Receita Federal na RMC.",
)


@mcp_server.tool()
def search_providers_by_service(
    query: str,
    municipio: Optional[str] = None,
    limit: int = 15,
) -> List[Dict[str, Any]]:
    """
    Busca prestadores de serviço ativos na Região Metropolitana de Curitiba (RMC)
    utilizando índice Full-Text Search (FTS BM25) na descrição do CNAE principal.

    Args:
        query: Termo de busca (ex: 'ar condicionado', 'refrigeração', 'eletricista', 'pintor').
        municipio: (Opcional) Nome da cidade na RMC para filtrar os resultados (ex: 'Curitiba', 'Pinhais', 'São José dos Pinhais').
        limit: Quantidade máxima de registros a retornar (padrão 15, máx 100).
    """
    return db_search_providers_by_service(query=query, municipio=municipio, limit=limit)


@mcp_server.tool()
def get_provider_details(cnpj: str) -> Optional[Dict[str, Any]]:
    """
    Consulta a ficha cadastral completa de uma empresa ativa através do seu CNPJ.

    Args:
        cnpj: CNPJ da empresa (com ou sem pontuação/máscara).
    """
    return db_get_provider_details(cnpj=cnpj)


@mcp_server.tool()
def list_available_cities() -> List[Dict[str, Any]]:
    """
    Lista todos os municípios cobertos na Região Metropolitana de Curitiba (RMC)
    com a quantidade total de empresas ativas em cada um.
    """
    return db_list_available_cities()

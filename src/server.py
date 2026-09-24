"""
Servidor MCP (Model Context Protocol) para consulta de dados abertos da Receita Federal.
Registra as ferramentas padronizadas para consumo por agentes e clientes MCP.
Suporta consultas unificadas em múltiplas regiões (Paraná e Rio de Janeiro).
"""

from typing import Any, Dict, List, Optional
from mcp.server.mcpserver import MCPServer

from src.config import settings
from src.models import EmpresaResumo, EmpresaDetalhe, MunicipioEstatistica, AnaliseMercado, EmpresaCapital
from src.tools import (
    get_provider_details as db_get_provider_details,
    list_available_cities as db_list_available_cities,
    search_providers_by_service as db_search_providers_by_service,
    analyze_market_competition as db_analyze_market_competition,
    get_biggest_companies_by_capital as db_get_biggest_companies_by_capital,
    search_company_by_name as db_search_company_by_name,
)

# Cria a instância do servidor MCP com metadados do serviço
mcp_server = MCPServer(
    name=settings.SERVICE_NAME,
    instructions="Servidor MCP público para busca analítica de prestadores e empresas ativas da Receita Federal (PR e RJ).",
)


@mcp_server.tool()
def search_providers_by_service(
    query: str,
    uf: Optional[str] = None,
    municipio: Optional[str] = None,
    bairro: Optional[str] = None,
    limit: int = 15,
    offset: int = 0,
) -> List[EmpresaResumo]:
    """
    Busca prestadores de serviço ativos utilizando índice Full-Text Search (FTS BM25) na descrição do CNAE principal.

    Args:
        query: Termo de busca (ex: 'ar condicionado', 'refrigeração', 'eletricista', 'pintor', 'energia solar').
        uf: (Opcional) Estado para filtrar os resultados (ex: 'PR' ou 'RJ').
        municipio: (Opcional) Nome da cidade para filtrar os resultados (ex: 'Curitiba', 'Rio de Janeiro', 'Niterói').
        bairro: (Opcional) Nome do bairro ou região (ex: 'Batel', 'Centro', 'Barra da Tijuca').
        limit: Quantidade máxima de registros a retornar (padrão 15, máx 100).
        offset: Deslocamento para paginação de resultados (padrão 0).
    """
    return db_search_providers_by_service(
        query=query, uf=uf, municipio=municipio, bairro=bairro, limit=limit, offset=offset
    )


@mcp_server.tool()
def get_provider_details(cnpj: str) -> Optional[EmpresaDetalhe]:
    """
    Consulta a ficha cadastral completa de uma empresa ativa através do seu CNPJ.

    Args:
        cnpj: CNPJ da empresa (com ou sem pontuação/máscara).
    """
    return db_get_provider_details(cnpj=cnpj)


@mcp_server.tool()
def list_available_cities(uf: Optional[str] = None) -> List[MunicipioEstatistica]:
    """
    Lista todos os municípios cobertos na base de dados com a quantidade total de empresas ativas em cada um.

    Args:
        uf: (Opcional) Filtrar cidades por Estado (ex: 'PR' ou 'RJ').
    """
    return db_list_available_cities(uf=uf)

@mcp_server.tool()
def analyze_market_competition(
    query: str,
    uf: Optional[str] = None,
    municipio: Optional[str] = None,
) -> Optional[AnaliseMercado]:
    """
    Executa uma análise de mercado avançada sobre um segmento específico.
    Retorna estatísticas consolidadas: densidade da concorrência, capital social médio, tempo de mercado e os bairros com mais concorrentes.

    Args:
        query: Termo de busca que define o segmento/nicho de mercado (ex: 'energia solar', 'construtora', 'pet shop').
        uf: (Opcional) Estado para concentrar a análise (ex: 'PR' ou 'RJ').
        municipio: (Opcional) Nome da cidade para focar a análise (ex: 'Curitiba', 'Rio de Janeiro').
    """
    return db_analyze_market_competition(query=query, uf=uf, municipio=municipio)

@mcp_server.tool()
def get_biggest_companies_by_capital(
    query: str,
    uf: Optional[str] = None,
    municipio: Optional[str] = None,
    limit: int = 5,
    offset: int = 0,
) -> List[EmpresaCapital]:
    """
    Busca as maiores empresas de um determinado segmento de mercado (query) ordenadas pelo Capital Social declarado na Receita Federal.
    Utilidade: Encontrar líderes de mercado, empresas de grande porte ou grandes fornecedores B2B.

    Args:
        query: Termo de busca do serviço ou produto (ex: 'construtora', 'tecnologia', 'transporte').
        uf: (Opcional) Estado para focar a busca (ex: 'PR' ou 'RJ').
        municipio: (Opcional) Nome da cidade para focar a busca (ex: 'Curitiba').
        limit: Quantidade máxima de resultados (padrão 5, máx 100).
        offset: Deslocamento para paginação (padrão 0).
    """
    return db_get_biggest_companies_by_capital(
        query=query, uf=uf, municipio=municipio, limit=limit, offset=offset
    )

@mcp_server.tool()
def search_company_by_name(
    name: str,
    uf: Optional[str] = None,
    municipio: Optional[str] = None,
    limit: int = 15,
    offset: int = 0,
) -> List[EmpresaResumo]:
    """
    Busca uma empresa ativa diretamente pelo seu NOME (Razão Social ou Nome Fantasia).
    Utilidade: Quando o usuário sabe o nome da empresa e quer encontrar o seu CNPJ ou detalhes.

    Args:
        name: O nome da empresa (ex: 'Oficina do João', 'Tech Solutions LTDA').
        uf: (Opcional) Limitar a busca a um Estado (ex: 'PR', 'RJ').
        municipio: (Opcional) Limitar a busca a um Município (ex: 'Curitiba', 'Rio de Janeiro').
        limit: Quantidade máxima de resultados (padrão 15).
        offset: Deslocamento para paginação (padrão 0).
    """
    return db_search_company_by_name(
        name=name, uf=uf, municipio=municipio, limit=limit, offset=offset
    )

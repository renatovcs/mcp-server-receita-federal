"""
Implementação das ferramentas (Tools) do Model Context Protocol (MCP).
Todas as consultas utilizam estritamente Prepared Statements (bind variables com `?`).
Busca textual otimizada via DuckDB Full-Text Search (FTS BM25).
"""

import logging
import re
from typing import Any, Dict, List, Optional
from src.config import settings
from src.database import db_manager

logger = logging.getLogger("anotae_mcp.tools")


def search_providers_by_service(
    query: str,
    municipio: Optional[str] = None,
    limit: int = 15,
) -> List[Dict[str, Any]]:
    """
    Busca prestadores de serviço ativos na RMC utilizando índice Full-Text Search (FTS BM25)
    na descrição da atividade econômica principal (CNAE).

    Args:
        query: Termo ou expressão do serviço (ex: 'ar condicionado', 'eletricista', 'pintura').
        municipio: Filtro opcional por município da RMC (ex: 'Curitiba', 'São José dos Pinhais').
        limit: Quantidade máxima de resultados (padrão 15, máximo 100).

    Returns:
        Lista de empresas ordenadas por relevância FTS e tempo de mercado.
    """
    cleaned_query = query.strip()
    if not cleaned_query:
        return []

    # Sanitização e limitação defensiva de paginação
    safe_limit = max(1, min(limit, settings.MAX_SEARCH_LIMIT))
    cleaned_municipio = municipio.strip() if municipio and municipio.strip() else None

    conn = db_manager.get_connection()

    sql = """
        SELECT 
            cnpj,
            razao_social,
            nome_fantasia,
            porte_empresa,
            data_inicio_atividade::VARCHAR AS data_inicio_atividade,
            idade_anos,
            cnae_fiscal_principal,
            descricao_cnae_principal,
            logradouro,
            numero,
            complemento,
            bairro,
            cep,
            municipio,
            uf,
            telefone_1,
            email,
            ROUND(score, 4) AS fts_score
        FROM (
            SELECT 
                *,
                fts_main_tb_empresas_ativas_rmc.match_bm25(cnpj, ?) AS score
            FROM tb_empresas_ativas_rmc
        ) sq
        WHERE score IS NOT NULL
          AND (? IS NULL OR LOWER(municipio) = LOWER(?))
        ORDER BY score DESC, idade_anos DESC
        LIMIT ?;
    """

    params = [cleaned_query, cleaned_municipio, cleaned_municipio, safe_limit]
    
    try:
        cursor = conn.execute(sql, params)
        column_names = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        return [dict(zip(column_names, row)) for row in rows]
    except Exception as e:
        logger.error(f"Erro ao executar busca FTS para query='{cleaned_query}': {e}", exc_info=True)
        raise RuntimeError(f"Falha na consulta FTS: {e}") from e


def get_provider_details(cnpj: str) -> Optional[Dict[str, Any]]:
    """
    Retorna os detalhes cadastrais completos de uma empresa ativa pelo CNPJ.

    Args:
        cnpj: CNPJ do prestador (com ou sem pontuação).

    Returns:
        Dicionário com os dados completos da empresa ou None se não encontrada.
    """
    cleaned_cnpj = cnpj.strip()
    if not cleaned_cnpj:
        return None

    # Normaliza CNPJ (remove caracteres não numéricos)
    digits_only = re.sub(r"\D", "", cleaned_cnpj)
    
    # Gera a máscara padrão caso possua 14 dígitos (ex: 00.000.000/0000-00)
    if len(digits_only) == 14:
        masked_cnpj = f"{digits_only[:2]}.{digits_only[2:5]}.{digits_only[5:8]}/{digits_only[8:12]}-{digits_only[12:14]}"
    else:
        masked_cnpj = cleaned_cnpj

    conn = db_manager.get_connection()

    sql = """
        SELECT 
            cnpj,
            cnpj_basico,
            razao_social,
            nome_fantasia,
            matriz_filial,
            porte_empresa,
            capital_social,
            codigo_natureza_juridica,
            natureza_juridica,
            data_inicio_atividade::VARCHAR AS data_inicio_atividade,
            idade_anos,
            cnae_fiscal_principal,
            descricao_cnae_principal,
            cnae_fiscal_secundaria,
            tipo_logradouro,
            logradouro,
            numero,
            complemento,
            bairro,
            cep,
            municipio,
            uf,
            endereco_completo,
            telefone_1,
            telefone_2,
            email
        FROM tb_empresas_ativas_rmc
        WHERE cnpj = ? OR cnpj = ?
        LIMIT 1;
    """

    params = [cleaned_cnpj, masked_cnpj]

    try:
        cursor = conn.execute(sql, params)
        row = cursor.fetchone()
        if not row:
            return None
        column_names = [desc[0] for desc in cursor.description]
        return dict(zip(column_names, row))
    except Exception as e:
        logger.error(f"Erro ao buscar detalhes para CNPJ='{cleaned_cnpj}': {e}", exc_info=True)
        raise RuntimeError(f"Falha na consulta por CNPJ: {e}") from e


def list_available_cities() -> List[Dict[str, Any]]:
    """
    Retorna os municípios disponíveis na base da Região Metropolitana de Curitiba (RMC)
    com a quantidade de empresas ativas em cada localidade.

    Returns:
        Lista ordenada por volume de empresas ativas.
    """
    conn = db_manager.get_connection()

    sql = """
        SELECT 
            municipio,
            COUNT(*) AS total_empresas
        FROM tb_empresas_ativas_rmc
        GROUP BY municipio
        ORDER BY total_empresas DESC;
    """

    try:
        cursor = conn.execute(sql)
        column_names = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        return [dict(zip(column_names, row)) for row in rows]
    except Exception as e:
        logger.error(f"Erro ao listar municípios disponíveis: {e}", exc_info=True)
        raise RuntimeError(f"Falha ao listar municípios: {e}") from e

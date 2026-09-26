"""
Implementação das ferramentas (Tools) do Model Context Protocol (MCP).
Todas as consultas utilizam estritamente Prepared Statements (bind variables com `?`).
Busca textual otimizada via DuckDB Full-Text Search (FTS BM25).
Suporta busca em todas as regiões cadastradas (Paraná, Rio de Janeiro, São Paulo e futuras expansões).
"""

import re
from typing import Any, Dict, List, Optional
import structlog
from cachetools import cached, TTLCache

from src.config import settings
from src.database import db_manager
from src.models import EmpresaResumo, EmpresaDetalhe, MunicipioEstatistica, AnaliseMercado, BairroEstatistica, EmpresaCapital

logger = structlog.get_logger("anotae_mcp.tools")


def _get_active_table_and_fts_func(conn) -> tuple[str, str]:
    """Detecta dinamicamente a tabela disponível no DuckDB (tb_empresas_ativas ou tb_empresas_ativas_rmc)."""
    tables = [t[0] for t in conn.execute("SHOW TABLES;").fetchall()]
    if "tb_empresas_ativas" in tables:
        return "tb_empresas_ativas", "fts_main_tb_empresas_ativas.match_bm25"
    return "tb_empresas_ativas_rmc", "fts_main_tb_empresas_ativas_rmc.match_bm25"


# Configuração dos Caches em Memória
# Evita reconsultar o DuckDB para perguntas repetitivas, economizando CPU.
search_cache = TTLCache(maxsize=1024, ttl=3600)    # 1024 buscas por 1 hora
details_cache = TTLCache(maxsize=2048, ttl=3600)   # 2048 CNPJs por 1 hora
cities_cache = TTLCache(maxsize=10, ttl=86400)     # Cidades por 24 horas (quase estático)
market_cache = TTLCache(maxsize=512, ttl=3600)     # 512 análises de mercado por 1 hora
capital_cache = TTLCache(maxsize=512, ttl=3600)    # 512 buscas por capital
name_cache = TTLCache(maxsize=1024, ttl=3600)      # 1024 buscas nominais por 1 hora

@cached(cache=search_cache)
def search_providers_by_service(
    query: str,
    uf: Optional[str] = None,
    municipio: Optional[str] = None,
    bairro: Optional[str] = None,
    limit: int = 15,
    offset: int = 0,
) -> List[EmpresaResumo]:
    """
    Busca prestadores de serviço ativos utilizando índice Full-Text Search (FTS BM25)
    na descrição da atividade econômica principal (CNAE).

    Args:
        query: Termo ou expressão do serviço (ex: 'ar condicionado', 'eletricista', 'energia solar').
        uf: Filtro opcional por Unidade Federativa / Estado (ex: 'PR', 'RJ', 'SP').
        municipio: Filtro opcional por município (ex: 'Curitiba', 'Rio de Janeiro', 'São Paulo').
        bairro: Filtro opcional por bairro ou região (ex: 'Batel', 'Centro', 'Barra da Tijuca', 'Pinheiros').
        limit: Quantidade máxima de resultados (padrão 15, máximo 100).
        offset: Deslocamento para paginação de resultados (padrão 0).

    Returns:
        Lista de empresas ordenadas por relevância FTS e tempo de mercado.
    """
    cleaned_query = query.strip()
    if not cleaned_query:
        return []

    # Sanitização defensiva de parâmetros
    safe_limit = max(1, min(limit, settings.MAX_SEARCH_LIMIT))
    safe_offset = max(0, offset)
    cleaned_uf = uf.strip().upper() if uf and uf.strip() else None
    cleaned_municipio = municipio.strip() if municipio and municipio.strip() else None
    cleaned_bairro = f"%{bairro.strip().lower()}%" if bairro and bairro.strip() else None

    conn = db_manager.get_connection()
    table_name, fts_func = _get_active_table_and_fts_func(conn)

    sql = f"""
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
                {fts_func}(cnpj, ?) AS score
            FROM {table_name}
        ) sq
        WHERE score IS NOT NULL
          AND (? IS NULL OR UPPER(uf) = UPPER(?))
          AND (? IS NULL OR LOWER(municipio) = LOWER(?))
          AND (? IS NULL OR LOWER(bairro) LIKE ?)
        ORDER BY score DESC, idade_anos DESC
        LIMIT ? OFFSET ?;
    """

    params = [
        cleaned_query,
        cleaned_uf,
        cleaned_uf,
        cleaned_municipio,
        cleaned_municipio,
        cleaned_bairro,
        cleaned_bairro,
        safe_limit,
        safe_offset,
    ]

    cursor = conn.cursor()
    try:
        cursor.execute(sql, params)
        column_names = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        return [EmpresaResumo(**dict(zip(column_names, row))) for row in rows]
    except Exception as e:
        logger.error(f"Erro ao executar busca FTS para query='{cleaned_query}': {e}", exc_info=True)
        raise RuntimeError(f"Falha na consulta FTS: {e}") from e
    finally:
        cursor.close()


@cached(cache=details_cache)
def get_provider_details(cnpj: str) -> Optional[EmpresaDetalhe]:
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
    table_name, _ = _get_active_table_and_fts_func(conn)

    sql = f"""
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
        FROM {table_name}
        WHERE cnpj = ? OR cnpj = ?
        LIMIT 1;
    """

    params = [cleaned_cnpj, masked_cnpj]

    cursor = conn.cursor()
    try:
        cursor.execute(sql, params)
        row = cursor.fetchone()
        if not row:
            return None
        column_names = [desc[0] for desc in cursor.description]
        return EmpresaDetalhe(**dict(zip(column_names, row)))
    except Exception as e:
        logger.error(f"Erro ao buscar detalhes para CNPJ='{cleaned_cnpj}': {e}", exc_info=True)
        raise RuntimeError(f"Falha na consulta por CNPJ: {e}") from e
    finally:
        cursor.close()


@cached(cache=cities_cache)
def list_available_cities(uf: Optional[str] = None) -> List[MunicipioEstatistica]:
    """
    Retorna os municípios disponíveis na base com a contagem de empresas ativas.
    Pode ser filtrado opcionalmente por UF (ex: 'PR', 'RJ' ou 'SP').

    Returns:
        Lista ordenada por volume de empresas ativas.
    """
    conn = db_manager.get_connection()
    table_name, _ = _get_active_table_and_fts_func(conn)
    cleaned_uf = uf.strip().upper() if uf and uf.strip() else None

    sql = f"""
        SELECT 
            municipio,
            uf,
            COUNT(*) AS total_empresas
        FROM {table_name}
        WHERE (? IS NULL OR UPPER(uf) = UPPER(?))
        GROUP BY municipio, uf
        ORDER BY total_empresas DESC;
    """

    cursor = conn.cursor()
    try:
        cursor.execute(sql, [cleaned_uf, cleaned_uf])
        column_names = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        return [MunicipioEstatistica(**dict(zip(column_names, row))) for row in rows]
    except Exception as e:
        logger.error(f"Erro ao listar municípios disponíveis: {e}", exc_info=True)
        raise RuntimeError(f"Falha ao listar municípios: {e}") from e
    finally:
        cursor.close()

@cached(cache=market_cache)
def analyze_market_competition(
    query: str,
    uf: Optional[str] = None,
    municipio: Optional[str] = None,
) -> Optional[AnaliseMercado]:
    """
    Executa uma análise agregada de mercado para um segmento específico (query).
    
    Returns:
        Um relatório AnaliseMercado ou None se o segmento não existir.
    """
    cleaned_query = query.strip()
    if not cleaned_query:
        return None

    cleaned_uf = uf.strip().upper() if uf and uf.strip() else None
    cleaned_municipio = municipio.strip() if municipio and municipio.strip() else None

    conn = db_manager.get_connection()
    table_name, fts_func = _get_active_table_and_fts_func(conn)

    sql_stats = f"""
        SELECT 
            COUNT(*) as total_empresas,
            COALESCE(AVG(capital_social), 0.0) as media_capital,
            COALESCE(AVG(idade_anos), 0.0) as media_idade
        FROM (
            SELECT 
                *,
                {fts_func}(cnpj, ?) AS score
            FROM {table_name}
        ) sq
        WHERE score IS NOT NULL
          AND (? IS NULL OR UPPER(uf) = UPPER(?))
          AND (? IS NULL OR LOWER(municipio) = LOWER(?));
    """

    sql_bairros = f"""
        SELECT 
            COALESCE(bairro, 'NÃO INFORMADO') as bairro,
            COUNT(*) as quantidade
        FROM (
            SELECT 
                *,
                {fts_func}(cnpj, ?) AS score
            FROM {table_name}
        ) sq
        WHERE score IS NOT NULL
          AND (? IS NULL OR UPPER(uf) = UPPER(?))
          AND (? IS NULL OR LOWER(municipio) = LOWER(?))
        GROUP BY bairro
        ORDER BY quantidade DESC
        LIMIT 5;
    """

    params = [
        cleaned_query,
        cleaned_uf,
        cleaned_uf,
        cleaned_municipio,
        cleaned_municipio,
    ]

    cursor = conn.cursor()
    try:
        cursor.execute(sql_stats, params)
        row = cursor.fetchone()
        
        if not row or row[0] == 0:
            return None
            
        total_empresas = int(row[0])
        media_capital = round(float(row[1]), 2)
        media_idade = round(float(row[2]), 1)
        
        cursor.execute(sql_bairros, params)
        bairros_rows = cursor.fetchall()
        
        top_bairros = [
            BairroEstatistica(bairro=b[0], quantidade=int(b[1])) 
            for b in bairros_rows
        ]
        
        return AnaliseMercado(
            termo_buscado=cleaned_query,
            uf=cleaned_uf,
            municipio=cleaned_municipio,
            total_empresas=total_empresas,
            capital_social_medio=media_capital,
            idade_media_anos=media_idade,
            top_5_bairros_concorrencia=top_bairros
        )

    except Exception as e:
        logger.error(f"Erro ao analisar concorrência de mercado para query='{cleaned_query}': {e}", exc_info=True)
        raise RuntimeError(f"Falha na análise de mercado: {e}") from e
    finally:
        cursor.close()

@cached(cache=capital_cache)
def get_biggest_companies_by_capital(
    query: str,
    uf: Optional[str] = None,
    municipio: Optional[str] = None,
    limit: int = 5,
    offset: int = 0,
) -> List[EmpresaCapital]:
    """
    Busca as maiores empresas (por capital social declarado) em um segmento específico.
    """
    cleaned_query = query.strip()
    if not cleaned_query:
        return []

    safe_limit = max(1, min(limit, settings.MAX_SEARCH_LIMIT))
    safe_offset = max(0, offset)
    cleaned_uf = uf.strip().upper() if uf and uf.strip() else None
    cleaned_municipio = municipio.strip() if municipio and municipio.strip() else None

    conn = db_manager.get_connection()
    table_name, fts_func = _get_active_table_and_fts_func(conn)

    sql = f"""
        SELECT 
            cnpj,
            razao_social,
            COALESCE(capital_social, 0.0) as capital_social,
            municipio,
            uf,
            COALESCE(idade_anos, 0.0) as idade_anos,
            descricao_cnae_principal,
            porte_empresa
        FROM (
            SELECT 
                *,
                {fts_func}(cnpj, ?) AS score
            FROM {table_name}
        ) sq
        WHERE score IS NOT NULL
          AND (? IS NULL OR UPPER(uf) = UPPER(?))
          AND (? IS NULL OR LOWER(municipio) = LOWER(?))
        ORDER BY capital_social DESC
        LIMIT ? OFFSET ?;
    """

    params = [
        cleaned_query,
        cleaned_uf,
        cleaned_uf,
        cleaned_municipio,
        cleaned_municipio,
        safe_limit,
        safe_offset,
    ]

    cursor = conn.cursor()
    try:
        cursor.execute(sql, params)
        column_names = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        return [EmpresaCapital(**dict(zip(column_names, row))) for row in rows]
    except Exception as e:
        logger.error(f"Erro ao buscar maiores empresas para query='{cleaned_query}': {e}", exc_info=True)
        raise RuntimeError(f"Falha na busca por capital: {e}") from e
    finally:
        cursor.close()

@cached(cache=name_cache)
def search_company_by_name(
    name: str,
    uf: Optional[str] = None,
    municipio: Optional[str] = None,
    limit: int = 15,
    offset: int = 0,
) -> List[EmpresaResumo]:
    """
    Busca empresas diretamente pela Razão Social ou Nome Fantasia.
    """
    cleaned_name = name.strip()
    if not cleaned_name or len(cleaned_name) < 3:
        return []

    safe_limit = max(1, min(limit, settings.MAX_SEARCH_LIMIT))
    safe_offset = max(0, offset)
    cleaned_uf = uf.strip().upper() if uf and uf.strip() else None
    cleaned_municipio = municipio.strip() if municipio and municipio.strip() else None

    conn = db_manager.get_connection()
    table_name, _ = _get_active_table_and_fts_func(conn)

    sql = f"""
        SELECT 
            cnpj,
            razao_social,
            nome_fantasia,
            municipio,
            uf,
            COALESCE(idade_anos, 0.0) as idade_anos,
            descricao_cnae_principal,
            0.0 as fts_score
        FROM {table_name}
        WHERE 
            (razao_social ILIKE ? OR nome_fantasia ILIKE ?)
            AND (? IS NULL OR UPPER(uf) = UPPER(?))
            AND (? IS NULL OR LOWER(municipio) = LOWER(?))
        ORDER BY idade_anos DESC
        LIMIT ? OFFSET ?;
    """

    search_pattern = f"%{cleaned_name}%"
    params = [
        search_pattern,
        search_pattern,
        cleaned_uf,
        cleaned_uf,
        cleaned_municipio,
        cleaned_municipio,
        safe_limit,
        safe_offset,
    ]

    cursor = conn.cursor()
    try:
        cursor.execute(sql, params)
        column_names = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        return [EmpresaResumo(**dict(zip(column_names, row))) for row in rows]
    except Exception as e:
        logger.error(f"Erro na busca nominal por '{cleaned_name}': {e}", exc_info=True)
        raise RuntimeError(f"Falha na busca nominal: {e}") from e
    finally:
        cursor.close()


"""
Script para unificar os arquivos Parquet da RMC, RMRJ e RMSP em um banco DuckDB consolidado
com índice Full-Text Search (FTS BM25) para busca rápida de empresas.
"""

import logging
import os
import sys
import time
from pathlib import Path
import duckdb

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("unificar_bases")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

PARQUET_RMC = DATA_DIR / "empresas_ativas_rmc.parquet"
PARQUET_RMRJ = DATA_DIR / "empresas_ativas_rmrj.parquet"
PARQUET_RMSP = DATA_DIR / "empresas_ativas_rmsp.parquet"
OUTPUT_DB = DATA_DIR / "empresas_ativas.duckdb"
TABLE_NAME = "tb_empresas_ativas"


def unificar_e_indexar():
    if not PARQUET_RMC.exists():
        logger.error(f"Arquivo não encontrado: {PARQUET_RMC}")
        sys.exit(1)
    if not PARQUET_RMRJ.exists():
        logger.error(f"Arquivo não encontrado: {PARQUET_RMRJ}")
        sys.exit(1)
    if not PARQUET_RMSP.exists():
        logger.error(f"Arquivo não encontrado: {PARQUET_RMSP}")
        sys.exit(1)

    if OUTPUT_DB.exists():
        logger.info(f"Removendo banco anterior {OUTPUT_DB}...")
        OUTPUT_DB.unlink()

    logger.info(f"Criando novo banco DuckDB consolidado: {OUTPUT_DB}")
    start_total = time.perf_counter()

    conn = duckdb.connect(str(OUTPUT_DB))

    try:
        logger.info("Carregando extensão FTS...")
        conn.execute("INSTALL fts; LOAD fts;")

        logger.info("Importando e unificando datasets Parquet (RMC + RMRJ + RMSP)...")
        t0 = time.perf_counter()
        
        # Cria a tabela consolidada unificando os três parquets
        conn.execute(f"""
            CREATE TABLE {TABLE_NAME} AS
            SELECT * FROM read_parquet('{PARQUET_RMC}')
            UNION ALL
            SELECT * FROM read_parquet('{PARQUET_RMRJ}')
            UNION ALL
            SELECT * FROM read_parquet('{PARQUET_RMSP}');
        """)
        
        # Cria VIEWs para retrocompatibilidade por região
        conn.execute(f"""
            CREATE VIEW tb_empresas_ativas_rmc AS
            SELECT * FROM {TABLE_NAME} WHERE uf = 'PR';
        """)
        conn.execute(f"""
            CREATE VIEW tb_empresas_ativas_rmrj AS
            SELECT * FROM {TABLE_NAME} WHERE uf = 'RJ';
        """)
        conn.execute(f"""
            CREATE VIEW tb_empresas_ativas_rmsp AS
            SELECT * FROM {TABLE_NAME} WHERE uf = 'SP';
        """)

        t_import = time.perf_counter() - t0
        logger.info(f"Dados importados com sucesso em {t_import:.2f}s!")

        # Estatísticas por UF
        stats = conn.execute(f"""
            SELECT uf, COUNT(*) AS total
            FROM {TABLE_NAME}
            GROUP BY uf
            ORDER BY total DESC;
        """).fetchall()

        logger.info("Distribuição de empresas ativas por UF:")
        total_geral = 0
        for uf, count in stats:
            logger.info(f"  -> UF: {uf} = {count:,} empresas")
            total_geral += count
        logger.info(f"Total consolidado: {total_geral:,} empresas ativas.")

        # Criando o índice FTS BM25 na tabela unificada
        logger.info("Criando índice FTS BM25 na coluna 'descricao_cnae_principal'...")
        t_idx_start = time.perf_counter()
        conn.execute(f"""
            PRAGMA create_fts_index(
                '{TABLE_NAME}',
                'cnpj',
                'descricao_cnae_principal',
                stemmer = 'portuguese',
                strip_accents = 1
            );
        """)
        t_idx = time.perf_counter() - t_idx_start
        logger.info(f"Índice FTS criado em {t_idx:.2f}s!")

        # Teste de validação 1: Busca no RJ
        logger.info("Testando busca FTS no Rio de Janeiro ('energia solar')...")
        res_rj = conn.execute(f"""
            SELECT cnpj, razao_social, municipio, uf, score
            FROM (
                SELECT cnpj, razao_social, municipio, uf,
                       fts_main_{TABLE_NAME}.match_bm25(cnpj, 'energia solar') AS score
                FROM {TABLE_NAME}
            ) sq
            WHERE score IS NOT NULL AND uf = 'RJ'
            ORDER BY score DESC
            LIMIT 2;
        """).fetchall()
        for r in res_rj:
            logger.info(f"  [RJ Match] {r[1]} - {r[2]}/{r[3]} (Score: {r[4]:.4f})")

        # Teste de validação 2: Busca no PR
        logger.info("Testando busca FTS no Paraná ('energia solar')...")
        res_pr = conn.execute(f"""
            SELECT cnpj, razao_social, municipio, uf, score
            FROM (
                SELECT cnpj, razao_social, municipio, uf,
                       fts_main_{TABLE_NAME}.match_bm25(cnpj, 'energia solar') AS score
                FROM {TABLE_NAME}
            ) sq
            WHERE score IS NOT NULL AND uf = 'PR'
            ORDER BY score DESC
            LIMIT 2;
        """).fetchall()
        for r in res_pr:
            logger.info(f"  [PR Match] {r[1]} - {r[2]}/{r[3]} (Score: {r[4]:.4f})")

        # Teste de validação 3: Busca em SP
        logger.info("Testando busca FTS em São Paulo ('energia solar')...")
        res_sp = conn.execute(f"""
            SELECT cnpj, razao_social, municipio, uf, score
            FROM (
                SELECT cnpj, razao_social, municipio, uf,
                       fts_main_{TABLE_NAME}.match_bm25(cnpj, 'energia solar') AS score
                FROM {TABLE_NAME}
            ) sq
            WHERE score IS NOT NULL AND uf = 'SP'
            ORDER BY score DESC
            LIMIT 2;
        """).fetchall()
        for r in res_sp:
            logger.info(f"  [SP Match] {r[1]} - {r[2]}/{r[3]} (Score: {r[4]:.4f})")

        db_size_mb = os.path.getsize(OUTPUT_DB) / (1024 * 1024)
        total_time = time.perf_counter() - start_total
        logger.info(f"Processo concluído com sucesso! Tamanho do banco final: {db_size_mb:.2f} MB em {total_time:.2f}s.")

    except Exception as e:
        logger.error(f"Erro na unificação: {e}", exc_info=True)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    unificar_e_indexar()

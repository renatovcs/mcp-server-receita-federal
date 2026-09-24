"""
Script de indexação Full-Text Search (FTS) para a base DuckDB da Receita Federal.
Cria índice BM25 na coluna `descricao_cnae_principal` com suporte a stemmer em português
e remoção automática de acentos (strip_accents).
"""

import argparse
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
logger = logging.getLogger("create_fts_index")


def build_fts_index(db_path: Path, rebuild: bool = False):
    if not db_path.exists():
        logger.error(f"Arquivo de banco de dados não encontrado: {db_path}")
        sys.exit(1)

    logger.info(f"Conectando ao banco de dados: {db_path}")
    start_time = time.perf_counter()

    conn = duckdb.connect(str(db_path), read_only=False)

    try:
        logger.info("Carregando extensão FTS...")
        conn.execute("INSTALL fts; LOAD fts;")

        table_name = "tb_empresas_ativas_rmc"
        pk_column = "cnpj"
        index_column = "descricao_cnae_principal"

        total_rows = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        logger.info(f"Tabela alvo: '{table_name}' com {total_rows:,} registros.")

        if rebuild:
            logger.info("Flag --rebuild detectada. Removendo índice FTS pré-existente (se houver)...")
            try:
                conn.execute(f"PRAGMA drop_fts_index('{table_name}');")
                logger.info("Índice anterior removido com sucesso.")
            except Exception as e:
                logger.warning(f"Aviso ao tentar remover índice anterior (pode não existir): {e}")

        logger.info(
            f"Criando índice FTS BM25 na coluna '{index_column}' (stemmer='portuguese', strip_accents=1)..."
        )
        idx_start = time.perf_counter()
        conn.execute(f"""
            PRAGMA create_fts_index(
                '{table_name}',
                '{pk_column}',
                '{index_column}',
                stemmer = 'portuguese',
                strip_accents = 1
            );
        """)
        idx_duration = time.perf_counter() - idx_start
        logger.info(f"Índice FTS criado com sucesso em {idx_duration:.2f} segundos!")

        # Validação do Índice com busca de teste
        test_query = "ar condicionado"
        logger.info(f"Executando query de validação BM25 para '{test_query}'...")
        val_start = time.perf_counter()
        test_results = conn.execute(f"""
            SELECT cnpj, razao_social, municipio, descricao_cnae_principal, score
            FROM (
                SELECT cnpj, razao_social, municipio, descricao_cnae_principal,
                       fts_main_{table_name}.match_bm25(cnpj, ?) AS score
                FROM {table_name}
            ) sq
            WHERE score IS NOT NULL
            ORDER BY score DESC
            LIMIT 3;
        """, [test_query]).fetchall()
        val_duration = (time.perf_counter() - val_start) * 1000

        logger.info(f"Query de validação concluída em {val_duration:.2f} ms:")
        for r in test_results:
            logger.info(f"  -> [{r[0]}] {r[1]} ({r[2]}) - Score: {r[4]:.4f} - CNAE: {r[3]}")

        file_size_mb = os.path.getsize(db_path) / (1024 * 1024)
        total_duration = time.perf_counter() - start_time
        logger.info(f"Processo finalizado com sucesso! Tamanho final do arquivo: {file_size_mb:.2f} MB (Total: {total_duration:.2f}s)")

    except Exception as e:
        logger.error(f"Erro durante a criação do índice FTS: {e}", exc_info=True)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cria índice Full-Text Search no DuckDB da Receita.")
    default_db = Path(__file__).resolve().parent.parent / "data" / "rmc_empresas.duckdb"
    parser.add_argument("--db-path", type=Path, default=default_db, help="Caminho do arquivo DuckDB")
    parser.add_argument("--rebuild", action="store_true", help="Força a reconstrução do índice caso já exista")

    args = parser.parse_args()
    build_fts_index(args.db_path, rebuild=args.rebuild)

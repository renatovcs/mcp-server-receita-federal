"""
Gerenciamento de conexão Singleton com DuckDB.
Garante conexão global única, modo estritamente read_only=True e ciclo de vida controlado via lifespan.
"""

from pathlib import Path
from typing import Optional
import duckdb
import structlog

from src.config import settings

logger = structlog.get_logger("anotae_mcp.database")


class DuckDBManager:
    """
    Singleton para conexão com DuckDB.
    Evita overhead de abrir e fechar conexões a cada requisição HTTP/SSE.
    """
    _instance: Optional["DuckDBManager"] = None
    _connection: Optional[duckdb.DuckDBPyConnection] = None
    _db_path: Optional[Path] = None
    _total_empresas: int = 0

    def __new__(cls) -> "DuckDBManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def initialize(self, db_path: Path) -> None:
        """
        Inicializa a conexão DuckDB em modo read_only=True durante o lifespan do ASGI.
        """
        if self._connection is not None:
            logger.info("Conexão DuckDB já inicializada.")
            return

        if not db_path.exists():
            raise FileNotFoundError(
                f"Arquivo de banco de dados DuckDB não encontrado no caminho: {db_path}"
            )

        self._db_path = db_path
        logger.info(f"Abrindo conexão DuckDB Singleton (read_only=True): {db_path}")

        try:
            self._connection = duckdb.connect(database=str(db_path), read_only=True)
            
            # Configuração defensiva de limites de recursos para garantir estabilidade e evitar OOM
            try:
                self._connection.execute(f"SET memory_limit = '{settings.DUCKDB_MEMORY_LIMIT}';")
                self._connection.execute(f"SET threads = {settings.DUCKDB_THREADS};")
                logger.info(
                    f"Limites operacionais DuckDB configurados: memory_limit={settings.DUCKDB_MEMORY_LIMIT}, threads={settings.DUCKDB_THREADS}"
                )
            except Exception as e:
                logger.warning(f"Aviso ao aplicar pragmas de recursos DuckDB: {e}")

            # Carrega extensão FTS para habilitar consultas BM25 indexadas
            try:
                self._connection.execute("LOAD fts;")
            except Exception:
                self._connection.execute("INSTALL fts; LOAD fts;")
            
            # Obtém contagem total para métricas do healthcheck
            try:
                res = self._connection.execute(
                    "SELECT COUNT(*) FROM tb_empresas_ativas"
                ).fetchone()
            except Exception:
                res = self._connection.execute(
                    "SELECT COUNT(*) FROM tb_empresas_ativas_rmc"
                ).fetchone()
            self._total_empresas = res[0] if res else 0

            logger.info(
                f"DuckDB inicializado com sucesso! Total de empresas ativas: {self._total_empresas:,}"
            )
        except Exception as e:
            logger.critical(f"Falha ao conectar ao banco DuckDB: {e}", exc_info=True)
            if self._connection:
                try:
                    self._connection.close()
                except Exception:
                    pass
            self._connection = None
            raise

    def get_connection(self) -> duckdb.DuckDBPyConnection:
        """
        Retorna a conexão ativa Singleton.
        """
        if self._connection is None:
            raise RuntimeError(
                "Conexão DuckDB não foi inicializada. Certifique-se de que o lifespan do ASGI foi executado."
            )
        return self._connection

    @property
    def total_empresas(self) -> int:
        return self._total_empresas

    @property
    def memory_limit(self) -> str:
        return settings.DUCKDB_MEMORY_LIMIT

    @property
    def threads(self) -> int:
        return settings.DUCKDB_THREADS

    @property
    def is_connected(self) -> bool:
        return self._connection is not None

    def close(self) -> None:
        """
        Fecha a conexão de forma segura no shutdown da aplicação.
        """
        if self._connection is not None:
            logger.info("Fechando conexão Singleton DuckDB...")
            try:
                self._connection.close()
            except Exception as e:
                logger.error(f"Erro ao fechar conexão DuckDB: {e}")
            finally:
                self._connection = None
                logger.info("Conexão DuckDB finalizada.")


db_manager = DuckDBManager()

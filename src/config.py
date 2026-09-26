"""
Módulo de configuração do microsserviço anotae-mcp-receita.
Lê variáveis de ambiente com fallbacks defensivos e tipagem estrita.
"""

import os
from pathlib import Path
from pydantic import BaseModel, Field


class Settings(BaseModel):
    SERVICE_NAME: str = "anotae-mcp-receita"
    SERVICE_VERSION: str = "0.2.0"
    HOST: str = Field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    PORT: int = Field(default_factory=lambda: int(os.getenv("PORT", "8005")))
    API_KEY: str = Field(default_factory=lambda: os.getenv("API_KEY", "anotae-receita-dev-key-123"))
    
    # Caminho do banco DuckDB
    DUCKDB_PATH: Path = Field(
        default_factory=lambda: Path(
            os.getenv(
                "DUCKDB_PATH",
                str(Path(__file__).resolve().parent.parent / "data" / "empresas_ativas.duckdb")
            )
        )
    )

    # Parâmetros de busca
    DEFAULT_SEARCH_LIMIT: int = 15
    MAX_SEARCH_LIMIT: int = 100

    # Limites operacionais de recursos para DuckDB (proteção de OOM e concorrência)
    DUCKDB_MEMORY_LIMIT: str = Field(default_factory=lambda: os.getenv("DUCKDB_MEMORY_LIMIT", "2GB"))
    DUCKDB_THREADS: int = Field(default_factory=lambda: int(os.getenv("DUCKDB_THREADS", "2")))


settings = Settings()

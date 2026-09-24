"""
Script de Extração e Carga de Dados da Região Metropolitana de Curitiba (RMC).
Utiliza DuckDB para processamento analítico de alta performance.
"""

from pathlib import Path
import duckdb

# -----------------------------------------------------------------------------
# 1. Configuração de Caminhos e Diretórios
# -----------------------------------------------------------------------------
# Se executado a partir de src/, sobe um nível para encontrar a raiz do projeto
CURRENT_DIR = Path(__file__).resolve().parent
BASE_DIR = CURRENT_DIR.parent if CURRENT_DIR.name == "src" else CURRENT_DIR

DATA_RAW_DIR = BASE_DIR / "data" / "raw"
DATA_PROCESSED_DIR = BASE_DIR / "data" / "processed"

# Garante a existência das pastas
DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_RAW_DIR / "rmc_database.duckdb"
PARQUET_OUTPUT = DATA_RAW_DIR / "municipios_rmc.parquet"
CSV_OUTPUT = DATA_RAW_DIR / "municipios_rmc.csv"

# -----------------------------------------------------------------------------
# 2. Lista Oficial dos 29 Municípios da RMC (Região Metropolitana de Curitiba)
# Fonte oficial: Legislação Estadual / COMEC / AMEP / IBGE
# -----------------------------------------------------------------------------
MUNICIPIOS_RMC = [
    {"id": 1, "municipio": "Adrianópolis", "uf": "PR", "regiao_metropolitana": "Curitiba"},
    {"id": 2, "municipio": "Agudos do Sul", "uf": "PR", "regiao_metropolitana": "Curitiba"},
    {"id": 3, "municipio": "Almirante Tamandaré", "uf": "PR", "regiao_metropolitana": "Curitiba"},
    {"id": 4, "municipio": "Araucária", "uf": "PR", "regiao_metropolitana": "Curitiba"},
    {"id": 5, "municipio": "Balsa Nova", "uf": "PR", "regiao_metropolitana": "Curitiba"},
    {"id": 6, "municipio": "Bocaiúva do Sul", "uf": "PR", "regiao_metropolitana": "Curitiba"},
    {"id": 7, "municipio": "Campina Grande do Sul", "uf": "PR", "regiao_metropolitana": "Curitiba"},
    {"id": 8, "municipio": "Campo do Tenente", "uf": "PR", "regiao_metropolitana": "Curitiba"},
    {"id": 9, "municipio": "Campo Largo", "uf": "PR", "regiao_metropolitana": "Curitiba"},
    {"id": 10, "municipio": "Campo Magro", "uf": "PR", "regiao_metropolitana": "Curitiba"},
    {"id": 11, "municipio": "Cerro Azul", "uf": "PR", "regiao_metropolitana": "Curitiba"},
    {"id": 12, "municipio": "Colombo", "uf": "PR", "regiao_metropolitana": "Curitiba"},
    {"id": 13, "municipio": "Contenda", "uf": "PR", "regiao_metropolitana": "Curitiba"},
    {"id": 14, "municipio": "Curitiba", "uf": "PR", "regiao_metropolitana": "Curitiba"},
    {"id": 15, "municipio": "Doutor Ulysses", "uf": "PR", "regiao_metropolitana": "Curitiba"},
    {"id": 16, "municipio": "Fazenda Rio Grande", "uf": "PR", "regiao_metropolitana": "Curitiba"},
    {"id": 17, "municipio": "Itaperuçu", "uf": "PR", "regiao_metropolitana": "Curitiba"},
    {"id": 18, "municipio": "Lapa", "uf": "PR", "regiao_metropolitana": "Curitiba"},
    {"id": 19, "municipio": "Mandirituba", "uf": "PR", "regiao_metropolitana": "Curitiba"},
    {"id": 20, "municipio": "Piên", "uf": "PR", "regiao_metropolitana": "Curitiba"},
    {"id": 21, "municipio": "Pinhais", "uf": "PR", "regiao_metropolitana": "Curitiba"},
    {"id": 22, "municipio": "Piraquara", "uf": "PR", "regiao_metropolitana": "Curitiba"},
    {"id": 23, "municipio": "Quatro Barras", "uf": "PR", "regiao_metropolitana": "Curitiba"},
    {"id": 24, "municipio": "Quitandinha", "uf": "PR", "regiao_metropolitana": "Curitiba"},
    {"id": 25, "municipio": "Rio Branco do Sul", "uf": "PR", "regiao_metropolitana": "Curitiba"},
    {"id": 26, "municipio": "Rio Negro", "uf": "PR", "regiao_metropolitana": "Curitiba"},
    {"id": 27, "municipio": "São José dos Pinhais", "uf": "PR", "regiao_metropolitana": "Curitiba"},
    {"id": 28, "municipio": "Tijucas do Sul", "uf": "PR", "regiao_metropolitana": "Curitiba"},
    {"id": 29, "municipio": "Tunas do Paraná", "uf": "PR", "regiao_metropolitana": "Curitiba"},
]


def extrair_e_carregar_rmc(persistir_banco: bool = True):
    """
    Carrega a lista de municípios da RMC no DuckDB e exporta para Parquet e CSV.
    """
    print("=" * 60)
    print(" Iniciando extração e carga da RMC no DuckDB")
    print("=" * 60)

    # Conecta ao arquivo DuckDB persistente ou em memória
    db_target = str(DB_PATH) if persistir_banco else ":memory:"
    conn = duckdb.connect(db_target)

    # 1. Cria a estrutura da tabela
    conn.execute("""
        CREATE OR REPLACE TABLE dim_municipios_rmc (
            id INTEGER PRIMARY KEY,
            municipio VARCHAR NOT NULL,
            uf VARCHAR(2) NOT NULL,
            regiao_metropolitana VARCHAR NOT NULL,
            data_extracao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 2. Insere os 29 municípios da RMC
    dados_insercao = [
        (m["id"], m["municipio"], m["uf"], m["regiao_metropolitana"])
        for m in MUNICIPIOS_RMC
    ]
    conn.executemany("""
        INSERT INTO dim_municipios_rmc (id, municipio, uf, regiao_metropolitana)
        VALUES (?, ?, ?, ?)
    """, dados_insercao)

    # 3. Exibe total e amostra dos dados
    total = conn.execute("SELECT COUNT(*) FROM dim_municipios_rmc").fetchone()[0]
    print(f"\n[OK] Total de municípios carregados no DuckDB: {total}")

    print("\n--- Amostra dos Municípios Cadastrados (Primeiros 10) ---")
    resultado = conn.execute("""
        SELECT id, municipio, uf, regiao_metropolitana 
        FROM dim_municipios_rmc 
        ORDER BY municipio ASC 
        LIMIT 10
    """).fetchall()

    for linha in resultado:
        print(f"[{linha[0]:02d}] {linha[1]} ({linha[2]})")

    # 4. Exporta para formato Parquet e CSV
    conn.execute(f"COPY dim_municipios_rmc TO '{PARQUET_OUTPUT.as_posix()}' (FORMAT PARQUET)")
    conn.execute(f"COPY dim_municipios_rmc TO '{CSV_OUTPUT.as_posix()}' (HEADER, DELIMITER ';')")

    print(f"\n[OK] Arquivo Parquet exportado: {PARQUET_OUTPUT}")
    print(f"[OK] Arquivo CSV exportado:     {CSV_OUTPUT}")
    if persistir_banco:
        print(f"[OK] Banco DuckDB salvo em:     {DB_PATH}")

    # 5. Consulta demonstrativa com DuckDB SQL
    print("\n--- Consulta Demonstrativa com DuckDB SQL (Filtros e Contagem) ---")
    filtro = conn.execute("""
        SELECT municipio 
        FROM dim_municipios_rmc 
        WHERE municipio ILIKE 'Campo%' OR municipio ILIKE '%Sul%'
        ORDER BY municipio
    """).fetchall()
    
    for item in filtro:
        print(f" -> {item[0]}")

    conn.close()
    print("\nProcessamento concluído com sucesso!")


if __name__ == "__main__":
    extrair_e_carregar_rmc(persistir_banco=True)

"""
Pipeline de Extração, Filtro e Enriquecimento das Empresas Ativas da RMC.
Lê os arquivos brutos da Receita Federal com DuckDB e gera:
1. Tabela física persistente 'tb_empresas_ativas_rmc' no DuckDB (receita/processed/rmc_empresas.duckdb)
2. Arquivo analítico de alta performance (receita/processed/empresas_ativas_rmc.parquet)
"""

import time
from pathlib import Path
import duckdb

# -----------------------------------------------------------------------------
# 1. Configuração de Diretórios e Arquivos
# -----------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_RAW_DIR = BASE_DIR / "receita" / "raw"
DATA_PROCESSED_DIR = BASE_DIR / "receita" / "processed"
DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_PROCESSED_DIR / "rmc_empresas.duckdb"
OUTPUT_PARQUET = DATA_PROCESSED_DIR / "empresas_ativas_rmc.parquet"

# Mapeamento Oficial dos 29 Municípios da RMC (TOM -> Nome com acentuação oficial)
TOM_RMC_MAP = {
    "7403": "Adrianópolis",
    "7405": "Agudos do Sul",
    "7407": "Almirante Tamandaré",
    "7435": "Araucária",
    "7443": "Balsa Nova",
    "7459": "Bocaiúva do Sul",
    "7477": "Campina Grande do Sul",
    "7479": "Campo do Tenente",
    "7481": "Campo Largo",
    "0842": "Campo Magro",
    "7501": "Cerro Azul",
    "7513": "Colombo",
    "7521": "Contenda",
    "7535": "Curitiba",
    "5449": "Doutor Ulysses",
    "9983": "Fazenda Rio Grande",
    "5451": "Itaperuçu",
    "7657": "Lapa",
    "7679": "Mandirituba",
    "7761": "Piên",
    "5453": "Pinhais",
    "7769": "Piraquara",
    "7795": "Quatro Barras",
    "7801": "Quitandinha",
    "7821": "Rio Branco do Sul",
    "7823": "Rio Negro",
    "7885": "São José dos Pinhais",
    "7925": "Tijucas do Sul",
    "5455": "Tunas do Paraná"
}

ESTAB_COL_NAMES = [
    'cnpj_basico', 'cnpj_ordem', 'cnpj_dv', 'matriz_filial', 'nome_fantasia',
    'situacao_cadastral', 'data_situacao_cadastral', 'motivo_situacao_cadastral',
    'nome_cidade_exterior', 'pais', 'data_inicio_atividade', 'cnae_fiscal_principal',
    'cnae_fiscal_secundaria', 'tipo_logradouro', 'logradouro', 'numero',
    'complemento', 'bairro', 'cep', 'uf', 'municipio',
    'ddd_1', 'telefone_1', 'ddd_2', 'telefone_2', 'ddd_fax', 'fax',
    'correio_eletronico', 'situacao_especial', 'data_situacao_especial'
]

EMPRE_COL_NAMES = [
    'cnpj_basico', 'razao_social', 'codigo_natureza_juridica',
    'qualificacao_responsavel', 'capital_social', 'porte_empresa',
    'ente_federativo_responsavel'
]

def executar_pipeline():
    inicio_total = time.time()
    print("=" * 75)
    print(" PIPELINE DE PROCESSAMENTO DAS EMPRESAS ATIVAS DA RMC (RECEITA FEDERAL)")
    print("=" * 75)

    # Coleta os arquivos brutos
    estab_files = sorted([f.as_posix() for f in DATA_RAW_DIR.glob("*ESTABELE*")])
    emp_files = sorted([f.as_posix() for f in DATA_RAW_DIR.glob("*EMPRECSV*")])
    cnae_files = sorted([f.as_posix() for f in DATA_RAW_DIR.glob("*CNAE*")])
    natju_files = sorted([f.as_posix() for f in DATA_RAW_DIR.glob("*NATJU*")])

    print(f"-> Arquivos de Estabelecimentos localizados: {len(estab_files)}")
    print(f"-> Arquivos de Empresas localizados:         {len(emp_files)}")
    print(f"-> Arquivo de CNAE:                         {len(cnae_files)}")
    print(f"-> Arquivo de Natureza Jurídica:            {len(natju_files)}")

    if not estab_files or not emp_files or not cnae_files or not natju_files:
        raise FileNotFoundError("Arquivos necessários da Receita Federal não foram encontrados em data/raw/")

    # Conecta ao DuckDB
    conn = duckdb.connect(str(DB_PATH))
    conn.execute("SET preserve_insertion_order = false")
    temp_dir = (DATA_RAW_DIR / "duckdb_temp").as_posix()
    conn.execute(f"PRAGMA temp_directory='{temp_dir}'")

    # -------------------------------------------------------------------------
    # Passo 1: Carregar Dimensões Auxiliares (Municípios RMC, CNAE, NATJU)
    # -------------------------------------------------------------------------
    print("\n[1/5] Carregando tabelas dimensionais (Municípios RMC, CNAE e Nat. Jurídica)...")
    
    # Dimensão Municípios RMC
    tom_tuples = list(TOM_RMC_MAP.items())
    conn.execute("CREATE OR REPLACE TEMP TABLE dim_municipios_rmc (cod_tom VARCHAR, municipio VARCHAR)")
    conn.executemany("INSERT INTO dim_municipios_rmc VALUES (?, ?)", tom_tuples)

    # Dimensão CNAE
    conn.execute(f"""
        CREATE OR REPLACE TEMP TABLE dim_cnae AS
        SELECT 
            cod_cnae,
            TRIM(descricao_cnae) AS descricao_cnae
        FROM read_csv(
            '{cnae_files[0]}',
            delim=';',
            header=false,
            all_varchar=true,
            encoding='iso-8859_1-1998',
            ignore_errors=true,
            names=['cod_cnae', 'descricao_cnae']
        )
    """)

    # Dimensão Natureza Jurídica
    conn.execute(f"""
        CREATE OR REPLACE TEMP TABLE dim_natju AS
        SELECT 
            codigo_natureza_juridica,
            TRIM(natureza_juridica) AS natureza_juridica
        FROM read_csv(
            '{natju_files[0]}',
            delim=';',
            header=false,
            all_varchar=true,
            encoding='iso-8859_1-1998',
            ignore_errors=true,
            names=['codigo_natureza_juridica', 'natureza_juridica']
        )
    """)

    # -------------------------------------------------------------------------
    # Passo 2: Extrair Estabelecimentos ATIVOS da RMC (Iterando arquivos com progresso)
    # -------------------------------------------------------------------------
    print("\n[2/5] Filtrando estabelecimentos ATIVOS da RMC nos arquivos ESTABELE...")
    conn.execute("""
        CREATE OR REPLACE TEMP TABLE temp_estab_rmc (
            cnpj_basico VARCHAR,
            cnpj_ordem VARCHAR,
            cnpj_dv VARCHAR,
            matriz_filial VARCHAR,
            nome_fantasia VARCHAR,
            situacao_cadastral VARCHAR,
            data_inicio_atividade DATE,
            cnae_fiscal_principal VARCHAR,
            cnae_fiscal_secundaria VARCHAR,
            tipo_logradouro VARCHAR,
            logradouro VARCHAR,
            numero VARCHAR,
            complemento VARCHAR,
            bairro VARCHAR,
            cep VARCHAR,
            uf VARCHAR,
            cod_municipio_tom VARCHAR,
            ddd_1 VARCHAR,
            telefone_1 VARCHAR,
            ddd_2 VARCHAR,
            telefone_2 VARCHAR,
            email VARCHAR
        )
    """)

    t_estab_start = time.time()
    for idx, f in enumerate(estab_files, 1):
        t0 = time.time()
        file_name = Path(f).name
        conn.execute(f"""
            INSERT INTO temp_estab_rmc
            SELECT
                cnpj_basico,
                cnpj_ordem,
                cnpj_dv,
                CASE matriz_filial 
                    WHEN '1' THEN 'Matriz' 
                    WHEN '2' THEN 'Filial' 
                    ELSE matriz_filial 
                END AS matriz_filial,
                NULLIF(TRIM(nome_fantasia), '') AS nome_fantasia,
                situacao_cadastral,
                TRY_STRPTIME(data_inicio_atividade, '%Y%m%d')::DATE AS data_inicio_atividade,
                cnae_fiscal_principal,
                NULLIF(TRIM(cnae_fiscal_secundaria), '') AS cnae_fiscal_secundaria,
                NULLIF(TRIM(tipo_logradouro), '') AS tipo_logradouro,
                NULLIF(TRIM(logradouro), '') AS logradouro,
                NULLIF(TRIM(numero), '') AS numero,
                NULLIF(TRIM(complemento), '') AS complemento,
                NULLIF(TRIM(bairro), '') AS bairro,
                NULLIF(TRIM(cep), '') AS cep,
                uf,
                municipio AS cod_municipio_tom,
                NULLIF(TRIM(ddd_1), '') AS ddd_1,
                NULLIF(TRIM(telefone_1), '') AS telefone_1,
                NULLIF(TRIM(ddd_2), '') AS ddd_2,
                NULLIF(TRIM(telefone_2), '') AS telefone_2,
                LOWER(NULLIF(TRIM(correio_eletronico), '')) AS email
            FROM read_csv(
                '{f}',
                delim=';',
                header=false,
                all_varchar=true,
                encoding='iso-8859_1-1998',
                ignore_errors=true,
                names={ESTAB_COL_NAMES}
            )
            WHERE uf = 'PR' 
              AND situacao_cadastral = '02' 
              AND municipio IN (SELECT cod_tom FROM dim_municipios_rmc)
        """)
        parcial = conn.execute("SELECT COUNT(*) FROM temp_estab_rmc").fetchone()[0]
        print(f"      [{idx:02d}/{len(estab_files):02d}] {file_name} -> total acumulado: {parcial:,} estabelecimentos ({time.time() - t0:.1f}s)")

    total_estabs = conn.execute("SELECT COUNT(*) FROM temp_estab_rmc").fetchone()[0]
    print(f"   -> Concluído! {total_estabs:,} estabelecimentos ativos encontrados na RMC ({time.time() - t_estab_start:.1f}s)")

    # -------------------------------------------------------------------------
    # Passo 3: Extrair Dados de EMPRESAS para os CNPJs da RMC
    # -------------------------------------------------------------------------
    print("\n[3/5] Cruzando com os arquivos de EMPRESAS (Razão Social, Capital Social e Natureza Jurídica)...")
    conn.execute("""
        CREATE OR REPLACE TEMP TABLE temp_emp_rmc (
            cnpj_basico VARCHAR,
            razao_social VARCHAR,
            codigo_natureza_juridica VARCHAR,
            capital_social DOUBLE,
            porte_empresa VARCHAR
        )
    """)

    t_emp_start = time.time()
    for idx, f in enumerate(emp_files, 1):
        t0 = time.time()
        file_name = Path(f).name
        conn.execute(f"""
            INSERT INTO temp_emp_rmc
            SELECT
                e.cnpj_basico,
                TRIM(e.razao_social) AS razao_social,
                e.codigo_natureza_juridica,
                TRY_CAST(REPLACE(e.capital_social, ',', '.') AS DOUBLE) AS capital_social,
                CASE e.porte_empresa
                    WHEN '01' THEN 'Não Informado'
                    WHEN '02' THEN 'Microempresa (ME)'
                    WHEN '03' THEN 'Empresa de Pequeno Porte (EPP)'
                    WHEN '05' THEN 'Demais'
                    ELSE e.porte_empresa
                END AS porte_empresa
            FROM read_csv(
                '{f}',
                delim=';',
                header=false,
                all_varchar=true,
                encoding='iso-8859_1-1998',
                ignore_errors=true,
                names={EMPRE_COL_NAMES}
            ) e
            SEMI JOIN temp_estab_rmc s ON e.cnpj_basico = s.cnpj_basico
        """)
        parcial = conn.execute("SELECT COUNT(*) FROM temp_emp_rmc").fetchone()[0]
        print(f"      [{idx:02d}/{len(emp_files):02d}] {file_name} -> total acumulado: {parcial:,} empresas ({time.time() - t0:.1f}s)")

    total_emps = conn.execute("SELECT COUNT(*) FROM temp_emp_rmc").fetchone()[0]
    print(f"   -> Concluído! {total_emps:,} empresas únicas associadas na RMC ({time.time() - t_emp_start:.1f}s)")

    # -------------------------------------------------------------------------
    # Passo 4: Criar Tabela Física Consolidada no DuckDB
    # -------------------------------------------------------------------------
    print("\n[4/5] Gerando tabela final consolidada 'tb_empresas_ativas_rmc' no DuckDB...")
    t0 = time.time()

    conn.execute("""
        CREATE OR REPLACE TABLE tb_empresas_ativas_rmc AS
        SELECT
            -- Identificação e CNPJ Completo Formatado
            SUBSTRING(e.cnpj_basico, 1, 2) || '.' || 
            SUBSTRING(e.cnpj_basico, 3, 3) || '.' || 
            SUBSTRING(e.cnpj_basico, 6, 3) || '/' || 
            e.cnpj_ordem || '-' || e.cnpj_dv AS cnpj,
            e.cnpj_basico,
            m.razao_social,
            e.nome_fantasia,
            e.matriz_filial,
            
            -- Porte e Capital Social
            m.porte_empresa,
            m.capital_social,

            -- Natureza Jurídica
            m.codigo_natureza_juridica,
            COALESCE(nj.natureza_juridica, 'Não Especificada') AS natureza_juridica,

            -- Idade e Data de Abertura
            e.data_inicio_atividade,
            CASE 
                WHEN e.data_inicio_atividade IS NOT NULL 
                THEN date_diff('year', e.data_inicio_atividade, CURRENT_DATE) 
                ELSE NULL 
            END AS idade_anos,

            -- Atividades Econômicas (CNAE)
            e.cnae_fiscal_principal,
            COALESCE(c.descricao_cnae, 'Descrição não encontrada') AS descricao_cnae_principal,
            e.cnae_fiscal_secundaria,

            -- Localização Detalhada (Colunas separadas para futura clusterização geográfica)
            e.tipo_logradouro,
            e.logradouro,
            e.numero,
            e.complemento,
            e.bairro,
            e.cep,
            mun.municipio,
            e.uf,
            
            -- Endereço Completo Formatado
            CONCAT_WS(', ',
                NULLIF(TRIM(CONCAT_WS(' ', e.tipo_logradouro, e.logradouro)), ''),
                NULLIF(e.numero, ''),
                NULLIF(e.complemento, ''),
                NULLIF(e.bairro, ''),
                mun.municipio || ' - ' || e.uf,
                CASE WHEN e.cep IS NOT NULL THEN 'CEP: ' || e.cep ELSE NULL END
            ) AS endereco_completo,

            -- Canais de Contato
            CASE 
                WHEN e.ddd_1 IS NOT NULL AND e.telefone_1 IS NOT NULL 
                THEN '(' || e.ddd_1 || ') ' || e.telefone_1 
                ELSE NULL 
            END AS telefone_1,
            CASE 
                WHEN e.ddd_2 IS NOT NULL AND e.telefone_2 IS NOT NULL 
                THEN '(' || e.ddd_2 || ') ' || e.telefone_2 
                ELSE NULL 
            END AS telefone_2,
            e.email,

            -- Metadados
            CURRENT_TIMESTAMP AS data_extracao
        FROM temp_estab_rmc e
        LEFT JOIN temp_emp_rmc m ON e.cnpj_basico = m.cnpj_basico
        LEFT JOIN dim_municipios_rmc mun ON e.cod_municipio_tom = mun.cod_tom
        LEFT JOIN dim_cnae c ON e.cnae_fiscal_principal = c.cod_cnae
        LEFT JOIN dim_natju nj ON m.codigo_natureza_juridica = nj.codigo_natureza_juridica
        ORDER BY mun.municipio, m.razao_social
    """)

    total_final = conn.execute("SELECT COUNT(*) FROM tb_empresas_ativas_rmc").fetchone()[0]
    print(f"      -> Tabela 'tb_empresas_ativas_rmc' criada com {total_final:,} registros ({time.time() - t0:.1f}s)")

    # -------------------------------------------------------------------------
    # Passo 5: Exportar para Parquet
    # -------------------------------------------------------------------------
    print("\n[5/5] Exportando para formato Parquet de alta compressão (data/processed/)...")
    t0 = time.time()
    conn.execute(f"""
        COPY tb_empresas_ativas_rmc TO '{OUTPUT_PARQUET.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    tamanho_mb = OUTPUT_PARQUET.stat().st_size / (1024 * 1024)
    print(f"      -> Arquivo Parquet gerado com sucesso: {tamanho_mb:.2f} MB ({time.time() - t0:.1f}s)")

    # Limpeza de tabelas temporárias
    conn.execute("DROP TABLE IF EXISTS temp_estab_rmc")
    conn.execute("DROP TABLE IF EXISTS temp_emp_rmc")
    conn.execute("DROP TABLE IF EXISTS dim_municipios_rmc")
    conn.execute("DROP TABLE IF EXISTS dim_cnae")
    conn.execute("DROP TABLE IF EXISTS dim_natju")

    tempo_total = time.time() - inicio_total
    print("\n" + "=" * 75)
    print(f" PIPELINE CONCLUÍDO COM SUCESSO EM {tempo_total / 60:.2f} MINUTOS!")
    print(f" -> Total de empresas ativas na RMC: {total_final:,}")
    print(f" -> Banco DuckDB: {DB_PATH}")
    print(f" -> Arquivo Parquet: {OUTPUT_PARQUET}")
    print("=" * 75)

    conn.close()

if __name__ == "__main__":
    executar_pipeline()

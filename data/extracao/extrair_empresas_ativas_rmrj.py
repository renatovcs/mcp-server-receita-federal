"""
Pipeline de Extração, Filtro e Enriquecimento das Empresas Ativas da RMRJ (Região Metropolitana do Rio de Janeiro).
Lê os arquivos brutos da Receita Federal com DuckDB e gera:
1. Tabela física persistente 'tb_empresas_ativas_rmrj' no DuckDB (receita/processed/rmrj_empresas.duckdb)
2. Arquivo analítico de alta performance (receita/processed/empresas_ativas_rmrj.parquet)
"""

import argparse
import sys
import time
from pathlib import Path
import duckdb

# -----------------------------------------------------------------------------
# 1. Configuração de Diretórios Padrão
# -----------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_RAW_DIR = BASE_DIR / "receita" / "raw"
DEFAULT_PROCESSED_DIR = BASE_DIR / "receita" / "processed"

# -----------------------------------------------------------------------------
# 2. Mapeamento Oficial dos 22 Municípios da RMRJ (TOM da Receita -> Nome Oficial)
# Fonte: Legislação Estadual RJ (Lei Complementar nº 184/2018) / Tabela TOM Receita Federal
# -----------------------------------------------------------------------------
TOM_RMRJ_MAP = {
    "6001": "Rio de Janeiro",
    "5865": "Niterói",
    "5897": "São Gonçalo",
    "5815": "Duque de Caxias",
    "5869": "Nova Iguaçu",
    "5923": "Belford Roxo",
    "5901": "São João de Meriti",
    "5849": "Magé",
    "5837": "Itaboraí",
    "5927": "Mesquita",
    "5863": "Nilópolis",
    "5851": "Maricá",
    "5925": "Queimados",
    "5839": "Itaguaí",
    "5929": "Japeri",
    "5931": "Seropédica",
    "5921": "Guapimirim",
    "5809": "Cachoeiras de Macacu",
    "5873": "Paracambi",
    "5933": "Tanguá",
    "5887": "Rio Bonito",
    "5877": "Petrópolis",
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


def executar_pipeline(data_raw_dir: Path, data_processed_dir: Path, build_fts: bool = False):
    inicio_total = time.time()
    data_processed_dir.mkdir(parents=True, exist_ok=True)

    db_path = data_processed_dir / "rmrj_empresas.duckdb"
    output_parquet = data_processed_dir / "empresas_ativas_rmrj.parquet"

    print("=" * 80)
    print(" PIPELINE DE PROCESSAMENTO DAS EMPRESAS ATIVAS DA RMRJ (RECEITA FEDERAL)")
    print(f" Origem dos dados brutos:    {data_raw_dir}")
    print(f" Destino DuckDB:             {db_path}")
    print(f" Destino Parquet:            {output_parquet}")
    print("=" * 80)

    # Coleta os arquivos brutos (aceita maiúsculas ou minúsculas)
    estab_files = sorted(
        [f.as_posix() for f in data_raw_dir.glob("*ESTABELE*")] +
        [f.as_posix() for f in data_raw_dir.glob("*estabele*")]
    )
    # Remove duplicidades se houver sistema de arquivos case-insensitive
    estab_files = sorted(list(set(estab_files)))

    emp_files = sorted(list(set(
        [f.as_posix() for f in data_raw_dir.glob("*EMPRECSV*")] +
        [f.as_posix() for f in data_raw_dir.glob("*empcsv*")] +
        [f.as_posix() for f in data_raw_dir.glob("*EMPRESAS*")]
    )))

    cnae_files = sorted(list(set(
        [f.as_posix() for f in data_raw_dir.glob("*CNAE*")] +
        [f.as_posix() for f in data_raw_dir.glob("*cnae*")]
    )))

    natju_files = sorted(list(set(
        [f.as_posix() for f in data_raw_dir.glob("*NATJU*")] +
        [f.as_posix() for f in data_raw_dir.glob("*natju*")]
    )))

    print(f"-> Arquivos de Estabelecimentos localizados: {len(estab_files)}")
    print(f"-> Arquivos de Empresas localizados:         {len(emp_files)}")
    print(f"-> Arquivo de CNAE localizado:              {len(cnae_files)}")
    print(f"-> Arquivo de Natureza Jurídica localizado: {len(natju_files)}")

    if len(estab_files) < 10:
        print(f"\n⚠️  ATENÇÃO: Foram encontrados apenas {len(estab_files)} arquivo(s) de Estabelecimentos!")
        print("   Lembre-se que a Receita Federal divide a base de todo o Brasil entre os arquivos 0 a 9.")
        print("   Para 100% de cobertura da RMRJ, garanta todos os 10 arquivos (0 a 9).\n")

    if not estab_files or not emp_files or not cnae_files:
        print("❌ Erro: Arquivos obrigatórios da Receita Federal não encontrados no diretório informado.")
        sys.exit(1)

    # Conecta ao DuckDB
    conn = duckdb.connect(str(db_path))
    conn.execute("SET preserve_insertion_order = false")
    temp_dir = (data_raw_dir / "duckdb_temp").as_posix()
    conn.execute(f"PRAGMA temp_directory='{temp_dir}'")

    # -------------------------------------------------------------------------
    # Passo 1: Carregar Dimensões Auxiliares (Municípios RMRJ, CNAE, NATJU)
    # -------------------------------------------------------------------------
    print("\n[1/5] Carregando tabelas dimensionais (Municípios RMRJ, CNAE e Nat. Jurídica)...")

    # Dimensão Municípios RMRJ
    tom_tuples = list(TOM_RMRJ_MAP.items())
    conn.execute("CREATE OR REPLACE TEMP TABLE dim_municipios_rmrj (cod_tom VARCHAR, municipio VARCHAR)")
    conn.executemany("INSERT INTO dim_municipios_rmrj VALUES (?, ?)", tom_tuples)

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

    # Dimensão Natureza Jurídica (opcional com fallback se não estiver presente)
    if natju_files:
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
    else:
        print("   ℹ️  Arquivo NATJU não encontrado. A coluna 'natureza_juridica' será preenchida como NULL.")
        conn.execute("""
            CREATE OR REPLACE TEMP TABLE dim_natju (
                codigo_natureza_juridica VARCHAR,
                natureza_juridica VARCHAR
            )
        """)

    # -------------------------------------------------------------------------
    # Passo 2: Extrair Estabelecimentos ATIVOS da RMRJ
    # -------------------------------------------------------------------------
    print("\n[2/5] Filtrando estabelecimentos ATIVOS da RMRJ nos arquivos ESTABELE...")
    conn.execute("""
        CREATE OR REPLACE TEMP TABLE temp_estab_rmrj (
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
            INSERT INTO temp_estab_rmrj
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
            WHERE uf = 'RJ' 
              AND situacao_cadastral = '02' 
              AND municipio IN (SELECT cod_tom FROM dim_municipios_rmrj)
        """)
        parcial = conn.execute("SELECT COUNT(*) FROM temp_estab_rmrj").fetchone()[0]
        print(f"      [{idx:02d}/{len(estab_files):02d}] {file_name} -> total acumulado: {parcial:,} estabelecimentos ({time.time() - t0:.1f}s)")

    total_estabs = conn.execute("SELECT COUNT(*) FROM temp_estab_rmrj").fetchone()[0]
    print(f"   -> Concluído! {total_estabs:,} estabelecimentos ativos encontrados na RMRJ ({time.time() - t_estab_start:.1f}s)")

    # -------------------------------------------------------------------------
    # Passo 3: Extrair Dados de EMPRESAS para os CNPJs da RMRJ
    # -------------------------------------------------------------------------
    print("\n[3/5] Cruzando com os arquivos de EMPRESAS (Razão Social, Capital Social e Porte)...")
    conn.execute("""
        CREATE OR REPLACE TEMP TABLE temp_emp_rmrj (
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
            INSERT INTO temp_emp_rmrj
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
            SEMI JOIN temp_estab_rmrj s ON e.cnpj_basico = s.cnpj_basico
        """)
        parcial = conn.execute("SELECT COUNT(*) FROM temp_emp_rmrj").fetchone()[0]
        print(f"      [{idx:02d}/{len(emp_files):02d}] {file_name} -> total acumulado: {parcial:,} empresas ({time.time() - t0:.1f}s)")

    total_emps = conn.execute("SELECT COUNT(*) FROM temp_emp_rmrj").fetchone()[0]
    print(f"   -> Concluído! {total_emps:,} empresas únicas associadas na RMRJ ({time.time() - t_emp_start:.1f}s)")

    # -------------------------------------------------------------------------
    # Passo 4: Criar Tabela Física Consolidada no DuckDB
    # -------------------------------------------------------------------------
    print("\n[4/5] Gerando tabela final consolidada 'tb_empresas_ativas_rmrj' no DuckDB...")
    t0 = time.time()

    conn.execute("""
        CREATE OR REPLACE TABLE tb_empresas_ativas_rmrj AS
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

            -- Localização Detalhada
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
        FROM temp_estab_rmrj e
        LEFT JOIN temp_emp_rmrj m ON e.cnpj_basico = m.cnpj_basico
        LEFT JOIN dim_municipios_rmrj mun ON e.cod_municipio_tom = mun.cod_tom
        LEFT JOIN dim_cnae c ON e.cnae_fiscal_principal = c.cod_cnae
        LEFT JOIN dim_natju nj ON m.codigo_natureza_juridica = nj.codigo_natureza_juridica
        ORDER BY mun.municipio, m.razao_social
    """)

    total_final = conn.execute("SELECT COUNT(*) FROM tb_empresas_ativas_rmrj").fetchone()[0]
    print(f"      -> Tabela 'tb_empresas_ativas_rmrj' criada com {total_final:,} registros ({time.time() - t0:.1f}s)")

    # -------------------------------------------------------------------------
    # Passo 5: Exportar para Parquet
    # -------------------------------------------------------------------------
    print("\n[5/5] Exportando para formato Parquet de alta compressão (ZSTD)...")
    t0 = time.time()
    conn.execute(f"""
        COPY tb_empresas_ativas_rmrj TO '{output_parquet.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    tamanho_mb = output_parquet.stat().st_size / (1024 * 1024)
    print(f"      -> Arquivo Parquet gerado com sucesso: {tamanho_mb:.2f} MB ({time.time() - t0:.1f}s)")

    # Criação opcional do índice FTS BM25
    if build_fts:
        print("\n[Bônus] Criando índice FTS BM25 na coluna 'descricao_cnae_principal'...")
        t_fts = time.time()
        conn.execute("INSTALL fts; LOAD fts;")
        conn.execute("""
            PRAGMA create_fts_index(
                'tb_empresas_ativas_rmrj',
                'cnpj',
                'descricao_cnae_principal',
                stemmer = 'portuguese',
                strip_accents = 1
            );
        """)
        print(f"      -> Índice FTS BM25 criado em {time.time() - t_fts:.2f}s!")

    # Limpeza de tabelas temporárias
    conn.execute("DROP TABLE IF EXISTS temp_estab_rmrj")
    conn.execute("DROP TABLE IF EXISTS temp_emp_rmrj")
    conn.execute("DROP TABLE IF EXISTS dim_municipios_rmrj")
    conn.execute("DROP TABLE IF EXISTS dim_cnae")
    conn.execute("DROP TABLE IF EXISTS dim_natju")

    tempo_total = time.time() - inicio_total
    print("\n" + "=" * 80)
    print(f" PIPELINE RMRJ CONCLUÍDO COM SUCESSO EM {tempo_total / 60:.2f} MINUTOS!")
    print(f" -> Total de empresas ativas na RMRJ: {total_final:,}")
    print(f" -> Banco DuckDB: {db_path}")
    print(f" -> Arquivo Parquet: {output_parquet}")
    print("=" * 80)

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline de Extração das Empresas Ativas da RMRJ (DuckDB).")
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=DEFAULT_RAW_DIR,
        help="Diretório onde estão os arquivos brutos CSV/ZIP da Receita Federal."
    )
    parser.add_argument(
        "--processed-dir",
        type=Path,
        default=DEFAULT_PROCESSED_DIR,
        help="Diretório onde serão salvos o rmrj_empresas.duckdb e empresas_ativas_rmrj.parquet."
    )
    parser.add_argument(
        "--build-fts",
        action="store_true",
        help="Cria automaticamente o índice FTS BM25 no DuckDB ao final do processamento."
    )

    args = parser.parse_args()
    executar_pipeline(
        data_raw_dir=args.raw_dir,
        data_processed_dir=args.processed_dir,
        build_fts=args.build_fts
    )

#!/usr/bin/env python3
"""
Orquestrador de Atualização Automática da Base de Empresas (Receita Federal)
Projetado para execução contínua via Cron em servidores Linux (ex: Oracle Cloud Infrastructure - OCI).

Fluxo de Trabalho:
1. Carregamento de Configurações: Carrega regiões e municípios a partir de 'config/regioes_metropolitanas.json'.
2. Lock de Instância: Garante que apenas uma execução ocorra por vez (evita concorrência).
3. Verificação de Versão: Checa cabeçalhos HTTP (Last-Modified / ETag) no portal da Receita.
   Se a versão atual já estiver processada, encerra em segundos sem tráfego de rede.
4. Download Resiliente: Baixa os arquivos necessários com suporte a retry e reconexão (HTTP Range).
5. Descompactação Controlada: Extrai os arquivos para processamento.
6. ETL em Passada Única (DuckDB):
   Processa todas as regiões configuradas em um ÚNICO scan dos dados nacionais da Receita.
7. Publicação Atômica: Gera arquivos .tmp e substitui as bases finais via rename atômico (Zero Downtime).
8. Limpeza Automática: Remove arquivos brutos para economizar espaço em disco na VM.
9. Notificação Webhook (Opcional): Envia resumo de execução para Discord/Telegram/Slack.
"""

import argparse
import json
import logging
import os
import shutil
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import urllib.request
import urllib.error

try:
    import fcntl
except ImportError:
    fcntl = None  # Fallback para ambiente Windows durante desenvolvimento local

import duckdb

# -----------------------------------------------------------------------------
# Configuração de Diretórios e URLs
# -----------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_FILE = BASE_DIR / "config" / "regioes_metropolitanas.json"
DEFAULT_DATA_DIR = BASE_DIR / "receita"
DEFAULT_PROCESSED_DIR = DEFAULT_DATA_DIR / "processed"
DEFAULT_RAW_DIR = DEFAULT_DATA_DIR / "raw_downloads"
DEFAULT_LOG_FILE = BASE_DIR / "atualizador_receita.log"
LOCK_FILE_PATH = DEFAULT_DATA_DIR / ".atualizador_receita.lock"
VERSION_FILE_PATH = DEFAULT_DATA_DIR / "version_lock.json"

RFB_BASE_URL = "https://dadosabertos.rfb.gov.br/CNPJ/"

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

# -----------------------------------------------------------------------------
# Configuração de Logs
# -----------------------------------------------------------------------------
def setup_logging(log_path: Path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout)
        ]
    )


# -----------------------------------------------------------------------------
# Carregador de Configuração Externa (JSON)
# -----------------------------------------------------------------------------
def carregar_configuracao_regioes(config_path: Path) -> Tuple[List[Tuple[str, str, str, str]], Set[str], List[Dict]]:
    """
    Carrega o arquivo JSON com a definição das regiões e municípios alvo.
    Retorna:
      - municipios_alvo: [(cod_tom, municipio, uf, regiao_id), ...]
      - ufs_alvo: {'PR', 'RJ', 'SP', ...}
      - regioes_export: [{'id': ..., 'db_name': ..., 'parquet_name': ..., 'table_name': ...}, ...]
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Arquivo de configuração de regiões não encontrado: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    regioes = data.get("regioes", [])
    if not regioes:
        raise ValueError(f"Nenhuma região definida em {config_path}")

    municipios_alvo: List[Tuple[str, str, str, str]] = []
    ufs_alvo: Set[str] = set()
    regioes_export: List[Dict] = []

    for reg in regioes:
        reg_id = reg["id"]
        reg_uf = reg["uf"].upper()
        ufs_alvo.add(reg_uf)

        municipios_dict = reg.get("municipios", {})
        for cod_tom, nome_mun in municipios_dict.items():
            municipios_alvo.append((str(cod_tom), str(nome_mun), reg_uf, reg_id))

        regioes_export.append({
            "id": reg_id,
            "nome": reg.get("nome", reg_id),
            "uf": reg_uf,
            "db_name": reg.get("db_name", f"{reg_id.lower()}_empresas"),
            "parquet_name": reg.get("parquet_name", f"empresas_ativas_{reg_id.lower()}"),
            "table_name": reg.get("table_name", f"tb_empresas_ativas_{reg_id.lower()}"),
            "total_municipios": len(municipios_dict)
        })

    return municipios_alvo, ufs_alvo, regioes_export


# -----------------------------------------------------------------------------
# Gerenciamento de Lock de Execução (Evita concorrência no Cron)
# -----------------------------------------------------------------------------
class SingleInstanceLock:
    def __init__(self, lock_file: Path):
        self.lock_file = lock_file
        self.fp = None

    def __enter__(self):
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        self.fp = open(self.lock_file, "w")
        if fcntl:
            try:
                fcntl.flock(self.fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, IOError):
                logging.warning("⚠️  Outra instância do atualizador já está em execução. Encerrando.")
                sys.exit(0)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.fp:
            if fcntl:
                try:
                    fcntl.flock(self.fp, fcntl.LOCK_UN)
                except Exception:
                    pass
            self.fp.close()
            try:
                self.lock_file.unlink(missing_ok=True)
            except Exception:
                pass


# -----------------------------------------------------------------------------
# 1. Verificador de Versão Remota (Detecção Inteligente)
# -----------------------------------------------------------------------------
def verificar_nova_versao(url_base: str, version_file: Path) -> Tuple[bool, str, Dict]:
    """
    Verifica se a Receita Federal publicou nova versão avaliando o cabeçalho
    Last-Modified ou ETag de arquivos de referência no servidor.
    """
    logging.info("Verificando se há nova versão disponível no portal da Receita Federal...")
    
    # Arquivo Sentinela (Cnaes.zip é leve e sempre atualizado junto com a base)
    sentinel_url = f"{url_base.rstrip('/')}/Cnaes.zip"
    
    current_meta = {}
    if version_file.exists():
        try:
            with open(version_file, "r", encoding="utf-8") as f:
                current_meta = json.load(f)
        except Exception as e:
            logging.warning(f"Não foi possível ler o arquivo de versão local: {e}")

    try:
        req = urllib.request.Request(sentinel_url, method="HEAD")
        req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Cron-Receita-Updater/1.0")
        with urllib.request.urlopen(req, timeout=30) as resp:
            remote_last_modified = resp.headers.get("Last-Modified", "")
            remote_etag = resp.headers.get("ETag", "")
            remote_version_tag = remote_last_modified or remote_etag or datetime.now().strftime("%Y-%m-%d")

        last_known_tag = current_meta.get("version_tag", "")
        
        if last_known_tag and last_known_tag == remote_version_tag:
            logging.info(f"✅ Nenhuma nova versão encontrada. Versão local já atualizada: '{last_known_tag}'.")
            return False, remote_version_tag, current_meta
        
        logging.info(f"🚀 Nova versão detectada! Remota: '{remote_version_tag}' | Anterior: '{last_known_tag}'")
        return True, remote_version_tag, current_meta

    except Exception as e:
        logging.error(f"Erro ao verificar versão remota em {sentinel_url}: {e}")
        return False, "", current_meta


# -----------------------------------------------------------------------------
# 2. Download Resiliente com Chunks e Retries
# -----------------------------------------------------------------------------
def baixar_arquivo(url: str, destino: Path, max_retries: int = 5, timeout: int = 60) -> bool:
    """
    Baixa um arquivo via HTTP com suporte a retomada parcial (Resume) e retries.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    temp_file = destino.with_suffix(destino.suffix + ".part")

    for tentativa in range(1, max_retries + 1):
        try:
            bytes_existentes = temp_file.stat().st_size if temp_file.exists() else 0
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Cron-Receita-Updater/1.0"}
            
            if bytes_existentes > 0:
                headers["Range"] = f"bytes={bytes_existentes}-"
                logging.info(f"   [Resume] Retomando {destino.name} a partir de {bytes_existentes / (1024*1024):.1f} MB...")

            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp, open(temp_file, "ab" if bytes_existentes > 0 else "wb") as f_out:
                shutil.copyfileobj(resp, f_out, length=1024 * 1024)

            # Move do .part para o arquivo final
            temp_file.replace(destino)
            tamanho_mb = destino.stat().st_size / (1024 * 1024)
            logging.info(f"   ✓ Concluído: {destino.name} ({tamanho_mb:.1f} MB)")
            return True

        except Exception as e:
            logging.warning(f"   ⚠️  Tentativa {tentativa}/{max_retries} falhou para {destino.name}: {e}")
            time.sleep(5 * tentativa)

    logging.error(f"❌ Falha definitiva no download de {url} após {max_retries} tentativas.")
    return False


def obter_lista_arquivos_necessarios(url_base: str) -> List[str]:
    """Retorna a lista dos arquivos essenciais a serem baixados."""
    arquivos = [
        "Cnaes.zip",
        "Naturezas.zip",
        "Municipios.zip",
    ]
    # 10 Estabelecimentos (0 a 9)
    for i in range(10):
        arquivos.append(f"Estabelecimentos{i}.zip")
    # 10 Empresas (0 a 9)
    for i in range(10):
        arquivos.append(f"Empresas{i}.zip")
    return arquivos


def descompactar_zip(arquivo_zip: Path, pasta_destino: Path):
    """Descompacta um arquivo .zip se ainda não estiver descompactado."""
    pasta_destino.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(arquivo_zip, "r") as z:
        for member in z.namelist():
            target_path = pasta_destino / member
            if not target_path.exists():
                logging.info(f"   Extraindo {member}...")
                z.extract(member, pasta_destino)


# -----------------------------------------------------------------------------
# 3. Pipeline ETL em Passada Única com DuckDB
# -----------------------------------------------------------------------------
def executar_etl_unificado(
    raw_dir: Path,
    processed_dir: Path,
    municipios_alvo: List[Tuple[str, str, str, str]],
    ufs_alvo: Set[str],
    regioes_export: List[Dict],
    build_fts: bool = False
) -> Dict[str, int]:
    """
    Executa a extração, unificação e enriquecimento de todas as regiões configuradas
    em uma única passada pelos dados nacionais da Receita Federal.
    """
    t_inicio = time.time()
    processed_dir.mkdir(parents=True, exist_ok=True)
    
    temp_work_dir = raw_dir / "duckdb_temp"
    temp_work_dir.mkdir(parents=True, exist_ok=True)

    estab_files = sorted(list(set(
        [f.as_posix() for f in raw_dir.glob("*ESTABELE*") if not f.name.lower().endswith((".zip", ".part"))] +
        [f.as_posix() for f in raw_dir.glob("*estabele*") if not f.name.lower().endswith((".zip", ".part"))]
    )))

    emp_files = sorted(list(set(
        [f.as_posix() for f in raw_dir.glob("*EMPRECSV*") if not f.name.lower().endswith((".zip", ".part"))] +
        [f.as_posix() for f in raw_dir.glob("*empcsv*") if not f.name.lower().endswith((".zip", ".part"))]
    )))

    cnae_files = sorted(list(set(
        [f.as_posix() for f in raw_dir.glob("*CNAE*") if not f.name.lower().endswith((".zip", ".part"))] +
        [f.as_posix() for f in raw_dir.glob("*cnae*") if not f.name.lower().endswith((".zip", ".part"))]
    )))

    natju_files = sorted(list(set(
        [f.as_posix() for f in raw_dir.glob("*NATJU*") if not f.name.lower().endswith((".zip", ".part"))] +
        [f.as_posix() for f in raw_dir.glob("*natju*") if not f.name.lower().endswith((".zip", ".part"))]
    )))

    logging.info(f"Arquivos prontos: {len(estab_files)} Estabelecimentos, {len(emp_files)} Empresas, {len(cnae_files)} CNAE.")
    if not estab_files or not emp_files or not cnae_files:
        raise RuntimeError("Arquivos CSV descompactados da Receita não encontrados.")

    conn = duckdb.connect()
    conn.execute("SET preserve_insertion_order = false")
    conn.execute(f"PRAGMA temp_directory='{temp_work_dir.as_posix()}'")

    # 1. Carrega Dimensões Auxiliares
    logging.info(f"[1/5] Carregando dimensões ({len(municipios_alvo)} municípios configurados em {len(ufs_alvo)} UFs)...")
    conn.execute("""
        CREATE OR REPLACE TEMP TABLE dim_municipios_alvo (
            cod_tom VARCHAR,
            municipio VARCHAR,
            uf VARCHAR,
            regiao VARCHAR
        )
    """)
    conn.executemany("INSERT INTO dim_municipios_alvo VALUES (?, ?, ?, ?)", municipios_alvo)

    conn.execute(f"""
        CREATE OR REPLACE TEMP TABLE dim_cnae AS
        SELECT cod_cnae, TRIM(descricao_cnae) AS descricao_cnae
        FROM read_csv('{cnae_files[0]}', delim=';', header=false, all_varchar=true, encoding='iso-8859_1-1998', ignore_errors=true, names=['cod_cnae', 'descricao_cnae'])
    """)

    if natju_files:
        conn.execute(f"""
            CREATE OR REPLACE TEMP TABLE dim_natju AS
            SELECT codigo_natureza_juridica, TRIM(natureza_juridica) AS natureza_juridica
            FROM read_csv('{natju_files[0]}', delim=';', header=false, all_varchar=true, encoding='iso-8859_1-1998', ignore_errors=true, names=['codigo_natureza_juridica', 'natureza_juridica'])
        """)
    else:
        conn.execute("CREATE OR REPLACE TEMP TABLE dim_natju (codigo_natureza_juridica VARCHAR, natureza_juridica VARCHAR)")

    # 2. Filtragem dos Estabelecimentos Ativos em Passada Única
    ufs_sql = ", ".join(f"'{uf}'" for uf in sorted(ufs_alvo))
    logging.info(f"[2/5] Filtrando estabelecimentos ATIVOS para UFs [{ufs_sql}] em passada única...")
    conn.execute("""
        CREATE OR REPLACE TEMP TABLE temp_estab_alvo (
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

    for idx, f in enumerate(estab_files, 1):
        t0 = time.time()
        conn.execute(f"""
            INSERT INTO temp_estab_alvo
            SELECT
                cnpj_basico, cnpj_ordem, cnpj_dv,
                CASE matriz_filial WHEN '1' THEN 'Matriz' WHEN '2' THEN 'Filial' ELSE matriz_filial END AS matriz_filial,
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
            FROM read_csv('{f}', delim=';', header=false, all_varchar=true, encoding='iso-8859_1-1998', ignore_errors=true, names={ESTAB_COL_NAMES})
            WHERE uf IN ({ufs_sql})
              AND situacao_cadastral = '02'
              AND (uf, municipio) IN (SELECT uf, cod_tom FROM dim_municipios_alvo)
        """)
        logging.info(f"   [{idx:02d}/{len(estab_files):02d}] {Path(f).name} processado em {time.time() - t0:.1f}s")

    total_estabs = conn.execute("SELECT COUNT(*) FROM temp_estab_alvo").fetchone()[0]
    logging.info(f"Total de estabelecimentos ativos coletados nas regiões: {total_estabs:,}")

    # 3. Cruzamento com Empresas (Razão Social, Porte, Capital Social)
    logging.info("[3/5] Cruzando com arquivos de Empresas (SEMI JOIN)...")
    conn.execute("""
        CREATE OR REPLACE TEMP TABLE temp_emp_alvo (
            cnpj_basico VARCHAR,
            razao_social VARCHAR,
            codigo_natureza_juridica VARCHAR,
            capital_social DOUBLE,
            porte_empresa VARCHAR
        )
    """)

    for idx, f in enumerate(emp_files, 1):
        t0 = time.time()
        conn.execute(f"""
            INSERT INTO temp_emp_alvo
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
            FROM read_csv('{f}', delim=';', header=false, all_varchar=true, encoding='iso-8859_1-1998', ignore_errors=true, names={EMPRE_COL_NAMES}) e
            SEMI JOIN temp_estab_alvo s ON e.cnpj_basico = s.cnpj_basico
        """)
        logging.info(f"   [{idx:02d}/{len(emp_files):02d}] {Path(f).name} associado em {time.time() - t0:.1f}s")

    # 4. Tabela Consolidada Geral em Memória
    logging.info("[4/5] Enriquecendo e formatando dados consolidados...")
    conn.execute("""
        CREATE OR REPLACE TEMP TABLE tb_empresas_consolidadas AS
        SELECT
            SUBSTRING(e.cnpj_basico, 1, 2) || '.' || 
            SUBSTRING(e.cnpj_basico, 3, 3) || '.' || 
            SUBSTRING(e.cnpj_basico, 6, 3) || '/' || 
            e.cnpj_ordem || '-' || e.cnpj_dv AS cnpj,
            e.cnpj_basico,
            m.razao_social,
            e.nome_fantasia,
            e.matriz_filial,
            m.porte_empresa,
            m.capital_social,
            m.codigo_natureza_juridica,
            COALESCE(nj.natureza_juridica, 'Não Especificada') AS natureza_juridica,
            e.data_inicio_atividade,
            CASE WHEN e.data_inicio_atividade IS NOT NULL THEN date_diff('year', e.data_inicio_atividade, CURRENT_DATE) ELSE NULL END AS idade_anos,
            e.cnae_fiscal_principal,
            COALESCE(c.descricao_cnae, 'Descrição não encontrada') AS descricao_cnae_principal,
            e.cnae_fiscal_secundaria,
            e.tipo_logradouro,
            e.logradouro,
            e.numero,
            e.complemento,
            e.bairro,
            e.cep,
            mun.municipio,
            e.uf,
            mun.regiao,
            CONCAT_WS(', ',
                NULLIF(TRIM(CONCAT_WS(' ', e.tipo_logradouro, e.logradouro)), ''),
                NULLIF(e.numero, ''),
                NULLIF(e.complemento, ''),
                NULLIF(e.bairro, ''),
                mun.municipio || ' - ' || e.uf,
                CASE WHEN e.cep IS NOT NULL THEN 'CEP: ' || e.cep ELSE NULL END
            ) AS endereco_completo,
            CASE WHEN e.ddd_1 IS NOT NULL AND e.telefone_1 IS NOT NULL THEN '(' || e.ddd_1 || ') ' || e.telefone_1 ELSE NULL END AS telefone_1,
            CASE WHEN e.ddd_2 IS NOT NULL AND e.telefone_2 IS NOT NULL THEN '(' || e.ddd_2 || ') ' || e.telefone_2 ELSE NULL END AS telefone_2,
            e.email,
            CURRENT_TIMESTAMP AS data_extracao
        FROM temp_estab_alvo e
        LEFT JOIN temp_emp_alvo m ON e.cnpj_basico = m.cnpj_basico
        LEFT JOIN dim_municipios_alvo mun ON e.uf = mun.uf AND e.cod_municipio_tom = mun.cod_tom
        LEFT JOIN dim_cnae c ON e.cnae_fiscal_principal = c.cod_cnae
        LEFT JOIN dim_natju nj ON m.codigo_natureza_juridica = nj.codigo_natureza_juridica
    """)

    # 5. Geração Atômica por Região (.parquet e .duckdb)
    logging.info(f"[5/5] Exportando bases analíticas para {len(regioes_export)} regiões com rotação atômica...")
    metricas_resultado = {}

    for reg in regioes_export:
        cod_regiao = reg["id"]
        db_prefix = reg["db_name"]
        parquet_prefix = reg["parquet_name"]
        table_name = reg["table_name"]

        final_parquet = processed_dir / f"{parquet_prefix}.parquet"
        tmp_parquet = processed_dir / f"{parquet_prefix}.parquet.tmp"
        
        final_db = processed_dir / f"{db_prefix}.duckdb"
        tmp_db = processed_dir / f"{db_prefix}.duckdb.tmp"

        # Exporta Parquet temporário
        conn.execute(f"""
            COPY (
                SELECT * EXCLUDE (regiao)
                FROM tb_empresas_consolidadas
                WHERE regiao = '{cod_regiao}'
                ORDER BY municipio, razao_social
            ) TO '{tmp_parquet.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)
        os.replace(tmp_parquet, final_parquet)

        # Gera DuckDB temporário e preenche
        if tmp_db.exists():
            tmp_db.unlink()
        regiao_conn = duckdb.connect(str(tmp_db))
        regiao_conn.execute(f"""
            CREATE TABLE {table_name} AS 
            SELECT * FROM read_parquet('{final_parquet.as_posix()}')
        """)
        count_regiao = regiao_conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        metricas_resultado[cod_regiao] = count_regiao

        if build_fts:
            regiao_conn.execute("INSTALL fts; LOAD fts;")
            regiao_conn.execute(f"""
                PRAGMA create_fts_index(
                    '{table_name}',
                    'cnpj',
                    'descricao_cnae_principal',
                    stemmer = 'portuguese',
                    strip_accents = 1
                );
            """)
        regiao_conn.close()
        os.replace(tmp_db, final_db)

        tamanho_pq = final_parquet.stat().st_size / (1024 * 1024)
        tamanho_db = final_db.stat().st_size / (1024 * 1024)
        logging.info(f"   -> [{cod_regiao} - {reg['nome']}] {count_regiao:,} empresas | Parquet: {tamanho_pq:.1f} MB | DuckDB: {tamanho_db:.1f} MB")

    conn.close()
    tempo_total = (time.time() - t_inicio) / 60
    logging.info(f"ETL unificado concluído com sucesso em {tempo_total:.2f} minutos!")
    return metricas_resultado


# -----------------------------------------------------------------------------
# 4. Notificação Webhook (Opcional - Discord / Telegram / Slack)
# -----------------------------------------------------------------------------
def enviar_notificacao_webhook(webhook_url: Optional[str], versao: str, metricas: Dict[str, int], duracao_min: float):
    if not webhook_url:
        return
    try:
        linhas_metricas = "\n".join([f"- **{regiao}**: {qtd:,} empresas ativas" for regiao, qtd in metricas.items()])
        payload = {
            "content": (
                f"✅ **Bases de Empresas da Receita Federal Atualizadas!**\n"
                f"📅 **Versão:** `{versao}` | ⏱️ **Duração:** {duracao_min:.1f} min\n"
                f"📊 **Resultados:**\n{linhas_metricas}"
            )
        }
        data_json = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=data_json,
            headers={"Content-Type": "application/json", "User-Agent": "Receita-Cron-Updater"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            pass
        logging.info("Notificação webhook enviada com sucesso.")
    except Exception as e:
        logging.warning(f"Não foi possível enviar webhook: {e}")


# -----------------------------------------------------------------------------
# 5. Função Principal (Orquestração do Cron)
# -----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Atualizador Automático da Base de Empresas (Cron / OCI)")
    parser.add_argument("--config-file", type=Path, default=DEFAULT_CONFIG_FILE, help="Arquivo JSON de configuração das regiões.")
    parser.add_argument("--force", action="store_true", help="Força a execução mesmo se a versão não tiver mudado.")
    parser.add_argument("--skip-download", action="store_true", help="Pula download e processa os arquivos já existentes em raw.")
    parser.add_argument("--keep-raw", action="store_true", help="Não deleta os zips/CSVs brutos ao final da execução.")
    parser.add_argument("--build-fts", action="store_true", help="Gera índice FTS BM25 nos bancos DuckDB.")
    parser.add_argument("--webhook-url", type=str, default=os.getenv("RECEITA_WEBHOOK_URL", ""), help="URL de Webhook para alertas.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="Diretório base de dados.")
    args = parser.parse_args()

    data_dir = args.data_dir
    processed_dir = data_dir / "processed"
    raw_dir = data_dir / "raw_downloads"
    version_file = data_dir / "version_lock.json"
    lock_file = data_dir / ".atualizador_receita.lock"
    log_file = data_dir / "atualizador_receita.log"

    setup_logging(log_file)
    logging.info("=" * 80)
    logging.info("INICIANDO ROTINA DO ATUALIZADOR DA RECEITA FEDERAL")
    logging.info("=" * 80)

    # Carrega arquivo JSON de configuração das regiões
    municipios_alvo, ufs_alvo, regioes_export = carregar_configuracao_regioes(args.config_file)
    nomes_regioes = ", ".join([f"{r['id']} ({r['total_municipios']} mun)" for r in regioes_export])
    logging.info(f"Regiões carregadas de '{args.config_file.name}': {nomes_regioes}")

    # Bloqueia execução concorrente
    with SingleInstanceLock(lock_file):
        inicio_cron = time.time()
        
        # 1. Checagem de versão
        houve_mudanca, versao_remota, current_meta = verificar_nova_versao(RFB_BASE_URL, version_file)
        if not houve_mudanca and not args.force and not args.skip_download:
            logging.info("Fim da rotina (nada a fazer).")
            return

        # 2. Download dos arquivos
        if not args.skip_download:
            logging.info("Baixando arquivos oficiais da Receita Federal...")
            arquivos_necessarios = obter_lista_arquivos_necessarios(RFB_BASE_URL)
            for arq in arquivos_necessarios:
                url = f"{RFB_BASE_URL.rstrip('/')}/{arq}"
                destino_zip = raw_dir / arq
                if not destino_zip.exists() or args.force:
                    sucesso = baixar_arquivo(url, destino_zip)
                    if not sucesso:
                        logging.error(f"Abortando pipeline devido à falha no download de {arq}.")
                        sys.exit(1)
                
                # Descompacta assim que baixar para economizar espaço se necessário
                descompactar_zip(destino_zip, raw_dir)
                if not args.keep_raw and destino_zip.exists():
                    destino_zip.unlink()  # Deleta o .zip logo após extrair para economizar disco

        # 3. Execução do ETL em passada única
        metricas = executar_etl_unificado(
            raw_dir=raw_dir,
            processed_dir=processed_dir,
            municipios_alvo=municipios_alvo,
            ufs_alvo=ufs_alvo,
            regioes_export=regioes_export,
            build_fts=args.build_fts
        )

        # 4. Limpeza pós-processamento
        if not args.keep_raw:
            logging.info("Limpando arquivos brutos CSV temporários para liberar espaço em disco...")
            for f in raw_dir.glob("*"):
                if f.is_file() and not f.name.endswith(".duckdb"):
                    try:
                        f.unlink()
                    except Exception:
                        pass
            shutil.rmtree(raw_dir / "duckdb_temp", ignore_errors=True)

        # 5. Atualiza o arquivo de versão
        novo_meta = {
            "version_tag": versao_remota or datetime.now().strftime("%Y-%m-%d"),
            "data_atualizacao": datetime.now().isoformat(),
            "metricas": metricas
        }
        with open(version_file, "w", encoding="utf-8") as f:
            json.dump(novo_meta, f, indent=2, ensure_ascii=False)

        duracao_total = (time.time() - inicio_cron) / 60
        logging.info("=" * 80)
        logging.info(f"ROTINA CONCLUÍDA COM SUCESSO EM {duracao_total:.2f} MINUTOS!")
        logging.info("=" * 80)

        # 6. Webhook
        enviar_notificacao_webhook(args.webhook_url, versao_remota, metricas, duracao_total)


if __name__ == "__main__":
    main()

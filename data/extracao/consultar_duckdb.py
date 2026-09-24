"""
Utilitário para consulta rápida e inspeção do banco DuckDB.
"""

from pathlib import Path
import duckdb

# Caminhos dos bancos DuckDB (prioriza o processado com as empresas ativas)
DB_PATH_PROCESSED = Path(__file__).resolve().parent.parent / "data" / "processed" / "rmc_empresas.duckdb"
DB_PATH_RAW = Path(__file__).resolve().parent.parent / "data" / "raw" / "rmc_database.duckdb"
DB_PATH = DB_PATH_PROCESSED if DB_PATH_PROCESSED.exists() else DB_PATH_RAW

def consultar():
    if not DB_PATH.exists():
        print(f"Erro: Banco de dados não encontrado em {DB_PATH_PROCESSED} nem em {DB_PATH_RAW}")
        print("Execute primeiro: python src/extrair_empresas_ativas_rmc.py")
        return

    # Conecta em modo leitura (read_only evita conflitos de lock)
    conn = duckdb.connect(str(DB_PATH), read_only=True)

    print("=" * 75)
    print(" 1. TABELAS DISPONÍVEIS NO BANCO")
    print("=" * 75)
    tabelas = [row[0] for row in conn.execute("SHOW TABLES").fetchall()]
    conn.sql("SHOW TABLES").show()

    if "tb_empresas_ativas_rmc" in tabelas:
        print("\n" + "=" * 75)
        print(" 2. VISÃO GERAL DAS EMPRESAS ATIVAS NA RMC")
        print("=" * 75)
        total = conn.execute("SELECT COUNT(*) FROM tb_empresas_ativas_rmc").fetchone()[0]
        total_matrizes = conn.execute("SELECT COUNT(*) FROM tb_empresas_ativas_rmc WHERE matriz_filial = 'Matriz'").fetchone()[0]
        total_com_tel = conn.execute("SELECT COUNT(*) FROM tb_empresas_ativas_rmc WHERE telefone_1 IS NOT NULL").fetchone()[0]
        total_com_email = conn.execute("SELECT COUNT(*) FROM tb_empresas_ativas_rmc WHERE email IS NOT NULL").fetchone()[0]
        print(f"Total de Empresas Ativas na RMC: {total:,}")
        print(f"  - Matrizes:                     {total_matrizes:,} ({total_matrizes/total*100:.1f}%)")
        print(f"  - Filiais:                      {total - total_matrizes:,} ({(total - total_matrizes)/total*100:.1f}%)")
        print(f"  - Com Telefone Cadastrado:      {total_com_tel:,} ({total_com_tel/total*100:.1f}%)")
        print(f"  - Com E-mail Cadastrado:        {total_com_email:,} ({total_com_email/total*100:.1f}%)")

        print("\n" + "=" * 75)
        print(" 3. TOP 50 MUNICÍPIOS COM MAIS EMPRESAS ATIVAS")
        print("=" * 75)
        conn.sql("""
            SELECT 
                municipio,
                COUNT(*) AS total_empresas,
                ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) AS percentual,
                ROUND(AVG(capital_social), 2) AS capital_medio
            FROM tb_empresas_ativas_rmc
            GROUP BY municipio
            ORDER BY total_empresas DESC
            LIMIT 50
        """).show()

        print("\n" + "=" * 75)
        print(" 4. TOP 10 NATUREZAS JURÍDICAS NA RMC")
        print("=" * 75)
        conn.sql("""
            SELECT 
                codigo_natureza_juridica AS cod,
                natureza_juridica,
                COUNT(*) AS total_empresas,
                ROUND(AVG(capital_social), 2) AS capital_social_medio
            FROM tb_empresas_ativas_rmc
            GROUP BY codigo_natureza_juridica, natureza_juridica
            ORDER BY total_empresas DESC
            LIMIT 10
        """).show()

        print("\n" + "=" * 75)
        print(" 5. TOP 10 ATIVIDADES ECONÔMICAS PRINCIPAIS (CNAE)")
        print("=" * 75)
        conn.sql("""
            SELECT 
                cnae_fiscal_principal AS cnae,
                descricao_cnae_principal AS atividade,
                COUNT(*) AS total_empresas
            FROM tb_empresas_ativas_rmc
            GROUP BY cnae_fiscal_principal, descricao_cnae_principal
            ORDER BY total_empresas DESC
            LIMIT 10
        """).show()

        print("\n" + "=" * 75)
        print(" 6. DISTRIBUIÇÃO POR FAIXA DE IDADE (TEMPO DE ATIVIDADE)")
        print("=" * 75)
        conn.sql("""
            SELECT 
                CASE 
                    WHEN idade_anos < 2 THEN '1. Até 2 anos'
                    WHEN idade_anos BETWEEN 2 AND 5 THEN '2. 2 a 5 anos'
                    WHEN idade_anos BETWEEN 6 AND 10 THEN '3. 6 a 10 anos'
                    WHEN idade_anos BETWEEN 11 AND 20 THEN '4. 11 a 20 anos'
                    ELSE '5. Mais de 20 anos'
                END AS faixa_idade,
                COUNT(*) AS total_empresas,
                ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) AS percentual
            FROM tb_empresas_ativas_rmc
            WHERE idade_anos IS NOT NULL
            GROUP BY faixa_idade
            ORDER BY faixa_idade
        """).show()

        print("\n" + "=" * 75)
        print(" 7. AMOSTRA DE EMPRESAS COM CONTATO E ENDEREÇO")
        print("=" * 75)
        conn.sql("""
            SELECT 
                cnpj,
                razao_social,
                municipio,
                bairro,
                telefone_1,
                email,
                idade_anos AS idade
            FROM tb_empresas_ativas_rmc
            WHERE telefone_1 IS NOT NULL AND email IS NOT NULL
            LIMIT 5
        """).show()

    elif "dim_municipios_rmc" in tabelas:
        print("\n" + "=" * 75)
        print(" 2. ESTRUTURA DA TABELA (SCHEMA)")
        print("=" * 75)
        conn.sql("DESCRIBE dim_municipios_rmc").show()

        print("\n" + "=" * 75)
        print(" 3. AMOSTRA DOS MUNICÍPIOS")
        print("=" * 75)
        conn.sql("SELECT * FROM dim_municipios_rmc LIMIT 10").show()

    conn.close()

if __name__ == "__main__":
    consultar()

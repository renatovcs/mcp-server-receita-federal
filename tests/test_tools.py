"""
Suíte de testes de integração e validação das ferramentas MCP com DuckDB Singleton.
Valida consultas FTS, paginação, filtros geográficos (UF, município, bairro),
e as novas ferramentas analíticas.
Compatível com base de produção e com fixture sintética para CI/CD.
"""

from pathlib import Path
import tempfile
import unittest
import duckdb

from src.config import settings
from src.database import db_manager
from src.tools import (
    analyze_market_competition,
    get_biggest_companies_by_capital,
    get_provider_details,
    list_available_cities,
    search_company_by_name,
    search_providers_by_service,
)


class TestMCPTools(unittest.TestCase):
    _temp_db_dir: tempfile.TemporaryDirectory = None

    @classmethod
    def setUpClass(cls):
        """
        Inicializa a conexão DuckDB Singleton.
        Se a base de produção não estiver presente (ex: CI/CD do GitHub Actions),
        cria uma fixture sintética em memória/disco com dados de PR e RJ e índice FTS.
        """
        test_db = settings.DUCKDB_PATH
        if not test_db.exists():
            cls._temp_db_dir = tempfile.TemporaryDirectory()
            test_db = Path(cls._temp_db_dir.name) / "test_empresas.duckdb"
            conn = duckdb.connect(str(test_db))
            conn.execute("""
                CREATE TABLE tb_empresas_ativas (
                    cnpj VARCHAR,
                    cnpj_basico VARCHAR,
                    razao_social VARCHAR,
                    nome_fantasia VARCHAR,
                    matriz_filial INTEGER,
                    porte_empresa VARCHAR,
                    capital_social DOUBLE,
                    codigo_natureza_juridica VARCHAR,
                    natureza_juridica VARCHAR,
                    data_inicio_atividade DATE,
                    idade_anos DOUBLE,
                    cnae_fiscal_principal VARCHAR,
                    descricao_cnae_principal VARCHAR,
                    cnae_fiscal_secundaria VARCHAR,
                    tipo_logradouro VARCHAR,
                    logradouro VARCHAR,
                    numero VARCHAR,
                    complemento VARCHAR,
                    bairro VARCHAR,
                    cep VARCHAR,
                    municipio VARCHAR,
                    uf VARCHAR,
                    endereco_completo VARCHAR,
                    telefone_1 VARCHAR,
                    telefone_2 VARCHAR,
                    email VARCHAR
                );
            """)
            conn.execute("""
                INSERT INTO tb_empresas_ativas VALUES 
                ('81.172.264/0001-24', '81172264', 'SOLAR CURITIBA LTDA', 'SOLAR PR', 1, 'ME', 150000.0, '2062', 'SOCIEDADE EMPRESARIA LIMITADA', '2015-01-01', 9.5, '4321500', 'instalacao e manutencao de paineis de energia solar e ar condicionado', NULL, 'RUA', 'XV DE NOVEMBRO', '100', NULL, 'CENTRO', '80020-000', 'Curitiba', 'PR', 'RUA XV DE NOVEMBRO, 100, CENTRO, Curitiba - PR', '4133334444', NULL, 'contato@solar.com'),
                ('02.993.750/0001-37', '02993750', 'CLINICA BATEL MEDICINA LTDA', 'CLINICA BATEL', 1, 'EPP', 500000.0, '2062', 'SOCIEDADE EMPRESARIA LIMITADA', '2010-05-10', 14.2, '8630501', 'atividade medica ambulatorial e clinica geral', NULL, 'AV', 'BATEL', '1230', NULL, 'BATEL', '80420-090', 'Curitiba', 'PR', 'AV BATEL, 1230, BATEL, Curitiba - PR', '4132221111', NULL, 'clinica@batel.com'),
                ('12.345.678/0001-90', '12345678', 'RIO ENERGIA SOLAR E ELETRICIDADE S.A.', 'RIO SOLAR', 1, 'DEMAIS', 50000000.0, '2054', 'SOCIEDADE ANONIMA FECHADA', '2005-03-15', 19.3, '4321500', 'instalacao de geradores de energia solar e refrigeracao predial', NULL, 'AV', 'RIO BRANCO', '1', NULL, 'CENTRO', '20040-001', 'Rio de Janeiro', 'RJ', 'AV RIO BRANCO, 1, CENTRO, Rio de Janeiro - RJ', '2122223333', NULL, 'diretoria@riosolar.com'),
                ('99.888.777/0001-11', '99888777', 'BARRA CLIMA AR CONDICIONADO LTDA', 'BARRA CLIMA', 1, 'ME', 80000.0, '2062', 'SOCIEDADE EMPRESARIA LIMITADA', '2018-08-20', 6.1, '4322302', 'instalacao e manutencao de sistemas centrais de ar condicionado e ventilacao', NULL, 'AV', 'DAS AMERICAS', '500', NULL, 'BARRA DA TIJUCA', '22640-100', 'Rio de Janeiro', 'RJ', 'AV DAS AMERICAS, 500, BARRA DA TIJUCA, Rio de Janeiro - RJ', '2133335555', NULL, 'contato@barraclima.com'),
                ('33.444.555/0001-22', '33444555', 'PAULISTA ENERGIA SOLAR LTDA', 'PAULISTA SOLAR', 1, 'EPP', 300000.0, '2062', 'SOCIEDADE EMPRESARIA LIMITADA', '2016-04-12', 8.2, '4321500', 'instalacao e manutencao de paineis de energia solar', NULL, 'AV', 'PAULISTA', '1000', NULL, 'BELA VISTA', '01310-100', 'São Paulo', 'SP', 'AV PAULISTA, 1000, BELA VISTA, São Paulo - SP', '1133334444', NULL, 'contato@paulistasolar.com');
            """)
            conn.execute("INSTALL fts; LOAD fts;")
            conn.execute("""
                PRAGMA create_fts_index(
                    'tb_empresas_ativas',
                    'cnpj',
                    'descricao_cnae_principal',
                    stemmer = 'portuguese',
                    strip_accents = 1
                );
            """)
            conn.close()

        db_manager.initialize(test_db)

    @classmethod
    def tearDownClass(cls):
        """Encerra a conexão e limpa arquivos temporários se houver."""
        db_manager.close()
        if cls._temp_db_dir:
            cls._temp_db_dir.cleanup()

    def test_01_list_available_cities(self):
        cities = list_available_cities()
        self.assertIsInstance(cities, list)
        self.assertGreater(len(cities), 0)

        city_names = [c.municipio for c in cities]
        self.assertIn("Rio de Janeiro", city_names)
        self.assertIn("Curitiba", city_names)
        self.assertIn("São Paulo", city_names)

        # Filtro por UF
        rj_cities = list_available_cities(uf="RJ")
        for c in rj_cities:
            self.assertEqual(c.uf, "RJ")

        pr_cities = list_available_cities(uf="PR")
        for c in pr_cities:
            self.assertEqual(c.uf, "PR")

        sp_cities = list_available_cities(uf="SP")
        for c in sp_cities:
            self.assertEqual(c.uf, "SP")

    def test_02_search_providers_by_service_pr(self):
        results = search_providers_by_service(
            query="solar",
            uf="PR",
            municipio="Curitiba",
            limit=5,
        )
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)

        for provider in results:
            self.assertIsNotNone(provider.cnpj)
            self.assertIsNotNone(provider.razao_social)
            self.assertEqual(provider.uf, "PR")
            self.assertEqual(provider.municipio.lower(), "curitiba")
            self.assertGreater(provider.fts_score, 0)

    def test_03_search_providers_by_service_rj(self):
        results = search_providers_by_service(
            query="solar",
            uf="RJ",
            limit=5,
        )
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)

        for provider in results:
            self.assertIsNotNone(provider.cnpj)
            self.assertEqual(provider.uf, "RJ")
            self.assertGreater(provider.fts_score, 0)

    def test_03b_search_providers_by_service_sp(self):
        results = search_providers_by_service(
            query="solar",
            uf="SP",
            municipio="São Paulo",
            limit=5,
        )
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)

        for provider in results:
            self.assertIsNotNone(provider.cnpj)
            self.assertEqual(provider.uf, "SP")
            self.assertGreater(provider.fts_score, 0)

    def test_04_search_providers_pagination_and_bairro(self):
        # 1. Filtro por bairro
        centro_results = search_providers_by_service(
            query="solar",
            uf="PR",
            municipio="Curitiba",
            bairro="Centro",
            limit=5,
        )
        self.assertGreater(len(centro_results), 0)
        for r in centro_results:
            self.assertIn("CENTRO", r.bairro.upper())

        # 2. Paginação via offset
        p1 = search_providers_by_service(query="solar", limit=1, offset=0)
        p2 = search_providers_by_service(query="solar", limit=1, offset=1)
        if len(p1) > 0 and len(p2) > 0:
            self.assertNotEqual(p1[0].cnpj, p2[0].cnpj)

    def test_05_get_provider_details_masked_and_unmasked(self):
        search_sample = search_providers_by_service(query="solar", limit=1)
        self.assertTrue(len(search_sample) > 0)
        original_cnpj = search_sample[0].cnpj

        # Busca com máscara
        details = get_provider_details(original_cnpj)
        self.assertIsNotNone(details)
        self.assertEqual(details.cnpj, original_cnpj)
        self.assertIsNotNone(details.razao_social)

        # Busca sem máscara (apenas dígitos)
        raw_digits = original_cnpj.replace(".", "").replace("/", "").replace("-", "")
        details_unmasked = get_provider_details(raw_digits)
        self.assertIsNotNone(details_unmasked)
        self.assertEqual(details_unmasked.cnpj, original_cnpj)

    def test_06_get_provider_details_nonexistent(self):
        details = get_provider_details("00.000.000/0000-00")
        self.assertIsNone(details)

    def test_07_analyze_market_competition(self):
        analise = analyze_market_competition(query="solar", uf="PR", municipio="Curitiba")
        self.assertIsNotNone(analise)
        self.assertEqual(analise.termo_buscado, "solar")
        self.assertGreater(analise.total_empresas, 0)
        self.assertGreater(analise.capital_social_medio, 0)
        self.assertIsInstance(analise.top_5_bairros_concorrencia, list)

    def test_08_get_biggest_companies_by_capital(self):
        maiores = get_biggest_companies_by_capital(query="solar", limit=5, offset=0)
        self.assertIsInstance(maiores, list)
        self.assertGreater(len(maiores), 0)

        # Valida ordenação decrescente de capital social
        capitais = [m.capital_social for m in maiores]
        self.assertEqual(capitais, sorted(capitais, reverse=True))

    def test_09_search_company_by_name(self):
        # Busca nominal com filtro de estado e município
        res = search_company_by_name(name="Solar", uf="PR", municipio="Curitiba", limit=5, offset=0)
        self.assertIsInstance(res, list)
        self.assertGreater(len(res), 0)
        for r in res:
            self.assertEqual(r.uf, "PR")
            self.assertEqual(r.municipio.lower(), "curitiba")
            self.assertTrue(
                "solar" in r.razao_social.lower() or 
                (r.nome_fantasia and "solar" in r.nome_fantasia.lower())
            )


if __name__ == "__main__":
    unittest.main()

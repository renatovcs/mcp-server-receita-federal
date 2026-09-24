"""
Suíte de testes de integração e validação das ferramentas MCP com DuckDB Singleton.
Valida dados consolidados de múltiplas regiões (PR e RJ).
"""

import unittest
from pathlib import Path
from src.config import settings
from src.database import db_manager
from src.tools import (
    get_provider_details,
    list_available_cities,
    search_providers_by_service,
)


class TestMCPTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Inicializa a conexão DuckDB Singleton em modo read-only para a suíte de testes."""
        test_db = settings.DUCKDB_PATH
        if not test_db.exists():
            raise FileNotFoundError(f"Banco de dados para teste não encontrado: {test_db}")
        db_manager.initialize(test_db)

    @classmethod
    def tearDownClass(cls):
        """Encerra a conexão ao fim da suíte."""
        db_manager.close()

    def test_01_list_available_cities(self):
        cities = list_available_cities()
        self.assertIsInstance(cities, list)
        self.assertGreater(len(cities), 0)
        
        city_names = [c["municipio"] for c in cities]
        self.assertIn("Rio de Janeiro", city_names)
        self.assertIn("Curitiba", city_names)

        # Filtro por UF
        rj_cities = list_available_cities(uf="RJ")
        for c in rj_cities:
            self.assertEqual(c["uf"], "RJ")

        pr_cities = list_available_cities(uf="PR")
        for c in pr_cities:
            self.assertEqual(c["uf"], "PR")

    def test_02_search_providers_by_service_pr(self):
        # Busca FTS por ar condicionado em Curitiba (PR)
        results = search_providers_by_service(
            query="ar condicionado",
            uf="PR",
            municipio="Curitiba",
            limit=5,
        )
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)
        self.assertLessEqual(len(results), 5)

        for provider in results:
            self.assertIn("cnpj", provider)
            self.assertIn("razao_social", provider)
            self.assertIn("fts_score", provider)
            self.assertEqual(provider["uf"], "PR")
            self.assertEqual(provider["municipio"].lower(), "curitiba")
            self.assertGreater(provider["fts_score"], 0)

    def test_03_search_providers_by_service_rj(self):
        # Busca FTS no Rio de Janeiro (RJ)
        results = search_providers_by_service(
            query="energia solar",
            uf="RJ",
            limit=5,
        )
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)
        self.assertLessEqual(len(results), 5)

        for provider in results:
            self.assertIn("cnpj", provider)
            self.assertEqual(provider["uf"], "RJ")
            self.assertGreater(provider["fts_score"], 0)

    def test_04_search_providers_unfiltered(self):
        # Busca sem filtros (deve retornar os melhores em score independente da UF)
        results = search_providers_by_service(
            query="refrigeracao",
            limit=4,
        )
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)
        self.assertLessEqual(len(results), 4)

    def test_05_get_provider_details_masked_and_unmasked(self):
        # 1. Pega um prestador válido da busca
        search_sample = search_providers_by_service(query="solar", limit=1)
        self.assertTrue(len(search_sample) > 0)
        original_cnpj = search_sample[0]["cnpj"]

        # 2. Busca usando o CNPJ formatado
        details = get_provider_details(original_cnpj)
        self.assertIsNotNone(details)
        self.assertEqual(details["cnpj"], original_cnpj)
        self.assertIn("capital_social", details)
        self.assertIn("natureza_juridica", details)
        self.assertIn("idade_anos", details)

        # 3. Busca usando apenas os dígitos numéricos (sem pontos/traço)
        raw_digits = original_cnpj.replace(".", "").replace("/", "").replace("-", "")
        details_unmasked = get_provider_details(raw_digits)
        self.assertIsNotNone(details_unmasked)
        self.assertEqual(details_unmasked["cnpj"], original_cnpj)

    def test_06_get_provider_details_nonexistent(self):
        details = get_provider_details("00.000.000/0000-00")
        self.assertIsNone(details)


if __name__ == "__main__":
    unittest.main()

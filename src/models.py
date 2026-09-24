"""
Modelos Pydantic para padronização de retorno e geração automática
de esquemas JSON para o Model Context Protocol (MCP).
"""

from typing import Optional
from pydantic import BaseModel, Field

class EmpresaResumo(BaseModel):
    """Resumo de uma empresa para listagem de busca."""
    cnpj: str = Field(..., description="CNPJ da empresa")
    razao_social: str = Field(..., description="Razão social oficial")
    nome_fantasia: Optional[str] = Field(None, description="Nome fantasia, se disponível")
    porte_empresa: Optional[str] = Field(None, description="Porte da empresa (ME, EPP, etc)")
    data_inicio_atividade: Optional[str] = Field(None, description="Data de início (YYYY-MM-DD)")
    idade_anos: Optional[float] = Field(None, description="Idade da empresa em anos")
    cnae_fiscal_principal: Optional[str] = Field(None, description="Código CNAE principal")
    descricao_cnae_principal: Optional[str] = Field(None, description="Descrição da atividade principal")
    logradouro: Optional[str] = None
    numero: Optional[str] = None
    complemento: Optional[str] = None
    bairro: Optional[str] = None
    cep: Optional[str] = None
    municipio: Optional[str] = None
    uf: Optional[str] = None
    telefone_1: Optional[str] = None
    email: Optional[str] = None
    fts_score: Optional[float] = Field(None, description="Score de relevância da busca FTS BM25")

class EmpresaDetalhe(BaseModel):
    """Ficha cadastral completa de uma empresa."""
    cnpj: str = Field(..., description="CNPJ da empresa")
    cnpj_basico: Optional[str] = None
    razao_social: str = Field(..., description="Razão social oficial")
    nome_fantasia: Optional[str] = Field(None, description="Nome fantasia, se disponível")
    matriz_filial: Optional[int] = Field(None, description="1 para Matriz, 2 para Filial")
    porte_empresa: Optional[str] = None
    capital_social: Optional[float] = Field(None, description="Capital social da empresa")
    codigo_natureza_juridica: Optional[str] = None
    natureza_juridica: Optional[str] = None
    data_inicio_atividade: Optional[str] = None
    idade_anos: Optional[float] = Field(None, description="Tempo de abertura em anos")
    cnae_fiscal_principal: Optional[str] = None
    descricao_cnae_principal: Optional[str] = None
    cnae_fiscal_secundaria: Optional[str] = Field(None, description="CNAEs secundários separados por vírgula")
    tipo_logradouro: Optional[str] = None
    logradouro: Optional[str] = None
    numero: Optional[str] = None
    complemento: Optional[str] = None
    bairro: Optional[str] = None
    cep: Optional[str] = None
    municipio: Optional[str] = None
    uf: Optional[str] = None
    endereco_completo: Optional[str] = Field(None, description="Endereço formatado e completo")
    telefone_1: Optional[str] = None
    telefone_2: Optional[str] = None
    email: Optional[str] = None

class BairroEstatistica(BaseModel):
    """Estatística de densidade por bairro."""
    bairro: str = Field(..., description="Nome do bairro")
    quantidade: int = Field(..., description="Número de empresas neste bairro")

class AnaliseMercado(BaseModel):
    """Relatório analítico sobre um segmento de mercado específico."""
    termo_buscado: str = Field(..., description="Segmento pesquisado (ex: energia solar)")
    uf: Optional[str] = Field(None, description="Estado analisado")
    municipio: Optional[str] = Field(None, description="Município analisado")
    total_empresas: int = Field(..., description="Total de empresas ativas encontradas no segmento")
    capital_social_medio: float = Field(..., description="Capital social médio no segmento")
    idade_media_anos: float = Field(..., description="Tempo de mercado médio (experiência) em anos")
    top_5_bairros_concorrencia: List[BairroEstatistica] = Field(..., description="Os 5 bairros com mais empresas deste segmento")

class MunicipioEstatistica(BaseModel):
    """Estatísticas consolidadas de empresas por município."""
    municipio: str = Field(..., description="Nome do município")
    uf: str = Field(..., description="Unidade Federativa / Estado")
    total_empresas: int = Field(..., description="Quantidade total de empresas ativas")

class EmpresaCapital(BaseModel):
    """Resumo de empresa focada em porte econômico (Capital Social)."""
    cnpj: str = Field(..., description="CNPJ da empresa")
    razao_social: str = Field(..., description="Razão social oficial")
    capital_social: float = Field(..., description="Capital social registrado")
    municipio: str = Field(..., description="Município sede")
    uf: str = Field(..., description="Estado sede")
    idade_anos: float = Field(..., description="Idade da empresa")
    descricao_cnae_principal: Optional[str] = Field(None, description="Atividade principal")
    porte_empresa: Optional[str] = Field(None, description="Porte (ME, EPP, etc)")

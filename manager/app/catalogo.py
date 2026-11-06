"""Catálogo estático usado pelo Manager para particionar os jobs.

Tabela 6588 do SIDRA/IBGE (LSPA - Levantamento Sistemático da Produção Agrícola):
"Série histórica da estimativa anual da área plantada, área colhida, produção
e rendimento médio dos produtos das lavouras".
"""

TABELA_LSPA = 6588
CLASSIFICACAO_PRODUTO = 48  # c48 = Produto das lavouras

# Variáveis da tabela 6588
VARIAVEIS = {
    109: "Área plantada (ha)",
    216: "Área colhida (ha)",
    35: "Produção (t)",
    36: "Rendimento médio (kg/ha)",
}

# Categorias da classificação c48 (subconjunto relevante para o agro brasileiro)
PRODUTOS = {
    39443: "Soja",
    39441: "Milho (1ª safra)",
    39442: "Milho (2ª safra)",
    39456: "Cana-de-açúcar",
    39429: "Algodão herbáceo",
    39432: "Arroz",
    39436: "Feijão (1ª safra)",
    39437: "Feijão (2ª safra)",
    39445: "Trigo",
    40527: "Café (total)",
    39467: "Mandioca",
    39463: "Laranja",
    39449: "Banana",
    39444: "Sorgo",
    39453: "Cacau",
    39470: "Tomate",
}

PRODUTOS_PADRAO = [39443, 39441, 39442, 39456, 39429, 39432, 39436, 39445, 40527, 39467]

# Partição geográfica: cada região vira uma tarefa independente por produto.
REGIOES = {
    "N": {"nome": "Norte", "ufs": {11: "RO", 12: "AC", 13: "AM", 14: "RR", 15: "PA", 16: "AP", 17: "TO"}},
    "NE": {"nome": "Nordeste", "ufs": {21: "MA", 22: "PI", 23: "CE", 24: "RN", 25: "PB", 26: "PE", 27: "AL", 28: "SE", 29: "BA"}},
    "SE": {"nome": "Sudeste", "ufs": {31: "MG", 32: "ES", 33: "RJ", 35: "SP"}},
    "S": {"nome": "Sul", "ufs": {41: "PR", 42: "SC", 43: "RS"}},
    "CO": {"nome": "Centro-Oeste", "ufs": {50: "MS", 51: "MT", 52: "GO", 53: "DF"}},
}

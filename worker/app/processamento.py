"""Processamento (CPU-bound) da resposta do SIDRA, executado em pool de threads no Worker.

Entrada: lista de linhas no formato da API /values do SIDRA (primeira linha = cabeçalho).
Saída: indicadores por UF para um produto/região.
"""

PRODUCAO, AREA_PLANTADA, AREA_COLHIDA, RENDIMENTO = "35", "109", "216", "36"


def valor_numerico(v: str) -> float | None:
    """O SIDRA usa símbolos especiais: '-' (zero absoluto), '..' / '...' (não se aplica /
    não disponível), 'X' (sigilo). Tratamos '-' como 0 e os demais como ausentes."""
    if v is None:
        return None
    v = v.strip()
    if v == "-":
        return 0.0
    try:
        return float(v)
    except ValueError:
        return None


def processar(linhas: list[dict], ufs: dict[str, str], regiao: str) -> dict:
    # uf -> periodo -> variavel -> valor
    dados: dict[str, dict[str, dict[str, float]]] = {}
    periodos: set[str] = set()
    for linha in linhas[1:]:  # linhas[0] é o cabeçalho descritivo
        valor = valor_numerico(linha.get("V"))
        if valor is None:
            continue
        uf, var, per = linha["D1C"], linha["D2C"], linha["D3C"]
        periodos.add(per)
        dados.setdefault(uf, {}).setdefault(per, {})[var] = valor

    if not periodos:
        return {"ufs": [], "serie_producao": {}, "periodo_atual": None, "periodo_base": None}

    ordenados = sorted(periodos)
    atual, base = ordenados[-1], ordenados[0]
    serie: dict[str, float] = {p: 0.0 for p in ordenados}
    resultado = []

    for cod_uf, por_periodo in dados.items():
        for p, vars_ in por_periodo.items():
            serie[p] += vars_.get(PRODUCAO, 0.0)
        ult = por_periodo.get(atual, {})
        ini = por_periodo.get(base, {})
        producao = ult.get(PRODUCAO, 0.0)
        plantada = ult.get(AREA_PLANTADA, 0.0)
        colhida = ult.get(AREA_COLHIDA, 0.0)
        producao_base = ini.get(PRODUCAO, 0.0)
        resultado.append({
            "cod_uf": cod_uf,
            "uf": ufs.get(cod_uf, cod_uf),
            "regiao": regiao,
            "producao_t": producao,
            "producao_base_t": producao_base,
            "area_plantada_ha": plantada,
            "area_colhida_ha": colhida,
            "rendimento_kg_ha": ult.get(RENDIMENTO) or (round(producao * 1000 / colhida, 1) if colhida else None),
            "perda_area_pct": round((plantada - colhida) / plantada * 100, 2) if plantada else None,
            "variacao_producao_pct": round((producao - producao_base) / producao_base * 100, 2) if producao_base else None,
        })

    resultado.sort(key=lambda u: u["producao_t"], reverse=True)
    return {"ufs": resultado, "serie_producao": serie, "periodo_atual": atual, "periodo_base": base}

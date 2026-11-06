"""Consolidação (fase *gather*) dos resultados parciais dos Workers.

Cada resultado parcial cobre um par (produto x região) e traz os indicadores por UF.
Aqui juntamos todas as regiões de um produto para obter a visão nacional e os
indicadores ligados ao tema Agronegócio/ESG.
"""

from collections import defaultdict


def _pct(novo: float, antigo: float) -> float | None:
    if not antigo:
        return None
    return round((novo - antigo) / antigo * 100, 2)


def agregar(parciais: list[dict]) -> dict:
    por_produto: dict[int, dict] = {}
    distribuicao: dict[str, dict] = defaultdict(lambda: {"tarefas": 0, "erros": 0, "ms_total": 0.0})
    erros = []

    for res in parciais:
        d = distribuicao[res.get("worker", "?")]
        d["tarefas"] += 1
        d["ms_total"] += res.get("metricas", {}).get("total_ms", 0)
        if res.get("erro"):
            d["erros"] += 1
            erros.append({"tarefa": res["task_id"], "worker": res.get("worker"), "erro": res["erro"]})
            continue

        prod = res["produto"]
        alvo = por_produto.setdefault(prod["id"], {
            "produto": prod,
            "ufs": [],
            "serie": defaultdict(float),
            "periodo_atual": None,
            "periodo_base": None,
        })
        alvo["ufs"].extend(res["ufs"])
        for periodo, valor in res.get("serie_producao", {}).items():
            alvo["serie"][periodo] += valor
        alvo["periodo_atual"] = max(filter(None, [alvo["periodo_atual"], res.get("periodo_atual")]), default=None)
        alvo["periodo_base"] = min(filter(None, [alvo["periodo_base"], res.get("periodo_base")]), default=None)

    produtos = []
    for alvo in por_produto.values():
        ufs = sorted(alvo["ufs"], key=lambda u: u["producao_t"], reverse=True)
        prod_t = sum(u["producao_t"] for u in ufs)
        prod_base = sum(u["producao_base_t"] for u in ufs)
        plantada = sum(u["area_plantada_ha"] for u in ufs)
        colhida = sum(u["area_colhida_ha"] for u in ufs)
        top3 = sum(u["producao_t"] for u in ufs[:3])
        produtos.append({
            "produto": alvo["produto"],
            "periodo_atual": alvo["periodo_atual"],
            "periodo_base": alvo["periodo_base"],
            "producao_t": prod_t,
            "area_plantada_ha": plantada,
            "area_colhida_ha": colhida,
            # Eficiência no uso da terra (kg/ha): mais produção sem abrir nova área
            "rendimento_kg_ha": round(prod_t * 1000 / colhida, 1) if colhida else None,
            # Área plantada que não foi colhida: proxy de perdas (clima, pragas)
            "perda_area_pct": round((plantada - colhida) / plantada * 100, 2) if plantada else None,
            "variacao_producao_pct": _pct(prod_t, prod_base),
            # Concentração geográfica: quanto da produção está nas 3 maiores UFs
            "concentracao_top3_pct": round(top3 / prod_t * 100, 1) if prod_t else None,
            "ufs": ufs,
            "serie": [{"periodo": p, "producao_t": v} for p, v in sorted(alvo["serie"].items())],
        })
    produtos.sort(key=lambda p: p["producao_t"], reverse=True)

    return {
        "produtos": produtos,
        "distribuicao": [
            {"worker": w, "tarefas": d["tarefas"], "erros": d["erros"],
             "ms_medio": round(d["ms_total"] / d["tarefas"], 1) if d["tarefas"] else 0}
            for w, d in sorted(distribuicao.items())
        ],
        "erros": erros,
    }

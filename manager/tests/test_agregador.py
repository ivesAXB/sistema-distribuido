from app.agregador import agregar


def parcial(task, worker, regiao, ufs, serie, ms=100.0):
    return {
        "task_id": task, "worker": worker, "produto": {"id": 1, "nome": "Soja"},
        "regiao": {"sigla": regiao}, "ufs": ufs, "serie_producao": serie,
        "periodo_atual": "202609", "periodo_base": "202509", "metricas": {"total_ms": ms},
    }


def uf(sigla, prod, base, plantada, colhida):
    return {"uf": sigla, "producao_t": prod, "producao_base_t": base,
            "area_plantada_ha": plantada, "area_colhida_ha": colhida}


def test_consolida_regioes_em_visao_nacional():
    r = agregar([
        parcial("1-S", "worker-1", "S", [uf("PR", 600, 500, 200, 200)], {"202509": 500, "202609": 600}),
        parcial("1-CO", "worker-2", "CO", [uf("MT", 1000, 1000, 300, 250), uf("GO", 400, 500, 100, 100)],
                {"202509": 1500, "202609": 1400}),
    ])
    p = r["produtos"][0]
    assert p["producao_t"] == 2000
    assert [u["uf"] for u in p["ufs"]] == ["MT", "PR", "GO"]
    assert p["variacao_producao_pct"] == 0.0           # 2000 vs 2000
    assert p["rendimento_kg_ha"] == round(2000 * 1000 / 550, 1)
    assert p["perda_area_pct"] == round(50 / 600 * 100, 2)
    assert p["concentracao_top3_pct"] == 100.0
    assert p["serie"] == [{"periodo": "202509", "producao_t": 2000}, {"periodo": "202609", "producao_t": 2000}]


def test_distribuicao_e_erros_por_worker():
    r = agregar([
        parcial("1-S", "worker-1", "S", [uf("PR", 10, 10, 1, 1)], {}, ms=200),
        {"task_id": "1-N", "worker": "worker-1", "erro": "HTTP 500", "metricas": {"total_ms": 0}},
        parcial("1-CO", "worker-2", "CO", [uf("MT", 10, 10, 1, 1)], {}, ms=100),
    ])
    dist = {d["worker"]: d for d in r["distribuicao"]}
    assert dist["worker-1"]["tarefas"] == 2 and dist["worker-1"]["erros"] == 1
    assert dist["worker-2"]["ms_medio"] == 100
    assert r["erros"] == [{"tarefa": "1-N", "worker": "worker-1", "erro": "HTTP 500"}]


def test_sem_resultados():
    assert agregar([]) == {"produtos": [], "distribuicao": [], "erros": []}

from app.processamento import processar, valor_numerico

CAB = {"V": "Valor", "D1C": "UF", "D2C": "Var", "D3C": "Mes"}


def linha(uf, var, mes, v):
    return {"V": v, "D1C": uf, "D2C": var, "D3C": mes}


def test_valores_especiais_do_sidra():
    assert valor_numerico("-") == 0.0
    assert valor_numerico("...") is None
    assert valor_numerico("X") is None
    assert valor_numerico("123") == 123.0


def test_indicadores_por_uf():
    linhas = [CAB,
              linha("41", "35", "202509", "1000"), linha("41", "35", "202609", "1200"),
              linha("41", "109", "202609", "500"), linha("41", "216", "202609", "400"),
              linha("41", "36", "202609", "3000"),
              linha("43", "35", "202609", "-")]
    r = processar(linhas, {"41": "PR", "43": "RS"}, "S")
    assert r["periodo_atual"] == "202609" and r["periodo_base"] == "202509"
    pr = r["ufs"][0]
    assert pr["uf"] == "PR"
    assert pr["variacao_producao_pct"] == 20.0
    assert pr["perda_area_pct"] == 20.0
    assert pr["rendimento_kg_ha"] == 3000
    assert r["serie_producao"] == {"202509": 1000.0, "202609": 1200.0}


def test_sem_dados():
    assert processar([CAB], {}, "N")["ufs"] == []

"""Testa o Manager de ponta a ponta com um Redis em memória (fakeredis)."""
import json

import fakeredis
import pytest
import redis.asyncio as aioredis
from fastapi.testclient import TestClient

from comum import chaves as K


@pytest.fixture
def cliente(monkeypatch):
    servidor = fakeredis.FakeServer()
    monkeypatch.setattr(aioredis, "from_url",
                        lambda *a, **k: fakeredis.FakeAsyncRedis(server=servidor, decode_responses=True))
    from app.main import app
    with TestClient(app) as c:
        yield c, fakeredis.FakeRedis(server=servidor, decode_responses=True)


def test_job_e_particionado_em_produto_x_regiao(cliente):
    c, r = cliente
    resp = c.post("/api/jobs", json={"produtos": [39443, 39445], "regioes": ["S", "CO"], "periodos": 13})
    assert resp.status_code == 201
    assert resp.json()["tarefas"] == 4
    tarefas = [json.loads(t) for t in r.lrange(K.FILA_TAREFAS, 0, -1)]
    assert sorted(t["task_id"] for t in tarefas) == ["39443-CO", "39443-S", "39445-CO", "39445-S"]
    sul = next(t for t in tarefas if t["task_id"] == "39443-S")
    assert set(sul["ufs"].values()) == {"PR", "SC", "RS"}


def test_pedido_invalido(cliente):
    c, _ = cliente
    assert c.post("/api/jobs", json={"produtos": [999]}).status_code == 400


def test_resultado_duplicado_conta_uma_vez(cliente):
    import asyncio
    from app.main import registrar_resultado

    c, r = cliente
    job = c.post("/api/jobs", json={"produtos": [39443], "regioes": ["S"]}).json()["job_id"]
    res = {"job_id": job, "task_id": "39443-S", "worker": "w1", "produto": {"id": 39443, "nome": "Soja"},
           "regiao": {"sigla": "S"}, "ufs": [], "serie_producao": {}}
    fake_async = aioredis.from_url("")
    asyncio.run(registrar_resultado(fake_async, res))
    asyncio.run(registrar_resultado(fake_async, res))  # reprocessamento (at-least-once)
    status = c.get(f"/api/jobs/{job}").json()
    assert status["concluidas"] == 1 and status["status"] == "concluido"

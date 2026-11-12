import asyncio

import httpx
import pytest

from app import sidra
from app.sidra import ErroSidra, consultar, montar_url

TAREFA = {
    "tabela": 6588, "classificacao": 48, "produto": {"id": 39443},
    "ufs": {"41": "PR", "42": "SC", "43": "RS"}, "variaveis": [109, 216, 35, 36], "periodos": 13,
}


def test_monta_endpoint_do_sidra():
    assert montar_url(TAREFA) == (
        "https://apisidra.ibge.gov.br/values/t/6588/n3/41,42,43/v/109,216,35,36"
        "/p/last%2013/c48/39443?formato=json"
    )


def _rodar(respostas, monkeypatch):
    monkeypatch.setattr(sidra.asyncio, "sleep", _sem_espera)
    chamadas = []

    def handler(req):
        chamadas.append(req)
        status, corpo = respostas[len(chamadas) - 1]
        return httpx.Response(status, json=corpo)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as cli:
            return await consultar(cli, asyncio.Semaphore(1), "http://x/values")

    return asyncio.run(go()), chamadas


async def _sem_espera(_):
    return None


def test_repete_em_erro_temporario(monkeypatch):
    dados, chamadas = _rodar([(503, {}), (429, {}), (200, [{"V": "Valor"}])], monkeypatch)
    assert dados == [{"V": "Valor"}]
    assert len(chamadas) == 3


def test_nao_repete_em_parametro_invalido(monkeypatch):
    with pytest.raises(ErroSidra):
        _rodar([(400, "Tabela inexistente")], monkeypatch)


def test_desiste_apos_tentativas(monkeypatch):
    with pytest.raises(ErroSidra, match="indisponível"):
        _rodar([(500, {})] * 4, monkeypatch)

"""Cliente assíncrono da API SIDRA/IBGE (https://apisidra.ibge.gov.br)."""

import asyncio
import logging
import os
import random

import httpx

SIDRA_BASE = os.getenv("SIDRA_BASE", "https://apisidra.ibge.gov.br")
log = logging.getLogger("worker.sidra")


def montar_url(tarefa: dict) -> str:
    """Monta o endpoint /values conforme a documentação do SIDRA:
    /t/{tabela}/n3/{UFs}/v/{variáveis}/p/last {N}/c{classificação}/{categoria}
    n3 = nível territorial Unidade da Federação.
    """
    ufs = ",".join(tarefa["ufs"].keys())
    variaveis = ",".join(str(v) for v in tarefa["variaveis"])
    return (
        f"{SIDRA_BASE}/values/t/{tarefa['tabela']}/n3/{ufs}/v/{variaveis}"
        f"/p/last%20{tarefa['periodos']}/c{tarefa['classificacao']}/{tarefa['produto']['id']}"
        "?formato=json"
    )


class ErroSidra(Exception):
    pass


async def consultar(cliente: httpx.AsyncClient, limite: asyncio.Semaphore, url: str,
                    tentativas: int = 4) -> list[dict]:
    """GET com limite de concorrência (semáforo) e retentativa com backoff exponencial + jitter."""
    ultimo_erro = None
    for n in range(tentativas):
        try:
            async with limite:
                resp = await cliente.get(url)
            if resp.status_code == 200:
                dados = resp.json()
                if isinstance(dados, list):
                    return dados
                raise ErroSidra(f"resposta inesperada: {str(dados)[:120]}")
            if resp.status_code in (429, 500, 502, 503, 504):
                ultimo_erro = f"HTTP {resp.status_code}"
            else:
                # 400 do SIDRA = parâmetros inválidos; não adianta repetir
                raise ErroSidra(f"HTTP {resp.status_code}: {resp.text[:120]}")
        except (httpx.TransportError, ValueError) as e:
            ultimo_erro = f"{type(e).__name__}: {e}"
        espera = (2 ** n) * 0.5 + random.random() * 0.5
        log.warning("Falha ao consultar SIDRA (%s). Nova tentativa em %.1fs", ultimo_erro, espera)
        await asyncio.sleep(espera)
    raise ErroSidra(f"SIDRA indisponível após {tentativas} tentativas: {ultimo_erro}")

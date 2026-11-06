"""Nó MANAGER (coordenador) do ecossistema Safra Distribuída.

Responsabilidades:
  * Receber pedidos de análise (jobs) via API REST.
  * Particionar cada job em tarefas independentes (produto x região) e publicá-las
    na fila distribuída (Redis).
  * Coletar os resultados enviados pelos Workers e consolidá-los.
  * Monitorar a saúde dos Workers (heartbeat) e reenfileirar tarefas de nós que caíram.
  * Servir o painel web (dashboard).

Todo o Manager roda em um único event loop asyncio: a API, o coletor de resultados
e o vigia de falhas são corrotinas concorrentes.
"""

import asyncio
import json
import logging
import os
import socket
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from comum import chaves as K
from .agregador import agregar
from .catalogo import (
    CLASSIFICACAO_PRODUTO,
    PRODUTOS,
    PRODUTOS_PADRAO,
    REGIOES,
    TABELA_LSPA,
    VARIAVEIS,
)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
MAX_TENTATIVAS = int(os.getenv("MAX_TENTATIVAS", "3"))
INTERVALO_VIGIA = float(os.getenv("INTERVALO_VIGIA", "3"))
MANAGER_ID = os.getenv("NODE_ID", socket.gethostname())

logging.basicConfig(level=logging.INFO, format="%(asctime)s [MANAGER] %(levelname)s %(message)s")
log = logging.getLogger("manager")

STATIC = Path(__file__).parent / "static"


class PedidoJob(BaseModel):
    produtos: list[int] = Field(default_factory=lambda: list(PRODUTOS_PADRAO))
    regioes: list[str] = Field(default_factory=lambda: list(REGIOES.keys()))
    periodos: int = Field(13, ge=2, le=60, description="Quantidade de meses (estimativas) mais recentes")


# ---------------------------------------------------------------------------
# Corrotinas de fundo
# ---------------------------------------------------------------------------

async def coletor_resultados(r: aioredis.Redis) -> None:
    """Consome a fila de resultados publicada pelos Workers."""
    log.info("Coletor de resultados iniciado")
    while True:
        try:
            item = await r.blpop(K.FILA_RESULTADOS, timeout=5)
            if not item:
                continue
            res = json.loads(item[1])
            await registrar_resultado(r, res)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("Erro no coletor")
            await asyncio.sleep(1)


async def registrar_resultado(r: aioredis.Redis, res: dict) -> None:
    job_id, task_id = res["job_id"], res["task_id"]
    chave_job = K.job(job_id)
    # Idempotência: se a tarefa foi reprocessada (ex.: worker lento + reenfileirada), conta 1x.
    novo = await r.hsetnx(K.resultados(job_id), task_id, json.dumps(res))
    if not novo:
        return
    campo = "falhas" if res.get("erro") else "concluidas"
    await r.hincrby(chave_job, campo, 1)
    job = await r.hgetall(chave_job)
    feitas = int(job.get("concluidas", 0)) + int(job.get("falhas", 0))
    if feitas >= int(job.get("total", 0)) and job.get("status") != "concluido":
        await r.hset(chave_job, mapping={"status": "concluido", "fim": time.time()})
        log.info("Job %s concluído (%s tarefas)", job_id, feitas)
    elif job.get("status") == "na_fila":
        await r.hset(chave_job, "status", "processando")


async def vigia_workers(r: aioredis.Redis) -> None:
    """Detecta Workers sem heartbeat e devolve suas tarefas para a fila (tolerância a falhas)."""
    log.info("Vigia de workers iniciado")
    while True:
        try:
            await asyncio.sleep(INTERVALO_VIGIA)
            for wid in await r.smembers(K.WORKERS):
                if await r.exists(K.heartbeat(wid)):
                    continue
                recuperadas = 0
                while True:
                    bruto = await r.rpop(K.processando(wid))
                    if bruto is None:
                        break
                    tarefa = json.loads(bruto)
                    tarefa["tentativas"] = tarefa.get("tentativas", 0) + 1
                    if tarefa["tentativas"] >= MAX_TENTATIVAS:
                        await r.rpush(K.FILA_RESULTADOS, json.dumps({
                            "job_id": tarefa["job_id"], "task_id": tarefa["task_id"],
                            "worker": wid, "erro": "excedeu tentativas após queda de workers",
                            "produto": tarefa["produto"], "regiao": tarefa["regiao"],
                        }))
                    else:
                        # Volta para a FRENTE da fila: prioridade para tarefas resgatadas
                        await r.rpush(K.FILA_TAREFAS, json.dumps(tarefa))
                    recuperadas += 1
                await r.srem(K.WORKERS, wid)
                await r.hset(K.worker(wid), "status", "offline")
                log.warning("Worker %s sem heartbeat: removido, %d tarefa(s) reenfileirada(s)", wid, recuperadas)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("Erro no vigia")


# ---------------------------------------------------------------------------
# Aplicação
# ---------------------------------------------------------------------------

@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    for tentativa in range(30):
        try:
            await r.ping()
            break
        except Exception:  # noqa: BLE001
            log.info("Aguardando Redis (%d)...", tentativa + 1)
            await asyncio.sleep(1)
    await r.hset(K.MANAGER, mapping={"id": MANAGER_ID, "inicio": time.time()})
    app.state.redis = r
    tarefas = [asyncio.create_task(coletor_resultados(r)), asyncio.create_task(vigia_workers(r))]
    log.info("Manager %s pronto", MANAGER_ID)
    yield
    for t in tarefas:
        t.cancel()
    await r.aclose()


app = FastAPI(title="Safra Distribuída - Manager", version="1.0.0", lifespan=ciclo_de_vida)


def redis_() -> aioredis.Redis:
    return app.state.redis


@app.get("/", include_in_schema=False)
async def painel():
    return FileResponse(STATIC / "index.html")


@app.get("/api/saude")
async def saude():
    await redis_().ping()
    return {"status": "ok", "papel": "manager", "id": MANAGER_ID}


@app.get("/api/catalogo")
async def catalogo():
    return {
        "tabela": TABELA_LSPA,
        "variaveis": VARIAVEIS,
        "produtos": [{"id": k, "nome": v, "padrao": k in PRODUTOS_PADRAO} for k, v in PRODUTOS.items()],
        "regioes": [{"sigla": k, "nome": v["nome"], "ufs": list(v["ufs"].values())} for k, v in REGIOES.items()],
    }


@app.post("/api/jobs", status_code=201)
async def criar_job(pedido: PedidoJob):
    produtos = [p for p in pedido.produtos if p in PRODUTOS]
    regioes = [g for g in pedido.regioes if g in REGIOES]
    if not produtos or not regioes:
        raise HTTPException(400, "Informe ao menos um produto e uma região válidos")

    r = redis_()
    job_id = uuid.uuid4().hex[:8]
    tarefas = []
    # Particionamento (scatter): uma tarefa por (produto x região)
    for p in produtos:
        for g in regioes:
            tarefas.append({
                "task_id": f"{p}-{g}",
                "job_id": job_id,
                "tabela": TABELA_LSPA,
                "classificacao": CLASSIFICACAO_PRODUTO,
                "produto": {"id": p, "nome": PRODUTOS[p]},
                "regiao": {"sigla": g, "nome": REGIOES[g]["nome"]},
                "ufs": {str(k): v for k, v in REGIOES[g]["ufs"].items()},
                "variaveis": list(VARIAVEIS.keys()),
                "periodos": pedido.periodos,
                "tentativas": 0,
            })

    await r.hset(K.job(job_id), mapping={
        "id": job_id,
        "status": "na_fila",
        "total": len(tarefas),
        "concluidas": 0,
        "falhas": 0,
        "inicio": time.time(),
        "parametros": json.dumps(pedido.model_dump()),
    })
    await r.lpush(K.JOBS, job_id)
    await r.lpush(K.FILA_TAREFAS, *[json.dumps(t) for t in tarefas])
    log.info("Job %s criado: %d tarefas publicadas", job_id, len(tarefas))
    return {"job_id": job_id, "tarefas": len(tarefas)}


@app.get("/api/jobs")
async def listar_jobs():
    r = redis_()
    ids = await r.lrange(K.JOBS, 0, 19)
    return [await _resumo_job(r, j) for j in ids]


async def _resumo_job(r: aioredis.Redis, job_id: str) -> dict:
    job = await r.hgetall(K.job(job_id))
    if not job:
        raise HTTPException(404, "Job não encontrado")
    fim = float(job["fim"]) if job.get("fim") else time.time()
    return {
        "id": job_id,
        "status": job["status"],
        "total": int(job["total"]),
        "concluidas": int(job["concluidas"]),
        "falhas": int(job["falhas"]),
        "duracao_s": round(fim - float(job["inicio"]), 2),
        "parametros": json.loads(job["parametros"]),
    }


@app.get("/api/jobs/{job_id}")
async def status_job(job_id: str):
    return await _resumo_job(redis_(), job_id)


@app.get("/api/jobs/{job_id}/resultado")
async def resultado_job(job_id: str):
    """Fase gather: consolida os resultados parciais devolvidos pelos Workers."""
    r = redis_()
    resumo = await _resumo_job(r, job_id)
    brutos = await r.hvals(K.resultados(job_id))
    parciais = [json.loads(b) for b in brutos]
    # A consolidação é CPU-bound: roda em thread para não travar o event loop.
    consolidado = await asyncio.to_thread(agregar, parciais)
    return {"job": resumo, **consolidado}


@app.get("/api/cluster")
async def cluster():
    r = redis_()
    ids = await r.smembers(K.WORKERS)
    conhecidos = set(ids)
    # Inclui workers que já caíram (status offline) para o painel mostrar a falha
    async for chave in r.scan_iter(match=K.worker("*")):
        conhecidos.add(chave.split(":")[-1])
    workers = []
    for wid in sorted(conhecidos):
        info = await r.hgetall(K.worker(wid))
        vivo = bool(await r.exists(K.heartbeat(wid)))
        workers.append({
            "id": wid,
            "status": "online" if vivo else "offline",
            "host": info.get("host"),
            "concorrencia": int(info.get("concorrencia", 0)),
            "threads": int(info.get("threads", 0)),
            "em_execucao": int(info.get("em_execucao", 0)) if vivo else 0,
            "tarefas_ok": int(info.get("tarefas_ok", 0)),
            "tarefas_erro": int(info.get("tarefas_erro", 0)),
            "processando": await r.llen(K.processando(wid)),
        })
    manager = await r.hgetall(K.MANAGER)
    return {
        "manager": {"id": manager.get("id"), "papel": "coordenador"},
        "fila_pendente": await r.llen(K.FILA_TAREFAS),
        "workers": workers,
    }

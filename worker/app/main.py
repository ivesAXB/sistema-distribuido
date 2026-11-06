"""Nó WORKER (processamento) do ecossistema Safra Distribuída.

Paralelismo em dois níveis:
  1. Entre nós: vários containers Worker consomem a mesma fila no Redis.
  2. Dentro do nó:
     - CONCORRENCIA corrotinas asyncio consomem tarefas simultaneamente e fazem
       as requisições HTTP ao SIDRA de forma não bloqueante (I/O assíncrono);
     - o processamento dos dados (parse + indicadores) roda em um
       ThreadPoolExecutor com THREADS threads, mantendo o event loop livre.

Confiabilidade: cada tarefa é movida atomicamente (BLMOVE) da fila global para a
lista "processando:<worker>". Se o worker morrer, o Manager detecta a ausência
de heartbeat e devolve essas tarefas para a fila.
"""

import asyncio
import json
import logging
import os
import signal
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import redis.asyncio as aioredis

from comum import chaves as K

from .processamento import processar
from .sidra import consultar, montar_url

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
WORKER_ID = os.getenv("NODE_ID") or socket.gethostname()
CONCORRENCIA = int(os.getenv("CONCORRENCIA", "4"))
THREADS = int(os.getenv("THREADS", "4"))
MAX_HTTP = int(os.getenv("MAX_HTTP", "3"))
HEARTBEAT_TTL = int(os.getenv("HEARTBEAT_TTL", "10"))
ATRASO_ARTIFICIAL = float(os.getenv("ATRASO_ARTIFICIAL", "0"))  # para demonstrar falhas no pitch

logging.basicConfig(level=logging.INFO, format=f"%(asctime)s [WORKER {WORKER_ID}] %(levelname)s %(message)s")
log = logging.getLogger("worker")
logging.getLogger("httpx").setLevel(logging.WARNING)


class Worker:
    def __init__(self) -> None:
        self.redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        self.pool = ThreadPoolExecutor(max_workers=THREADS, thread_name_prefix="proc")
        self.limite_http = asyncio.Semaphore(MAX_HTTP)
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(60.0), headers={"User-Agent": "safra-distribuida/1.0"})
        self.parar = asyncio.Event()
        self.em_execucao = 0

    async def registrar(self) -> None:
        for tentativa in range(30):
            try:
                await self.redis.ping()
                break
            except Exception:  # noqa: BLE001
                log.info("Aguardando Redis (%d)...", tentativa + 1)
                await asyncio.sleep(1)
        await self.redis.sadd(K.WORKERS, WORKER_ID)
        await self.redis.hset(K.worker(WORKER_ID), mapping={
            "host": socket.gethostname(),
            "concorrencia": CONCORRENCIA,
            "threads": THREADS,
            "status": "online",
            "inicio": time.time(),
            "em_execucao": 0,
        })
        await self.redis.set(K.heartbeat(WORKER_ID), "1", ex=HEARTBEAT_TTL)
        log.info("Registrado no cluster: %d corrotinas, %d threads, %d conexões HTTP",
                 CONCORRENCIA, THREADS, MAX_HTTP)

    async def heartbeat(self) -> None:
        while not self.parar.is_set():
            await self.redis.set(K.heartbeat(WORKER_ID), "1", ex=HEARTBEAT_TTL)
            # Se o Manager nos removeu (ex.: pausa longa), nos re-registramos
            await self.redis.sadd(K.WORKERS, WORKER_ID)
            await self.redis.hset(K.worker(WORKER_ID), mapping={"status": "online", "em_execucao": self.em_execucao})
            try:
                await asyncio.wait_for(self.parar.wait(), timeout=HEARTBEAT_TTL / 3)
            except asyncio.TimeoutError:
                pass

    async def consumidor(self, n: int) -> None:
        # Cada consumidor usa conexão própria, pois BLMOVE bloqueia a conexão.
        conn = aioredis.from_url(REDIS_URL, decode_responses=True)
        fila_local = K.processando(WORKER_ID)
        while not self.parar.is_set():
            try:
                bruto = await conn.blmove(K.FILA_TAREFAS, fila_local, timeout=2, src="RIGHT", dest="LEFT")
            except Exception:  # noqa: BLE001
                log.exception("Erro ao ler fila")
                await asyncio.sleep(1)
                continue
            if bruto is None:
                continue
            self.em_execucao += 1
            try:
                await self.executar(json.loads(bruto), n)
            finally:
                self.em_execucao -= 1
                await conn.lrem(fila_local, 1, bruto)  # ack: remove o lease
        await conn.aclose()

    async def executar(self, tarefa: dict, n: int) -> None:
        inicio = time.perf_counter()
        base = {
            "job_id": tarefa["job_id"], "task_id": tarefa["task_id"], "worker": WORKER_ID,
            "produto": tarefa["produto"], "regiao": tarefa["regiao"],
        }
        try:
            url = montar_url(tarefa)
            linhas = await consultar(self.http, self.limite_http, url)
            t_http = time.perf_counter()
            if ATRASO_ARTIFICIAL:
                await asyncio.sleep(ATRASO_ARTIFICIAL)
            loop = asyncio.get_running_loop()
            dados = await loop.run_in_executor(
                self.pool, self._processar_em_thread, linhas, tarefa["ufs"], tarefa["regiao"]["sigla"])
            fim = time.perf_counter()
            thread = dados.pop("_thread")
            resultado = {**base, **dados, "metricas": {
                "http_ms": round((t_http - inicio) * 1000, 1),
                "proc_ms": round((fim - t_http) * 1000, 1),
                "total_ms": round((fim - inicio) * 1000, 1),
                "corrotina": n,
                "thread": thread,
            }}
            await self.redis.hincrby(K.worker(WORKER_ID), "tarefas_ok", 1)
            log.info("Tarefa %s/%s ok em %.0f ms (corrotina %d, %s)", tarefa["job_id"], tarefa["task_id"],
                     resultado["metricas"]["total_ms"], n, resultado["metricas"]["thread"])
        except Exception as e:  # noqa: BLE001  (inclui ErroSidra)
            resultado = {**base, "erro": str(e),
                         "metricas": {"total_ms": round((time.perf_counter() - inicio) * 1000, 1)}}
            await self.redis.hincrby(K.worker(WORKER_ID), "tarefas_erro", 1)
            log.error("Tarefa %s falhou: %s", tarefa["task_id"], e)
        await self.redis.rpush(K.FILA_RESULTADOS, json.dumps(resultado))

    @staticmethod
    def _processar_em_thread(linhas, ufs, regiao) -> dict:
        dados = processar(linhas, ufs, regiao)
        dados["_thread"] = threading.current_thread().name
        return dados

    async def rodar(self) -> None:
        await self.registrar()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self.parar.set)
            except NotImplementedError:  # Windows (execução local)
                pass
        await asyncio.gather(self.heartbeat(), *[self.consumidor(i) for i in range(CONCORRENCIA)])
        # Desligamento gracioso: sai do cluster sem esperar o vigia do Manager
        await self.redis.srem(K.WORKERS, WORKER_ID)
        await self.redis.hset(K.worker(WORKER_ID), "status", "offline")
        await self.redis.delete(K.heartbeat(WORKER_ID))
        await self.http.aclose()
        self.pool.shutdown()
        log.info("Worker encerrado")


if __name__ == "__main__":
    asyncio.run(Worker().rodar())

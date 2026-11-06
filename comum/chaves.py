"""Convenção de chaves no Redis (contrato compartilhado entre Manager e Workers)."""

FILA_TAREFAS = "safra:fila:tarefas"        # LIST  - tarefas pendentes (Manager -> Workers)
FILA_RESULTADOS = "safra:fila:resultados"  # LIST  - resultados parciais (Workers -> Manager)
WORKERS = "safra:workers"                  # SET   - workers ativos
JOBS = "safra:jobs"                        # LIST  - histórico de jobs
MANAGER = "safra:manager"                  # HASH  - dados do coordenador


def job(job_id: str) -> str:               # HASH  - status do job
    return f"safra:job:{job_id}"


def resultados(job_id: str) -> str:        # HASH  - task_id -> resultado parcial
    return f"safra:job:{job_id}:resultados"


def processando(worker_id: str) -> str:    # LIST  - tarefas em execução no worker (lease)
    return f"safra:processando:{worker_id}"


def heartbeat(worker_id: str) -> str:      # STRING com TTL - sinal de vida
    return f"safra:heartbeat:{worker_id}"


def worker(worker_id: str) -> str:         # HASH  - metadados/estatísticas do worker
    return f"safra:worker:{worker_id}"

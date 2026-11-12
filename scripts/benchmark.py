"""Benchmark do ecossistema: mede o tempo de um job conforme o número de Workers online.

Uso (com o cluster no ar via Docker Compose):

    # mede o cluster como está agora
    python scripts/benchmark.py --repeticoes 3

    # varia automaticamente 1, 2 e 3 workers (usa docker compose stop/start)
    python scripts/benchmark.py --docker --repeticoes 3

Só depende da biblioteca padrão do Python.
"""

import argparse
import json
import statistics
import subprocess
import time
import urllib.request

WORKERS_COMPOSE = ["worker-1", "worker-2", "worker-3"]


def _req(api: str, caminho: str, corpo: dict | None = None) -> dict:
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(api + caminho, data=dados, method="POST" if dados else "GET",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def workers_online(api: str) -> int:
    return sum(w["status"] == "online" for w in _req(api, "/api/cluster")["workers"])


def medir_job(api: str, pedido: dict, limite_s: float = 300) -> dict:
    """Dispara um job e espera terminar. Retorna duração, tarefas e distribuição por worker."""
    job = _req(api, "/api/jobs", pedido)["job_id"]
    inicio = time.time()
    while time.time() - inicio < limite_s:
        st = _req(api, f"/api/jobs/{job}")
        if st["status"] == "concluido":
            res = _req(api, f"/api/jobs/{job}/resultado")
            return {
                "job": job,
                "duracao_s": st["duracao_s"],
                "tarefas": st["total"],
                "falhas": st["falhas"],
                "por_worker": {d["worker"]: d["tarefas"] for d in res["distribuicao"]},
            }
        time.sleep(0.2)
    raise TimeoutError(f"job {job} não terminou em {limite_s}s")


def medir_cenario(api: str, pedido: dict, repeticoes: int) -> dict:
    medidas = [medir_job(api, pedido) for _ in range(repeticoes)]
    tempos = [m["duracao_s"] for m in medidas]
    return {
        "workers": workers_online(api),
        "tempos_s": tempos,
        "mediana_s": round(statistics.median(tempos), 2),
        "tarefas": medidas[-1]["tarefas"],
        "falhas": sum(m["falhas"] for m in medidas),
        "por_worker": medidas[-1]["por_worker"],
    }


def _compose(*args: str) -> None:
    subprocess.run(["docker", "compose", *args], check=True, capture_output=True)


def ajustar_workers_docker(api: str, n: int) -> None:
    ligar, desligar = WORKERS_COMPOSE[:n], WORKERS_COMPOSE[n:]
    if desligar:
        _compose("stop", *desligar)
    _compose("start", *ligar)
    # espera o vigia do Manager refletir o novo tamanho do cluster
    for _ in range(60):
        if workers_online(api) == n:
            return
        time.sleep(1)
    raise RuntimeError(f"cluster não chegou a {n} workers online")


def tabela_markdown(cenarios: list[dict]) -> str:
    base = cenarios[0]["mediana_s"]
    linhas = ["| Workers | Tarefas | Tempo (mediana) | Speedup | Tarefas por worker |",
              "|---|---|---|---|---|"]
    for c in cenarios:
        dist = ", ".join(f"{w}: {t}" for w, t in sorted(c["por_worker"].items()))
        linhas.append(f"| {c['workers']} | {c['tarefas']} | {c['mediana_s']} s | "
                      f"{base / c['mediana_s']:.2f}x | {dist} |")
    return "\n".join(linhas)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--repeticoes", type=int, default=3)
    ap.add_argument("--periodos", type=int, default=13)
    ap.add_argument("--docker", action="store_true", help="varia 1..3 workers com docker compose")
    args = ap.parse_args()

    pedido = {"periodos": args.periodos}  # produtos e regiões padrão: 50 tarefas
    medir_job(args.api, pedido)  # aquecimento (conexões e cache do SIDRA)

    cenarios = []
    for n in (range(1, len(WORKERS_COMPOSE) + 1) if args.docker else [None]):
        if n:
            ajustar_workers_docker(args.api, n)
        c = medir_cenario(args.api, pedido, args.repeticoes)
        print(f"{c['workers']} worker(s): {c['tempos_s']} -> mediana {c['mediana_s']} s", flush=True)
        cenarios.append(c)

    print()
    print(tabela_markdown(cenarios))


if __name__ == "__main__":
    main()

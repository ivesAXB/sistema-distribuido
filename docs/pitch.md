# Roteiro do Pitch (máx. 10 min)

| Tempo | Bloco | Conteúdo | Quem |
|---|---|---|---|
| 0:00–1:00 | **Problema e tema** | O agro responde por cerca de ¼ do PIB brasileiro. A LSPA/IBGE publica todo mês a estimativa da safra por UF e por cultura. Pergunta: *onde estamos produzindo mais por hectare, onde estamos perdendo área e como a safra evolui?* | |
| 1:00–2:00 | **Dados (SIDRA)** | Tabela 6588, variáveis 109/216/35/36, classificação c48 (produto), nível n3 (UF). Mostrar a URL real do endpoint. | |
| 2:00–4:30 | **Arquitetura** | Diagrama de implantação: Manager, Redis, Workers. Scatter-gather: 1 job vira 50 tarefas (produto × região). Fila *pull* com balanceamento natural. Justificar Redis (BLMOVE atômico, *lease*) e FastAPI/asyncio. | |
| 4:30–5:30 | **Paralelismo interno** | Diagrama 8: corrotinas asyncio para I/O, semáforo limitando o SIDRA, ThreadPoolExecutor para CPU. Mostrar nos logs: `corrotina N, proc_M`. | |
| 5:30–8:00 | **Demo ao vivo** | `docker compose ps` (nós explícitos) → painel → disparar job → gráfico de distribuição por Worker → aba Soja (MT/PR/GO) → **`docker kill safra-worker-2`** durante um job → painel mostra offline e o job termina mesmo assim. | |
| 8:00–9:15 | **Leitura ESG/Agro** | Rendimento (kg/ha) = eficiência no uso da terra, menos pressão por desmatamento. Área não colhida = risco climático. Concentração top-3 = dependência regional. | |
| 9:15–10:00 | **Fechamento** | Escalabilidade (`docker service scale` no Swarm), limitações e próximos passos (PIM-PF para cruzar com a agroindústria, persistência histórica). | |

## Checklist antes de apresentar

- [ ] `docker compose up --build -d` já executado (a primeira build demora)
- [ ] Painel aberto em http://localhost:8000 e um job já rodado (cache aquecido)
- [ ] Terminal com `docker compose logs -f worker-1 worker-2 worker-3` visível
- [ ] Para a demo de falha ser bem visível: `ATRASO_ARTIFICIAL=5` no `worker-2` (docker-compose.yml) e `docker kill` logo após disparar o job
- [ ] Diagramas exportados de `docs/arquitetura.md` (https://mermaid.live) para os slides

## Perguntas prováveis

- **E se o Manager cair?** É o ponto único de falha do coordenador, mas o estado (filas, jobs, resultados) fica no Redis com AOF. Ao reiniciar, o Manager retoma a coleta. No Swarm, o `restart_policy` o recria automaticamente.
- **E se o Redis cair?** É o ponto único da solução atual. Evolução: Redis Sentinel/Cluster.
- **Por que threads, se Python tem GIL?** O gargalo é I/O (rede), resolvido com asyncio. As threads tiram o processamento do event loop, para que o heartbeat e o consumo da fila não travem. Para CPU pesado, bastaria trocar por `ProcessPoolExecutor`.
- **Uma tarefa pode ser processada duas vezes?** Sim (*at-least-once*). Por isso o Manager grava com `HSETNX` (idempotente) e conta cada tarefa uma única vez.

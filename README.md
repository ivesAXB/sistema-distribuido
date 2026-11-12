# 🌾 Safra Distribuída

[![Testes](https://github.com/ivesAXB/sistema-distribuido/actions/workflows/testes.yml/badge.svg)](https://github.com/ivesAXB/sistema-distribuido/actions/workflows/testes.yml)

Ecossistema distribuído que consome a **API SIDRA do IBGE** (pesquisa **LSPA**, Levantamento Sistemático da Produção Agrícola, tabela **6588**) e calcula, em paralelo, indicadores de safra por UF para o tema **Agronegócio / ESG**.

> Projeto Final — Desenvolvimento de Sistemas Distribuídos — Prof. Vitório Neto

- **Topologia:** 1 nó **Manager** (coordenador) + N nós **Workers** (processamento) + Redis (broker)
- **Paralelismo:** entre nós (vários Workers) e dentro de cada nó (corrotinas `asyncio` + `ThreadPoolExecutor`)
- **Tolerância a falhas:** heartbeat, *lease* de tarefas e reenfileiramento automático
- **Arquitetura e diagramas UML:** [`docs/arquitetura.md`](docs/arquitetura.md)
- **Roteiro do pitch:** [`docs/pitch.md`](docs/pitch.md)

---

## POP — Procedimento Operacional Padrão: como subir e rodar com Docker

### Pré-requisitos

- **Docker Desktop** (Windows/macOS) ou **Docker Engine + Compose v2** (Linux)
- Acesso à internet (os Workers consultam `https://apisidra.ibge.gov.br`)
- Porta **8000** livre

Confira a instalação:

```bash
docker --version
docker compose version
```

### Passo 1 — Clonar o repositório

```bash
git clone https://github.com/ivesAXB/sistema-distribuido.git
cd sistema-distribuido
```

### Passo 2 — Construir as imagens e subir o cluster

```bash
docker compose up --build -d
```

Isso cria 5 containers na rede `safra-cluster`:

| Container | Papel |
|---|---|
| `safra-manager` | **MANAGER** (coordenador): API + painel na porta 8000 |
| `safra-worker-1` | **WORKER** (processamento) |
| `safra-worker-2` | **WORKER** (processamento) |
| `safra-worker-3` | **WORKER** (processamento) |
| `safra-redis` | Broker de mensagens / estado do cluster |

### Passo 3 — Verificar se os nós estão no ar

```bash
docker compose ps
```

Os papéis também ficam visíveis pelos *labels*:

```bash
docker ps --filter "label=org.safra.papel" --format "table {{.Names}}\t{{.Label \"org.safra.papel\"}}\t{{.Status}}"
```

### Passo 4 — Abrir o painel

Acesse **<http://localhost:8000>**. O painel mostra o Manager e os 3 Workers online.

### Passo 5 — Disparar um job distribuído

No painel, escolha os produtos e clique em **"Disparar job distribuído"**. Ou use a API:

```bash
curl -X POST http://localhost:8000/api/jobs -H "Content-Type: application/json" -d "{}"
```

O job padrão gera **50 tarefas** (10 produtos × 5 regiões), que os Workers dividem entre si. Ao terminar, aparecem os gráficos e a tabela por UF.

### Passo 6 — Acompanhar a distribuição nos logs

```bash
docker compose logs -f worker-1 worker-2 worker-3
```

Cada linha mostra qual Worker, qual corrotina e qual thread processou cada tarefa.

### Passo 7 — (Demonstração) Tolerância a falhas

Suba um job e, logo em seguida, derrube um Worker de forma abrupta:

```bash
docker kill safra-worker-2
```

Em ~10 s o Manager percebe que o heartbeat sumiu, devolve as tarefas daquele nó para a fila e os outros Workers terminam o job. No painel, o `worker-2` aparece como **offline**. Para trazê-lo de volta:

```bash
docker compose start worker-2
```

> Dica: para ver o resgate com calma, rode um Worker lento com `ATRASO_ARTIFICIAL=15` (variável de ambiente em segundos).

### Passo 8 — Encerrar

```bash
docker compose down
```

Para apagar também os dados do Redis:

```bash
docker compose down -v
```

### (Opcional) Docker Swarm — cluster com vários hosts

```bash
docker swarm init
docker compose build
docker stack deploy -c docker-stack.yml safra
docker service ls
docker service scale safra_worker=6
```

No Swarm, o serviço `manager` é restrito a nós com `node.role == manager`, e o serviço `worker` é replicado entre os nós do cluster. Para encerrar: `docker stack rm safra`.

---

## API do Manager

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/` | Painel web |
| `GET` | `/api/saude` | Health check |
| `GET` | `/api/catalogo` | Produtos, regiões e variáveis disponíveis |
| `POST` | `/api/jobs` | Cria um job `{produtos: [ids], regioes: ["N","NE",...], periodos: 13}` |
| `GET` | `/api/jobs` | Últimos jobs |
| `GET` | `/api/jobs/{id}` | Progresso do job |
| `GET` | `/api/jobs/{id}/resultado` | Resultado consolidado + distribuição por Worker |
| `GET` | `/api/cluster` | Estado do Manager, dos Workers e da fila |
| `GET` | `/docs` | Swagger (OpenAPI) gerado pelo FastAPI |

## Fonte de dados — SIDRA/IBGE

Endpoint usado pelos Workers (um por tarefa):

```
https://apisidra.ibge.gov.br/values/t/6588/n3/{UFs}/v/109,216,35,36/p/last 13/c48/{produto}?formato=json
```

| Parâmetro | Significado |
|---|---|
| `t/6588` | Tabela LSPA: estimativa anual de área plantada, colhida, produção e rendimento |
| `n3/{UFs}` | Nível territorial Unidade da Federação (as UFs da região da tarefa) |
| `v/109,216,35,36` | Área plantada (ha), área colhida (ha), produção (t), rendimento médio (kg/ha) |
| `p/last 13` | Últimos 13 meses de estimativa (mesmo mês do ano anterior → mês atual) |
| `c48/{produto}` | Classificação "Produto das lavouras" (ex.: 39443 = Soja) |

## Indicadores e relação com Agronegócio / ESG

| Indicador | Como é calculado | Leitura Agro/ESG |
|---|---|---|
| **Rendimento (kg/ha)** | produção ÷ área colhida | Eficiência no uso da terra: produzir mais sem abrir novas áreas, o que reduz a pressão por desmatamento (**E**) |
| **Área plantada não colhida (%)** | (plantada − colhida) ÷ plantada | Proxy de perdas por clima e pragas, ou seja, risco climático da safra (**E**) |
| **Variação da estimativa (%)** | estimativa atual vs. mesmo mês do ano anterior | Segurança alimentar e oferta para a cadeia agroindustrial (**S**) |
| **Concentração (top 3 UFs)** | participação das 3 maiores UFs | Dependência regional e exposição a eventos climáticos locais (risco/**G**) |

## Estrutura do repositório

```
sistema-distribuido/
├── docker-compose.yml        # topologia: manager + worker-1..3 + redis
├── docker-stack.yml          # alternativa Docker Swarm (manager/worker nodes)
├── comum/chaves.py           # contrato de filas/chaves do Redis (compartilhado)
├── manager/
│   ├── Dockerfile
│   └── app/
│       ├── main.py           # API, particionamento, coletor, vigia de falhas
│       ├── agregador.py      # consolidação (gather)
│       ├── catalogo.py       # tabela, produtos, regiões
│       └── static/index.html # painel
├── worker/
│   ├── Dockerfile
│   ├── app/
│   │   ├── main.py           # consumidores asyncio, heartbeat, pool de threads
│   │   ├── sidra.py          # cliente HTTP assíncrono do SIDRA (retry + semáforo)
│   │   └── processamento.py  # cálculo dos indicadores
│   └── tests/
├── .github/workflows/      # CI: testes + build das imagens
└── docs/
    ├── arquitetura.md        # diagramas UML (Mermaid)
    └── pitch.md              # roteiro de 10 min
```

## Configuração (variáveis de ambiente)

| Variável | Nó | Padrão | Descrição |
|---|---|---|---|
| `REDIS_URL` | ambos | `redis://redis:6379/0` | Endereço do broker |
| `NODE_ID` | ambos | hostname | Identificação do nó no cluster |
| `CONCORRENCIA` | worker | 4 | Corrotinas consumindo a fila |
| `THREADS` | worker | 4 | Threads do pool de processamento |
| `MAX_HTTP` | worker | 3 | Requisições simultâneas ao SIDRA por Worker |
| `HEARTBEAT_TTL` | worker | 10 | Segundos até o Worker ser considerado morto |
| `ATRASO_ARTIFICIAL` | worker | 0 | Atraso por tarefa (s), para demonstrações |
| `INTERVALO_VIGIA` | manager | 3 | Frequência da verificação de heartbeats (s) |
| `MAX_TENTATIVAS` | manager | 3 | Reenfileiramentos antes de marcar a tarefa como erro |

## Testes

São 13 testes automatizados, que o GitHub Actions roda a cada push (`.github/workflows/testes.yml`). O CI também valida o `docker-compose.yml` e constrói as imagens.

| Suíte | O que cobre |
|---|---|
| `manager/tests/test_api.py` | Particionamento produto × região, validação do pedido e idempotência (resultado duplicado conta 1x), usando Redis em memória |
| `manager/tests/test_agregador.py` | Consolidação nacional, rendimento, perdas, concentração e distribuição por Worker |
| `worker/tests/test_sidra.py` | Montagem do endpoint SIDRA e retentativas (503/429 repetem, 400 não repete) |
| `worker/tests/test_processamento.py` | Símbolos especiais do SIDRA (`-`, `...`, `X`) e indicadores por UF |

Para rodar localmente (sem Docker), a partir da raiz do repositório:

```bash
pip install -r manager/requirements.txt -r worker/requirements.txt -r requirements-dev.txt
cd manager && PYTHONPATH=.. python -m pytest -q tests && cd ..
cd worker && PYTHONPATH=.. python -m pytest -q tests && cd ..
```

## Equipe

| Nome | RA | Responsabilidade |
|---|---|---|
| | | |

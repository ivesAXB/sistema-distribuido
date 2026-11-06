# Arquitetura da Solução — Safra Distribuída

Os diagramas estão em Mermaid (o GitHub renderiza direto no navegador). Para exportar em PNG/SVG para os slides, use <https://mermaid.live>.

## 1. Topologia distribuída

**Estilo:** Manager/Worker (mestre-trabalhador) com **fila de trabalho compartilhada** (*work queue*) e **scatter-gather**:

1. O **Manager** (coordenador) recebe um pedido de análise e o **particiona** em tarefas independentes: `produto × macrorregião` (10 produtos × 5 regiões = 50 tarefas no job padrão).
2. As tarefas vão para uma fila no **Redis**. Qualquer **Worker** livre pega a próxima (*pull*): o balanceamento de carga é natural, e um worker mais rápido simplesmente pega mais tarefas.
3. Cada Worker consulta a **API SIDRA/IBGE** (LSPA, tabela 6588), calcula os indicadores e devolve um **resultado parcial**.
4. O Manager **coleta e consolida** (*gather*) os parciais na visão nacional.

| Nó | Papel | Quantidade | Tecnologia |
|---|---|---|---|
| `safra-manager` | Coordenador: API REST, particionamento, coleta, detecção de falhas, painel | 1 | Python 3.12, FastAPI, asyncio |
| `safra-worker-1..3` | Processamento: consumo da fila, I/O com o SIDRA, cálculo de indicadores | N (3 por padrão, escalável) | Python 3.12, asyncio, httpx, ThreadPoolExecutor |
| `safra-redis` | Broker de mensagens + estado compartilhado | 1 | Redis 7.2 |

### Por que estas escolhas

- **Fila *pull* em vez de *push* (RPC do Manager para os Workers):** o Manager não precisa conhecer os endereços dos Workers. Basta subir mais um container para escalar (`docker service scale` no Swarm).
- **Redis como broker:** listas com operações atômicas (`BLMOVE`) entregam semântica de *at-least-once* com pouca infraestrutura. Também guarda o estado do cluster (heartbeats, contadores e resultados).
- **Particionamento produto × região:** gera tarefas de tamanho parecido e independentes entre si (sem coordenação entre Workers), e cada requisição ao SIDRA fica pequena (respostas rápidas, menos risco de timeout).
- **Tolerância a falhas:** heartbeat com TTL + *lease* por worker + reenfileiramento pelo Manager + consolidação idempotente (`HSETNX`).

## 2. Diagrama de implantação (Docker)

```mermaid
flowchart TB
    user([Usuário / Navegador])
    sidra[(API SIDRA / IBGE<br/>apisidra.ibge.gov.br<br/>LSPA - tabela 6588)]

    subgraph docker["Docker host — rede bridge safra-cluster"]
        direction TB
        subgraph mgr["«node» safra-manager  (papel: MANAGER)"]
            api[FastAPI REST + Painel]
            part[Particionador]
            col[Coletor de resultados]
            vig[Vigia de heartbeat]
        end

        redis[("«node» safra-redis<br/>Redis 7.2<br/>filas + estado")]

        subgraph w1["«node» safra-worker-1 (WORKER)"]
            c1[4 corrotinas asyncio]
            t1[pool de 4 threads]
        end
        subgraph w2["«node» safra-worker-2 (WORKER)"]
            c2[4 corrotinas asyncio]
            t2[pool de 4 threads]
        end
        subgraph w3["«node» safra-worker-3 (WORKER)"]
            c3[4 corrotinas asyncio]
            t3[pool de 4 threads]
        end
    end

    user -- "HTTP :8000" --> api
    part -- "LPUSH tarefas" --> redis
    redis -- "BLPOP resultados" --> col
    vig -. "verifica heartbeats<br/>reenfileira tarefas" .-> redis
    redis -- "BLMOVE tarefa" --> c1 & c2 & c3
    c1 & c2 & c3 -- "RPUSH resultado<br/>SET heartbeat" --> redis
    c1 & c2 & c3 -- "HTTPS GET /values" --> sidra
```

## 3. Diagrama de componentes

```mermaid
flowchart LR
    subgraph Manager
        A[API REST<br/>/api/jobs, /api/cluster] --> P[Particionador<br/>produto × região]
        C[Coletor] --> AG[Agregador<br/>gather]
        V[Vigia de falhas]
        D[Painel web<br/>Chart.js]
    end
    subgraph Comum["Pacote comum"]
        K[chaves.py<br/>contrato de filas/chaves]
    end
    subgraph Worker
        CO[Consumidores asyncio] --> S[Cliente SIDRA<br/>httpx + semáforo + retry]
        CO --> PR[Processamento<br/>ThreadPoolExecutor]
        H[Heartbeat]
    end
    P -->|tarefas| Q[(Redis)]
    Q -->|tarefas| CO
    CO -->|resultados| Q
    Q -->|resultados| C
    H --> Q
    V --> Q
    Manager -.usa.-> K
    Worker -.usa.-> K
    S -->|HTTPS| SIDRA[(SIDRA/IBGE)]
```

## 4. Diagrama de sequência — execução de um job

```mermaid
sequenceDiagram
    autonumber
    actor U as Usuário
    participant M as Manager
    participant R as Redis
    participant W1 as Worker 1
    participant W2 as Worker 2
    participant S as API SIDRA

    U->>M: POST /api/jobs {produtos, periodos}
    M->>M: particiona em N tarefas (produto × região)
    M->>R: HSET job (status=na_fila, total=N)
    M->>R: LPUSH fila:tarefas (N tarefas)
    M-->>U: 201 {job_id}

    par Worker 1 (várias corrotinas em paralelo)
        W1->>R: BLMOVE fila:tarefas → processando:W1
        W1->>S: GET /values/t/6588/n3/{UFs}/v/.../c48/{produto}
        S-->>W1: JSON
        W1->>W1: indicadores no pool de threads
        W1->>R: RPUSH fila:resultados
        W1->>R: LREM processando:W1 (ack)
    and Worker 2
        W2->>R: BLMOVE fila:tarefas → processando:W2
        W2->>S: GET /values/...
        S-->>W2: JSON
        W2->>R: RPUSH fila:resultados
        W2->>R: LREM processando:W2 (ack)
    end

    loop Coletor (Manager)
        M->>R: BLPOP fila:resultados
        M->>R: HSETNX resultados[task_id] (idempotente)
        M->>R: HINCRBY concluidas
    end
    M->>R: HSET status=concluido

    U->>M: GET /api/jobs/{id}/resultado
    M->>R: HVALS resultados
    M->>M: agrega (thread) → visão nacional
    M-->>U: indicadores consolidados
```

## 5. Diagrama de sequência — falha de um Worker

```mermaid
sequenceDiagram
    autonumber
    participant W as Worker 2
    participant R as Redis
    participant M as Manager (vigia)
    participant W1 as Worker 1

    W->>R: SET heartbeat:W2 EX 10 (a cada ~3s)
    W->>R: BLMOVE tarefa → processando:W2
    Note over W: container morre (docker kill)
    Note over R: heartbeat:W2 expira após 10s
    M->>R: EXISTS heartbeat:W2 → 0
    M->>R: RPOP processando:W2 (tarefas órfãs)
    M->>R: RPUSH fila:tarefas (tentativas+1)
    M->>R: SREM workers W2
    W1->>R: BLMOVE pega a tarefa resgatada
    W1->>R: RPUSH resultado
```

## 6. Diagrama de classes

```mermaid
classDiagram
    class PedidoJob {
        +list~int~ produtos
        +list~str~ regioes
        +int periodos
    }
    class Tarefa {
        +str task_id
        +str job_id
        +int tabela
        +Produto produto
        +Regiao regiao
        +dict ufs
        +list~int~ variaveis
        +int periodos
        +int tentativas
    }
    class ResultadoParcial {
        +str task_id
        +str worker
        +list~IndicadorUF~ ufs
        +dict serie_producao
        +str periodo_atual
        +Metricas metricas
        +str erro
    }
    class IndicadorUF {
        +str uf
        +float producao_t
        +float area_plantada_ha
        +float area_colhida_ha
        +float rendimento_kg_ha
        +float perda_area_pct
        +float variacao_producao_pct
    }
    class Manager {
        +criar_job(PedidoJob)
        +coletor_resultados()
        +vigia_workers()
        +resultado_job(id)
    }
    class Worker {
        -Semaphore limite_http
        -ThreadPoolExecutor pool
        +registrar()
        +heartbeat()
        +consumidor(n)
        +executar(Tarefa)
    }
    class Agregador {
        +agregar(list~ResultadoParcial~) dict
    }
    class ClienteSidra {
        +montar_url(Tarefa) str
        +consultar(url) list
    }
    Manager ..> PedidoJob
    Manager --> "N" Tarefa : particiona
    Manager --> Agregador
    Worker --> ClienteSidra
    Worker ..> Tarefa : consome
    Worker --> ResultadoParcial : produz
    ResultadoParcial "1" *-- "N" IndicadorUF
```

## 7. Ciclo de vida da tarefa (estados)

```mermaid
stateDiagram-v2
    [*] --> NaFila: Manager LPUSH
    NaFila --> EmProcessamento: Worker BLMOVE (lease)
    EmProcessamento --> Concluida: RPUSH resultado + LREM
    EmProcessamento --> Erro: SIDRA falhou após 4 retentativas
    EmProcessamento --> NaFila: worker sem heartbeat (vigia)
    NaFila --> Erro: tentativas >= MAX_TENTATIVAS
    Concluida --> [*]
    Erro --> [*]
```

## 8. Paralelismo interno de um Worker

```mermaid
flowchart LR
    Q[(fila:tarefas)] --> C0 & C1 & C2 & C3
    subgraph EL["Event loop asyncio (1 thread)"]
        C0[corrotina 0]
        C1[corrotina 1]
        C2[corrotina 2]
        C3[corrotina 3]
        SEM{{Semáforo<br/>MAX_HTTP=3}}
        HB[heartbeat]
    end
    C0 & C1 & C2 & C3 --> SEM --> HTTP[httpx.AsyncClient<br/>conexões HTTP concorrentes]
    C0 & C1 & C2 & C3 -- run_in_executor --> TP
    subgraph TP["ThreadPoolExecutor (THREADS=4)"]
        T0[proc_0]
        T1[proc_1]
        T2[proc_2]
        T3[proc_3]
    end
```

- **I/O (HTTP ao SIDRA e Redis):** assíncrono. Enquanto uma corrotina espera a rede, as outras continuam. O semáforo limita as conexões simultâneas para respeitar o servidor do IBGE.
- **CPU (parse e indicadores):** delegado a um pool de threads, para que o event loop continue livre para responder ao heartbeat e consumir novas tarefas.

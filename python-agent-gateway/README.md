# Python Agent Gateway (gRPC)

## 1. Install

```bash
pip install -r requirements.txt
```

## 2. Generate gRPC code

```bash
python -m grpc_tools.protoc -I ./proto --python_out=. --grpc_python_out=. ./proto/agent_bridge.proto
```

## 3. Run

```bash
python server.py
```

Default ports:

- gRPC: `50051`
- health: `8089` (`/liveness`, `/readiness`)
- metrics: `9102`

## 4. Security env

### JWT

```bash
set AGENT_JWT_ENABLED=true
set AGENT_JWT_ALGORITHM=HS256
set AGENT_JWT_SECRET=change-me-change-me-change-me-change-me
set AGENT_JWT_ISSUER=agent-bridge-java
set AGENT_JWT_AUDIENCE=python-agent-gateway
```

RS256 / JWKS (optional):

```bash
set AGENT_JWT_ALGORITHM=RS256
set AGENT_JWT_PUBLIC_KEY_PATH=C:/certs/jwt-public.pem
set AGENT_JWT_JWKS_URL=https://issuer.example.com/.well-known/jwks.json
```

### TLS

```bash
set AGENT_TLS_ENABLED=true
set AGENT_TLS_CERT_PATH=C:/certs/server.pem
set AGENT_TLS_KEY_PATH=C:/certs/server.key
```

### mTLS

```bash
set AGENT_MTLS_ENABLED=true
set AGENT_TLS_CLIENT_CA_PATH=C:/certs/ca.pem
```

## 5. Runtime env (v1.1)

```bash
# production-safety
set AGENT_ENV=prod
set AGENT_ALLOW_PLAINTEXT=false

# async task store: memory|redis
set AGENT_TASK_STORE=redis
set AGENT_REDIS_HOST=127.0.0.1
set AGENT_REDIS_PORT=6379
set AGENT_REDIS_DB=0
set AGENT_REDIS_USER=
set AGENT_REDIS_PASSWORD=
set AGENT_REDIS_TIMEOUT_SEC=2
set AGENT_REDIS_KEY_PREFIX=agentbridge
set AGENT_IDEMPOTENCY_TTL_SEC=86400

# async worker
set AGENT_ASYNC_RETRY_MAX=1
set AGENT_TASK_TTL_SEC=86400
```

Notes:

- Non-dev env defaults TLS enabled (`AGENT_ENV=prod`).
- If TLS is disabled, `AGENT_ALLOW_PLAINTEXT=true` must be explicitly set.
- `/readiness` returns 503 when task-store dependency (for example Redis) is unavailable.

## 6. Docker compose quick start

```bash
docker compose up --build
```

Files:

- `docker-compose.yml`: start `python-agent-gateway + redis`
- `.env.example`: environment template
- `Dockerfile`: gateway image build

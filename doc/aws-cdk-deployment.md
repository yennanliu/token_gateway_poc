# AWS CDK Deployment — Infra Design

How to deploy the LLM API gateway to AWS with the AWS CDK (TypeScript).
This doc starts from the **simplest thing that works in production** and then
lists what to add as traffic grows. It maps the service's runtime needs
(container, database, secrets) onto a small set of managed AWS services.

> Companion code lives in [`gateway-cdk/`](../gateway-cdk). Today that folder is
> still the default `cdk init` scaffold (an SNS→SQS demo). This doc is the plan
> for what replaces it.

---

## 1. What we're deploying

The gateway is a **single stateless container** ([`Dockerfile`](../Dockerfile)):

- Python 3.12 / FastAPI / uvicorn, listens on **`:8000`**.
- On boot it runs `alembic upgrade head` (migrations) then serves.
- It is **horizontally scalable** — no local state. All state lives in the DB.

Its dependencies:

| Need | Local (docker-compose) | AWS (this doc) |
|------|------------------------|----------------|
| Relational DB | Postgres container | **RDS for PostgreSQL** |
| Rate-limit store (optional) | Redis container | **ElastiCache Redis** (deferred — see §6) |
| Secrets (upstream keys, admin token, Stripe) | `.env` file | **AWS Secrets Manager** |
| HTTPS entry point | `-p 8000:8000` | **Application Load Balancer + ACM cert** |

Config is entirely environment-variable driven (see [`.env.example`](../.env.example) and
[`src/gateway/config.py`](../src/gateway/config.py)), which maps cleanly onto ECS task
environment + secrets.

---

## 2. Simplest production architecture (the baseline)

**ECS Fargate service behind an Application Load Balancer, talking to RDS Postgres,
with secrets in Secrets Manager.** No servers to manage, pay-per-use, and it's the
natural home for an existing Dockerfile.

```
                    Internet
                       │  HTTPS (443)
                 ┌─────▼──────┐
                 │    ALB     │   (public subnets)  ── ACM TLS cert
                 └─────┬──────┘
                       │ HTTP :8000  (target group, health check GET /health)
              ┌────────▼─────────┐
              │  ECS Fargate     │   (private subnets)
              │  gateway task    │   desiredCount: 2
              │  FastAPI :8000   │
              └───┬──────────┬───┘
      reads/writes│          │ fetches at startup
              ┌───▼───┐  ┌───▼──────────────┐
              │  RDS  │  │ Secrets Manager  │
              │  PG   │  │ upstream keys,   │
              │(priv) │  │ admin token, …   │
              └───────┘  └──────────────────┘
```

Why Fargate over the alternatives (kept short, since we're keeping it simple):

- **vs. Lambda** — the gateway proxies **streaming** SSE responses and holds long-lived
  upstream connections. That fights Lambda's response model and 15-min cap. Fargate
  runs the container as-is with zero code changes.
- **vs. EC2 / EKS** — no instance patching, no Kubernetes control plane to run. Fargate
  is the least operational overhead for one container.
- **vs. App Runner** — App Runner is even simpler but gives less control over VPC
  networking to a private RDS and less room to grow. Fargate is the sweet spot.

---

## 3. AWS resources (one CDK stack to start)

Keep everything in **one stack** (`GatewayStack`) initially. Split later (§7) only if
lifecycles diverge.

| # | Resource | CDK construct | Notes |
|---|----------|---------------|-------|
| 1 | **VPC** | `ec2.Vpc` | 2 AZs, public + private-with-egress subnets. 1 NAT gateway to start (cost). |
| 2 | **ECR repo** | `ecr.Repository` (or `DockerImageAsset`) | Holds the gateway image. `DockerImageAsset` lets CDK build & push from the local Dockerfile on `cdk deploy`. |
| 3 | **RDS Postgres** | `rds.DatabaseInstance` | `t4g.micro` to start, single-AZ, 20 GB gp3, in private subnets. Auto-generated master secret. |
| 4 | **Secrets** | `secretsmanager.Secret` | One secret per upstream key + admin token (+ Stripe if used). DB secret is created by RDS. |
| 5 | **ECS cluster + Fargate service** | `ecs.Cluster` + `ecsp.ApplicationLoadBalancedFargateService` | The L3 pattern wires task def + ALB + target group + security groups in one construct. |
| 6 | **TLS cert** | `acm.Certificate` (DNS-validated) | Needs a domain in Route 53, or start HTTP-only for a pure POC. |
| 7 | **Logs** | Auto (`awslogs` driver) | CloudWatch log group per service. |

The `ApplicationLoadBalancedFargateService` pattern collapses most of the wiring:

```ts
const service = new ecsp.ApplicationLoadBalancedFargateService(this, 'Gateway', {
  cluster,
  desiredCount: 2,
  cpu: 512,            // 0.5 vCPU
  memoryLimitMiB: 1024,
  taskImageOptions: {
    image: ecs.ContainerImage.fromDockerImageAsset(imageAsset),
    containerPort: 8000,
    environment: {
      DATABASE_URL: '',          // assembled from the DB secret (see §4)
      DEFAULT_RPM_LIMIT: '600',
      ENABLE_TRANSLATION: 'false',
    },
    secrets: {
      OPENAI_API_KEY: ecs.Secret.fromSecretsManager(openaiSecret),
      ANTHROPIC_API_KEY: ecs.Secret.fromSecretsManager(anthropicSecret),
      GEMINI_API_KEY: ecs.Secret.fromSecretsManager(geminiSecret),
      ADMIN_TOKEN: ecs.Secret.fromSecretsManager(adminSecret),
    },
  },
  publicLoadBalancer: true,
  // certificate + domainName once a domain exists; otherwise HTTP-only POC.
});

service.targetGroup.configureHealthCheck({ path: '/health' });
db.connections.allowDefaultPortFrom(service.service);   // ECS → RDS on 5432
```

---

## 4. Configuration & secrets mapping

Every `.env` var becomes either a plaintext **environment** entry or a **secret** on the
task definition.

| `.env` var | Source in AWS | Kind |
|------------|---------------|------|
| `DATABASE_URL` | Built from the RDS-generated secret (host, port, user, password) — assemble as `postgresql+asyncpg://…` | secret-derived |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` | Secrets Manager | secret |
| `ADMIN_TOKEN` | Secrets Manager (generate, don't hardcode) | secret |
| `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` | Secrets Manager (only if payments enabled) | secret |
| `REDIS_URL` | ElastiCache endpoint | plaintext env (deferred) |
| `DEFAULT_RPM_LIMIT`, `ENABLE_TRANSLATION`, `MAX_RETRIES`, `*_BASE_URL` | Task env | plaintext |

Notes:

- **`DATABASE_URL` must use the `postgresql+asyncpg://` driver prefix** — SQLAlchemy async
  needs it. The RDS secret gives host/port/user/pass; compose the URL in the task
  (an entrypoint wrapper or a small init that reads the injected `DB_*` secret fields).
- ECS injects `secrets:` values as env vars at container start by pulling from Secrets
  Manager — they never appear in the task definition JSON or CloudFormation.
- Grant the **task execution role** read on each secret (the L3 pattern does this
  automatically for anything passed via `secrets:`).

---

## 5. Migrations & deploys

- **Migrations** already run automatically: the container `CMD` does
  `alembic upgrade head` before `uvicorn`. On a rolling ECS deploy the new task runs
  migrations as it boots. This is fine for the POC.
  - ⚠️ With `desiredCount > 1`, multiple tasks can race on `alembic upgrade` during a
    deploy. Alembic takes a lock so it's usually safe, but the clean fix (later) is a
    **one-shot ECS "migration task"** (or CodeBuild step) run *before* the service
    updates. Keep the auto-migrate for now; revisit if deploys collide.
- **Image build**: `DockerImageAsset` builds the Dockerfile locally during `cdk deploy`
  and pushes to the CDK-managed ECR. Simplest path — no separate CI push needed to start.
- **Rollout**: Fargate does a rolling replacement with ALB health checks on `/health`.
  Set `minHealthyPercent: 100`, `maxHealthyPercent: 200` for zero-downtime.
- **Rollback**: `cdk deploy` of the previous commit, or ECS "deployment circuit breaker"
  (`circuitBreaker: { rollback: true }`) to auto-revert a failed rollout.

> Health check: the app already exposes `GET /health` ([`src/gateway/main.py`](../src/gateway/main.py)),
> so the target group can point straight at it — no new route needed.

---

## 6. Deliberately deferred (keep it simple)

Ship without these; add when a real need shows up:

- **Redis / ElastiCache** — only needed to share rate limits across >1 instance. The
  in-memory token bucket works per-task; with 2 tasks a client's effective limit is
  ~2× the configured RPM. Acceptable for a POC. Add ElastiCache (`REDIS_URL`) when
  limits must be exact.
- **Custom domain + ACM** — start with the ALB's `*.elb.amazonaws.com` DNS name over
  HTTP, or a self-issued cert, for internal testing. Add Route 53 + ACM for a real URL.
- **Autoscaling** — start with a fixed `desiredCount: 2`. Add target-tracking on CPU
  (`service.autoScaleTaskCount`) later.
- **RDS Multi-AZ / read replicas / Proxy** — single-AZ `t4g.micro` first. Multi-AZ when
  uptime matters; RDS Proxy if connection counts climb.
- **WAF, CloudFront** — add WAF on the ALB when exposed publicly at scale.

---

## 7. Growth path (when the POC graduates)

1. **Split stacks** by lifecycle: `NetworkStack` (VPC), `DataStack` (RDS, ElastiCache,
   secrets), `ServiceStack` (ECS + ALB). Data outlives frequent service redeploys.
2. **Environments** via CDK context/props: `dev` / `staging` / `prod` stacks with
   different instance sizes and counts.
3. **CI/CD**: move image build to CodePipeline/GitHub Actions → ECR, and `cdk deploy` from
   CI instead of a laptop. Add a dedicated migration task stage.
4. **Observability**: CloudWatch dashboards + alarms (5xx rate, task health, RDS CPU/conns,
   ALB latency). The app already emits per-request logs (`logs.record_request`).
5. **Exact rate limiting & Multi-AZ**: enable ElastiCache and RDS Multi-AZ (from §6).

---

## 8. Cost sketch (baseline, us-east-1, order-of-magnitude)

| Item | Config | ~Monthly |
|------|--------|----------|
| Fargate | 2 × 0.5 vCPU / 1 GB, always-on | ~$30 |
| ALB | 1 | ~$18 + LCU |
| RDS Postgres | `t4g.micro` single-AZ, 20 GB gp3 | ~$15 |
| NAT gateway | 1 | ~$32 + data |
| Secrets Manager | ~5 secrets | ~$2 |
| **Total** | | **~$100/mo** before traffic |

Biggest levers if cost matters: drop to 1 task, or replace the NAT gateway (use VPC
endpoints for ECR/Secrets/CloudWatch and put tasks in isolated subnets) — NAT is often
the largest line item at idle.

---

## 9. Getting started (from the existing scaffold)

```bash
cd gateway-cdk
npm install
npx cdk bootstrap            # once per account/region
# ... replace lib/gateway-cdk-stack.ts (currently the SNS/SQS demo) with GatewayStack
npx cdk synth                # inspect the CloudFormation
npx cdk deploy               # builds the Dockerfile, pushes to ECR, deploys
```

The current `lib/gateway-cdk-stack.ts` is the default `cdk init` template and should be
replaced with the resources in §3. The stack name in `bin/` (`GatewayCdkStack`) can stay.

---

## Summary

Start with **one CDK stack**: VPC → RDS Postgres → Secrets Manager →
Fargate service behind an ALB, image built from the repo's existing Dockerfile via
`DockerImageAsset`, config injected as task env + secrets. Skip Redis, custom domains,
autoscaling, and Multi-AZ until there's a concrete need. Everything the app requires is
already env-driven and stateless, so this is a near-lift-and-shift of `docker-compose`
onto managed AWS services.

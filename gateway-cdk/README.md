# gateway-cdk

AWS CDK (TypeScript) app that deploys the LLM API gateway to AWS. It implements
the simple-first baseline described in
[`../doc/aws-cdk-deployment.md`](../doc/aws-cdk-deployment.md):

```
ALB (public) → ECS Fargate (private) → RDS Postgres (private)
                                     → Secrets Manager (upstream keys, admin token)
```

The container image is built from the repo's own [`../Dockerfile`](../Dockerfile)
via a `DockerImageAsset`, so `cdk deploy` builds and pushes it — no separate CI
step. All config is injected as ECS task environment + secrets; the Postgres DSN
(`postgresql+asyncpg://…`) is assembled inside the container from the RDS-managed
secret so the password never lands in the task definition.

Defined in [`lib/gateway-cdk-stack.ts`](lib/gateway-cdk-stack.ts).

## Prerequisites

- Node 18+ and Docker running (Docker is needed at **deploy** time to build the image).
- AWS credentials configured (`aws configure` / SSO), and the target account
  bootstrapped: `npx cdk bootstrap`.

## Deploy

```bash
npm install
npx cdk bootstrap                 # once per account/region
npx cdk synth                     # inspect the CloudFormation (no Docker needed)
npx cdk deploy                    # builds the image, pushes to ECR, deploys
```

After the first deploy, set the **real** upstream provider keys (the stack creates
placeholder secrets). Find their ARNs in the Secrets Manager console (named
`OpenAiApiKey…`, `AnthropicApiKey…`, `GeminiApiKey…`) and:

```bash
aws secretsmanager put-secret-value --secret-id <arn> --secret-string 'sk-...'
```

Then force a new deployment so tasks pick them up:

```bash
aws ecs update-service --cluster <cluster> --service <service> --force-new-deployment
```

The `ADMIN_TOKEN` is auto-generated; its secret ARN is a stack output
(`AdminTokenSecretArn`). The public URL is the `ServiceUrl` output — point any
provider SDK's base URL there.

## Commands

- `npm run build` — `tsc` typecheck / compile
- `npm test` — jest assertions on the synthesized template (no Docker required)
- `npx cdk diff` — diff against the deployed stack
- `npx cdk destroy` — tear down (the DB has `removalPolicy: DESTROY` for the POC)

## What's deferred

Per §6 of the design doc: Redis/ElastiCache, custom domain + ACM (HTTP only for
now), autoscaling (fixed `desiredCount: 2`), and RDS Multi-AZ. See the doc for the
growth path.

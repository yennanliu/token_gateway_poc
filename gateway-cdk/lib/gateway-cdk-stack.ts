import * as path from 'path';
import { CfnOutput, RemovalPolicy, Stack, StackProps } from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ecsp from 'aws-cdk-lib/aws-ecs-patterns';
import * as ecr_assets from 'aws-cdk-lib/aws-ecr-assets';
import * as rds from 'aws-cdk-lib/aws-rds';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';

/**
 * GatewayCdkStack — the "simple-first" baseline from doc/aws-cdk-deployment.md.
 *
 *   ALB (public) -> ECS Fargate (private) -> RDS Postgres (private)
 *                                         -> Secrets Manager (upstream keys)
 *
 * The image is built from the repo's existing Dockerfile via a DockerImageAsset,
 * so `cdk deploy` builds + pushes with no separate CI step. Everything the app
 * needs is env-driven (see src/gateway/config.py), which maps onto ECS task
 * environment + secrets.
 *
 * Deferred by design (§6 of the doc): Redis/ElastiCache, custom domain + ACM,
 * autoscaling, RDS Multi-AZ. Add them when there's a concrete need.
 */
export class GatewayCdkStack extends Stack {
  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);

    // --- 1. Network -------------------------------------------------------
    // 2 AZs; 1 NAT gateway keeps idle cost down (NAT is the biggest line item).
    const vpc = new ec2.Vpc(this, 'GatewayVpc', {
      maxAzs: 2,
      natGateways: 1,
    });

    // --- 2. Container image (built from ../Dockerfile at deploy time) -----
    // Repo root is two levels up from lib/ (gateway-cdk/lib -> gateway-cdk -> repo).
    const image = ecs.ContainerImage.fromDockerImageAsset(
      new ecr_assets.DockerImageAsset(this, 'GatewayImage', {
        directory: path.join(__dirname, '..', '..'),
        platform: ecr_assets.Platform.LINUX_AMD64,
      }),
    );

    // --- 3. Database ------------------------------------------------------
    // Single-AZ t4g.micro to start. RDS auto-generates a master secret whose
    // password excludes URL-unsafe characters, so it's safe to interpolate
    // into the asyncpg DSN below.
    const db = new rds.DatabaseInstance(this, 'GatewayDb', {
      engine: rds.DatabaseInstanceEngine.postgres({
        version: rds.PostgresEngineVersion.VER_16,
      }),
      instanceType: ec2.InstanceType.of(
        ec2.InstanceClass.BURSTABLE4_GRAVITON,
        ec2.InstanceSize.MICRO,
      ),
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      allocatedStorage: 20,
      storageType: rds.StorageType.GP3,
      databaseName: 'gateway',
      multiAz: false,
      // POC: destroy the DB with the stack. Switch to SNAPSHOT/RETAIN for prod.
      removalPolicy: RemovalPolicy.DESTROY,
      deletionProtection: false,
    });
    const dbSecret = db.secret!; // created by fromGeneratedSecret (the default)

    // --- 4. Application secrets ------------------------------------------
    // Placeholder secrets — after `cdk deploy`, set the real values in the
    // Secrets Manager console (or via `aws secretsmanager put-secret-value`).
    // The auto-generated random string is just a stand-in until then.
    const secret = (idPart: string, description: string) =>
      new secretsmanager.Secret(this, idPart, { description });

    const openaiKey = secret('OpenAiApiKey', 'Real OpenAI API key the gateway injects upstream');
    const anthropicKey = secret('AnthropicApiKey', 'Real Anthropic API key the gateway injects upstream');
    const geminiKey = secret('GeminiApiKey', 'Real Gemini API key the gateway injects upstream');
    // Admin/console token — safe to auto-generate; no manual step needed.
    const adminToken = new secretsmanager.Secret(this, 'AdminToken', {
      description: 'X-Admin-Token for the console / /admin endpoints',
      generateSecretString: { passwordLength: 48, excludePunctuation: true },
    });

    // --- 5. ECS Fargate service behind an ALB ----------------------------
    const cluster = new ecs.Cluster(this, 'GatewayCluster', { vpc });

    // The app reads DATABASE_URL directly, but the DB password lives in a
    // secret. We inject the DB fields as secrets and assemble the asyncpg DSN
    // inside the container so the password never lands in the task definition.
    const command = [
      'sh',
      '-c',
      [
        'export DATABASE_URL="postgresql+asyncpg://$DB_USER:$DB_PASSWORD@$DB_HOST:$DB_PORT/$DB_NAME"',
        'alembic upgrade head',
        'exec uvicorn gateway.main:app --host 0.0.0.0 --port 8000',
      ].join(' && '),
    ];

    const service = new ecsp.ApplicationLoadBalancedFargateService(this, 'Gateway', {
      cluster,
      desiredCount: 2,
      cpu: 512, // 0.5 vCPU
      memoryLimitMiB: 1024,
      publicLoadBalancer: true,
      // POC: HTTP only. Add `certificate` + `domainName`/`domainZone` for HTTPS.
      taskImageOptions: {
        image,
        containerPort: 8000,
        command,
        environment: {
          DB_NAME: 'gateway',
          DEFAULT_RPM_LIMIT: '600',
          ENABLE_TRANSLATION: 'false',
        },
        secrets: {
          DB_HOST: ecs.Secret.fromSecretsManager(dbSecret, 'host'),
          DB_PORT: ecs.Secret.fromSecretsManager(dbSecret, 'port'),
          DB_USER: ecs.Secret.fromSecretsManager(dbSecret, 'username'),
          DB_PASSWORD: ecs.Secret.fromSecretsManager(dbSecret, 'password'),
          OPENAI_API_KEY: ecs.Secret.fromSecretsManager(openaiKey),
          ANTHROPIC_API_KEY: ecs.Secret.fromSecretsManager(anthropicKey),
          GEMINI_API_KEY: ecs.Secret.fromSecretsManager(geminiKey),
          ADMIN_TOKEN: ecs.Secret.fromSecretsManager(adminToken),
        },
      },
      // Zero-downtime rolling deploys + auto-rollback on a failed rollout.
      minHealthyPercent: 100,
      maxHealthyPercent: 200,
      circuitBreaker: { rollback: true },
    });

    // Health check hits the app's existing GET /health (src/gateway/main.py).
    service.targetGroup.configureHealthCheck({ path: '/health' });

    // Let the Fargate tasks reach Postgres on 5432.
    db.connections.allowDefaultPortFrom(service.service);

    // --- 6. Outputs -------------------------------------------------------
    new CfnOutput(this, 'ServiceUrl', {
      value: `http://${service.loadBalancer.loadBalancerDnsName}`,
      description: 'Public gateway URL (point provider SDK base URLs here)',
    });
    new CfnOutput(this, 'AdminTokenSecretArn', {
      value: adminToken.secretArn,
      description: 'Secret holding the X-Admin-Token',
    });
  }
}

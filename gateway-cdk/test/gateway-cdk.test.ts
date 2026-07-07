import * as cdk from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import * as GatewayCdk from '../lib/gateway-cdk-stack';

// NOTE: synthesizing this stack builds the gateway Docker image (DockerImageAsset),
// so `npm test` requires a running Docker daemon.
test('provisions the Fargate-behind-ALB gateway baseline', () => {
  const app = new cdk.App();
  const stack = new GatewayCdk.GatewayCdkStack(app, 'TestStack', {
    env: { account: '123456789012', region: 'us-east-1' },
  });

  const template = Template.fromStack(stack);

  // Postgres RDS instance
  template.hasResourceProperties('AWS::RDS::DBInstance', {
    Engine: 'postgres',
  });

  // Fargate service behind a public ALB, container on port 8000
  template.resourceCountIs('AWS::ECS::Service', 1);
  template.hasResourceProperties('AWS::ElasticLoadBalancingV2::LoadBalancer', {
    Scheme: 'internet-facing',
  });
  template.hasResourceProperties('AWS::ElasticLoadBalancingV2::TargetGroup', {
    HealthCheckPath: '/health',
  });

  // 3 placeholder upstream-key secrets + generated admin token + RDS master (5)
  template.resourceCountIs('AWS::SecretsManager::Secret', 5);
});

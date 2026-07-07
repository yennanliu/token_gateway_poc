#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { GatewayCdkStack } from '../lib/gateway-cdk-stack';

const app = new cdk.App();
new GatewayCdkStack(app, 'GatewayCdkStack', {
  // Use the ambient CLI account/region so RDS/AZ lookups resolve concretely.
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION,
  },
});

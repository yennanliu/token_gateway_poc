#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib/core';
import { GatewayCdkStack } from '../lib/gateway-cdk-stack';

const app = new cdk.App();
new GatewayCdkStack(app, 'GatewayCdkStack');

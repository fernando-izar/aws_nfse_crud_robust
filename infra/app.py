#!/usr/bin/env python3
import os
import aws_cdk as cdk
from robust_stack import RobustNfseStack

app = cdk.App()
RobustNfseStack(app, "NfseStack",
                env=cdk.Environment(
                    account=os.getenv("CDK_DEFAULT_ACCOUNT"),
                    region=os.getenv("CDK_DEFAULT_REGION", "us-east-1")
                ))
app.synth()

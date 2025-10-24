# rate-limiter

## Deploy the  application

```
sam build
```
``
sam deploy   --stack-name rate-limiter-sam   --resolve-s3   --parameter-overrides     RedisEndpoint=rate-limit-valkey-ifklzy.serverless.usw2.cache.amazonaws.com     RedisPort=6379     Subnet1=subnet-0cee86b345a8e194a     Subnet2=subnet-0fc1f52ffb2acc7bf     LambdaSG=sg-0c37a54ff5c9f4f13   --capabilities CAPABILITY_IAM
```

## Cleanup

To delete the sample application that you created, use the AWS CLI. Assuming you used your project name for the stack name, you can run the following:

```bash
sam delete --stack-name "rate-limiter"
```

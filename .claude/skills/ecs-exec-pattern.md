# ECS Exec S3-Mediated Pattern

Use this pattern for ALL DB queries from local machine.
ECS container has no psql, no aws CLI — only python3 + asyncpg + boto3.

## Steps
1. Write script to /tmp/script.py (must upload results to S3)
2. Upload: aws s3 cp /tmp/script.py s3://aa-cis-bronze-867490540162/scripts/script.py --profile pqnghiep-admin --region us-west-1
3. Presign: URL=$(aws s3 presign s3://aa-cis-bronze-867490540162/scripts/script.py --profile pqnghiep-admin --region us-west-1 --expires-in 300)
4. Get task: TASK_ARN=$(aws ecs list-tasks --cluster aa-cis-dev-cluster --service-name aa-cis-dev-api --profile pqnghiep-admin --region us-west-1 --query 'taskArns[0]' --output text)
5. Run: aws ecs execute-command --cluster aa-cis-dev-cluster --task $TASK_ARN --container api --interactive --command "sh -c 'curl -s \"$URL\" -o /tmp/s.py && python3 /tmp/s.py'" --profile pqnghiep-admin --region us-west-1

## Script template
```python
import asyncio, json, boto3
from urllib.parse import urlparse

async def main():
    import asyncpg
    sm = boto3.client("secretsmanager", region_name="us-west-1")
    dsn = sm.get_secret_value(SecretId="aa-cis/dev/rds")["SecretString"].strip()
    p = urlparse(dsn)
    conn = await asyncpg.connect(
        host=p.hostname, port=p.port or 5432,
        database=p.path.lstrip("/"), user=p.username, password=p.password,
        ssl="require"
    )
    # ... queries ...
    await conn.close()
    # Upload result to S3
    boto3.client("s3", region_name="us-west-1").put_object(
        Bucket="aa-cis-bronze-867490540162", Key="scripts/result.json",
        Body=json.dumps(result), ContentType="application/json"
    )
    print(json.dumps(result, indent=2, default=str))

asyncio.run(main())
```

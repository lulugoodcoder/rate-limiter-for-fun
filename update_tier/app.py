import os
import json
import redis
import time

REDIS_HOST = os.environ['REDIS_HOST']
REDIS_PORT = int(os.environ['REDIS_PORT'])

redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    socket_connect_timeout=2,
    socket_timeout=2,
    decode_responses=True,
    ssl=True,                     # <--- Enable TLS
    ssl_cert_reqs=None  
)

MAX_RETRIES = 3
RETRY_DELAY = 0.3

def lambda_handler(event, context):
    try:
        body = json.loads(event.get('body') or '{}')
        user_id = body['user_id']
        tier = body['tier']
    except Exception as e:
        return {"statusCode": 400, "body": json.dumps({"error": "invalid body", "detail": str(e)})}

    key = f"user:{{{user_id}}}:tier"

    for attempt in range(MAX_RETRIES):
        try:
            redis_client.set(key, tier)
            break
        except redis.exceptions.ConnectionError as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
            else:
                return {"statusCode": 500, "body": json.dumps({"error": "valkey_error", "detail": str(e)})}

    return {"statusCode": 200, "body": json.dumps({"ok": True, "user_id": user_id, "tier": tier})}



import os
import json
import redis

REDIS_HOST = os.environ['REDIS_HOST']
REDIS_PORT = int(os.environ['REDIS_PORT'])

redis_client = redis.Redis(  
    host=REDIS_HOST,
    port=REDIS_PORT,
    socket_connect_timeout=2,
    socket_timeout=2,
    decode_responses=True,
    ssl=True,           
    ssl_cert_reqs=None, 
)

def lambda_handler(event, context):
    """
    POST /update-rules
    body: {"tier": "premium", "max_tokens": 100, "refill_rate": 10}
    """
    try:
        body = json.loads(event.get('body') or '{}')
        tier = body['tier']
        max_tokens = int(body['max_tokens'])
        refill_rate = float(body['refill_rate'])
    except Exception as e:
        return {"statusCode": 400, "body": json.dumps({"error": "invalid body", "detail": str(e)})}

    key = f"rules:tier:{tier}"
    try:
        # HMSET via hset in redis-py: mapping argument
        redis_client.hset(key, mapping={"max_tokens": max_tokens, "refill_rate": refill_rate})
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"error": "redis_error", "detail": str(e)})}

    return {"statusCode": 200, "body": json.dumps({"ok": True, "tier": tier})}

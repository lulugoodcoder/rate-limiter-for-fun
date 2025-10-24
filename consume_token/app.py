import os
import json
import redis
import time
import boto3
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import atexit

REDIS_HOST = os.environ['REDIS_HOST']
REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))

def log_metric(name, value, unit="Count"):
    """Log metric using EMF - CloudWatch automatically extracts it"""
    metric_log = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [{
                "Namespace": "RateLimiter",
                "Dimensions": [[]],
                "Metrics": [{
                    "Name": name,
                    "Unit": unit
                }]
            }]
        },
        name: value
    }
    print(json.dumps(metric_log))

# Redis client
r = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    socket_connect_timeout=2,
    socket_timeout=2,
    decode_responses=True,
    ssl=True,
    ssl_cert_reqs=None,
)

# Lua script: token bucket
LUA_SCRIPT = """
-- KEYS[1] = bucket_key
-- ARGV[1] = now
-- ARGV[2] = cost
-- ARGV[3] = JSON string of all rules

local bucket_key = KEYS[1]
local now = tonumber(ARGV[1])
local cost = tonumber(ARGV[2])
local rules_json = ARGV[3]

-- Parse rules map
local cjson = cjson or require("cjson")
local rules = cjson.decode(rules_json)

-- Extract user_id from bucket key
local user_id = bucket_key:match("bucket:{(.*)}")
local user_tier_key = "user:{" .. user_id .. "}:tier"
local tier = redis.call("GET", user_tier_key)
if not tier then
    return {0, "USER_NOT_FOUND"}
end

local tier_rule = rules[tier]
if not tier_rule or not tier_rule["max_tokens"] or not tier_rule["refill_rate"] then
    return {0, "TIER_CONFIG_NOT_FOUND"}
end

local max_tokens = tonumber(tier_rule["max_tokens"])
local refill_rate = tonumber(tier_rule["refill_rate"])

-- Get current bucket state
local bucket = redis.call("HMGET", bucket_key, "tokens", "last_refill")
local tokens = tonumber(bucket[1]) or max_tokens
local last_refill = tonumber(bucket[2]) or now

local elapsed = math.max(0, now - last_refill)
local refilled_tokens = tokens + (elapsed * refill_rate)
local available_tokens = math.min(max_tokens, refilled_tokens)

if available_tokens >= cost then
    local new_tokens = available_tokens - cost
    redis.call("HMSET", bucket_key, "tokens", new_tokens, "last_refill", now)
    redis.call("EXPIRE", bucket_key, 3600)
    return {1, tostring(new_tokens)}
else
    return {0, tostring(available_tokens)}
end
"""

MAX_RETRIES = 3
RETRY_DELAY = 0.3
SCRIPT_SHA = None

# Module-level cache (persists across warm Lambda invocations)
_RULES_CACHE = None

def load_script():
    """Load Lua script into Redis and cache SHA"""
    global SCRIPT_SHA
    if SCRIPT_SHA:
        return SCRIPT_SHA
    try:
        SCRIPT_SHA = r.script_load(LUA_SCRIPT)
    except Exception:
        SCRIPT_SHA = None
    return SCRIPT_SHA

def get_rules():
    """Get all tier rules using SCAN, with in-memory caching"""
    global _RULES_CACHE
    if _RULES_CACHE is None:
        all_rules = {}
        
        # Use SCAN instead of KEYS (non-blocking, safe for production)
        cursor = 0
        while True:
            cursor, keys = r.scan(cursor, match="rules:tier:*", count=100)
            for k in keys:
                tier_name = k.split(":")[-1]
                rule = r.hgetall(k)
                all_rules[tier_name] = rule
            if cursor == 0:
                break
        
        _RULES_CACHE = all_rules
    return _RULES_CACHE

def lambda_handler(event, context):
    """
    POST /consume
    body: {"user_id": "alice", "cost": 1}
    """
    # Parse input
    try:
        body = json.loads(event.get('body') or '{}')
        user_id = body.get('user_id')
        cost = int(body.get('cost', 1))
        if not user_id:
            raise ValueError("missing user_id")
    except Exception as e:
        return {
            "statusCode": 400, 
            "body": json.dumps({"error": "invalid body", "detail": str(e)})
        }

    # Get rules (cached after first call)
    try:
        all_rules = get_rules()
    except Exception as e:
        return {
            "statusCode": 500, 
            "body": json.dumps({"error": "failed to load rules", "detail": str(e)})
        }

    if not all_rules:
        return {
            "statusCode": 500, 
            "body": json.dumps({"error": "NO_RULES_FOUND"})
        }

    now = int(time.time())
    bucket_key = f"bucket:{{{user_id}}}"
    rules_json = json.dumps(all_rules)

    sha = load_script()
    res = None

    # Execute Lua script with retries
    for attempt in range(MAX_RETRIES):
        try:
            if sha:
                res = r.evalsha(sha, 1, bucket_key, now, cost, rules_json)
            else:
                res = r.eval(LUA_SCRIPT, 1, bucket_key, now, cost, rules_json)
            break
        except redis.exceptions.NoScriptError:
            sha = load_script()
        except redis.exceptions.ConnectionError as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
            else:
                return {
                    "statusCode": 500, 
                    "body": json.dumps({
                        "error": "valkey_connection_error", 
                        "detail": str(e)
                    })
                }
        except Exception as e:
            return {
                "statusCode": 500, 
                "body": json.dumps({
                    "error": "valkey_error", 
                    "detail": str(e)
                })
            }

    # Parse response
    try:
        allowed = int(res[0]) == 1
        data = res[1]
        log_metric("ConsumeRequestTotal", 1)
        log_metric("ConsumeRequestAllowed", 1 if allowed else 0)
        log_metric("ConsumeRequestDenied", 0 if allowed else 1)
    except Exception:
        return {
            "statusCode": 500, 
            "body": json.dumps({
                "error": "bad_redis_response", 
                "resp": str(res)
            })
        }

    status = 200 if allowed else 429
    return {
        "statusCode": status, 
        "body": json.dumps({
            "allowed": allowed, 
            "detail": data
        })
    }

#!/bin/bash

URL="https://gt40uqms31.execute-api.us-west-2.amazonaws.com/Prod/consume"
USER_ID="alice"
NUM_REQUESTS=1000
PARALLEL=10

for i in $(seq 1 $NUM_REQUESTS); do
  (
    RESPONSE=$(curl -s -X POST $URL \
      -H "Content-Type: application/json" \
      -d "{\"user_id\": \"$USER_ID\"}")
    echo "Request $i: $RESPONSE"
  ) &
  
  # limit number of parallel jobs
  if (( i % PARALLEL == 0 )); then
    wait
  fi
done

# wait for remaining background jobs
wait


#!/usr/bin/env bash

docker stop probablefuturesbot
docker rm probablefuturesbot
docker run --restart always --name probablefuturesbot -d -v /home/ubuntu/probable-futures-bot/logs/:/probablefuturesbot/probablefuturesbot/logs probablefuturesbot/probablefuturesbot bash -c "cd /probablefuturesbot/probablefuturesbot && python3 -m probablefuturesbot"
docker logs -f probablefuturesbot
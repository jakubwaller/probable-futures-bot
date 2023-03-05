#!/usr/bin/env bash

git pull
docker build -t probablefuturesbot/probablefuturesbot -f Dockerfile-linux .

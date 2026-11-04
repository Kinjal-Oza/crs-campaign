#!/bin/bash
# Prepare app A (asynchronous social network): DeathStarBench commit 5728790 with RabbitMQ home-timeline fan-out.
# Changes, all mechanical: 10% probabilistic sampling; Jaeger and stores pinned; image tag for the source build; init script -> localhost.
set -euo pipefail
D=${1:-dsb_async}; IMG=${IMG:-ghcr.io/kinjal-oza/sn-async:5728790}
git clone -q https://github.com/delimitrou/DeathStarBench.git $D && cd $D && git checkout -q 5728790 && cd socialNetwork
python3 - "$IMG" <<'PY'
import sys, re, json
img = sys.argv[1]
c = open("docker-compose.yml").read()
c = c.replace("image: yg397/social-network-microservices", f"image: {img}")
c = c.replace("image: jaegertracing/all-in-one:latest", "image: jaegertracing/all-in-one:1.57")
c = re.sub(r"image: mongo\s*\n", "image: mongo:4.0.28\n", c)
c = re.sub(r"image: redis\s*\n", "image: redis:5.0.14\n", c)
c = re.sub(r"image: memcached\s*\n", "image: memcached:1.5.22\n", c)
c = re.sub(r"image: rabbitmq\s*\n", "image: rabbitmq:3.8.34\n", c)
c = c.replace("      - 16686:16686\n", "      - 16686:16686\n      - 6831:6831/udp\n")
open("docker-compose.yml", "w").write(c)
j = json.load(open("nginx-web-server/jaeger-config.json")); j["sampler"] = {"type": "probabilistic", "param": 0.1}
json.dump(j, open("nginx-web-server/jaeger-config.json", "w"), indent=2)
y = open("config/jaeger-config.yml").read().replace("type: const", "type: probabilistic").replace("param: 1", "param: 0.1")
open("config/jaeger-config.yml", "w").write(y)
s = open("scripts/init_social_graph.py").read().replace('addr = "http://10.68.39.88:8080"', 'addr = "http://localhost:8080"')
open("scripts/init_social_graph.py", "w").write(s)
PY
grep -n "image:" docker-compose.yml | sort -k3 | uniq -f2 -c | head -20

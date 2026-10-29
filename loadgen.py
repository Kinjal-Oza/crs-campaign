"""Open-loop load generator for DeathStarBench socialNetwork (replaces wrk2, same request mix as mixed-workload.lua:
60% read-home-timeline, 30% read-user-timeline, 10% compose-post). Poisson arrivals at RATE req/s for DUR seconds.
Writes one line per request: t_send, endpoint, status, latency_ms.
Usage: python3 loadgen.py RATE DUR OUT.csv
"""
import asyncio, aiohttp, random, string, sys, time
RATE, DUR, OUT = float(sys.argv[1]), float(sys.argv[2]), sys.argv[3]
BASE = "http://localhost:8080"; NU = 962
def rs(n): return "".join(random.choices(string.ascii_letters + string.digits, k=n))
def req():
    r = random.random(); u = random.randrange(NU)
    if r < 0.6:
        s = random.randrange(100); return "home", "GET", f"{BASE}/wrk2-api/home-timeline/read?user_id={u}&start={s}&stop={s+10}", None
    if r < 0.9:
        s = random.randrange(100); return "user", "GET", f"{BASE}/wrk2-api/user-timeline/read?user_id={u}&start={s}&stop={s+10}", None
    text = rs(256) + "".join(f" @username_{random.randrange(NU)}" for _ in range(random.randint(0, 5))) \
         + "".join(f" http://{rs(64)}" for _ in range(random.randint(0, 5)))
    nm = random.randint(0, 4)
    data = dict(username=f"username_{u}", user_id=str(u), text=text,
                media_ids="[" + ",".join(f'"{random.randrange(10**17, 10**18)}"' for _ in range(nm)) + "]",
                media_types="[" + ",".join('"png"' for _ in range(nm)) + "]", post_type="0")
    return "compose", "POST", f"{BASE}/wrk2-api/post/compose", data

async def one(sess, f):
    name, m, url, data = req(); t0 = time.time()
    try:
        async with sess.request(m, url, data=data, timeout=aiohttp.ClientTimeout(total=10)) as r:
            await r.read(); st = r.status
    except Exception: st = 0
    f.write(f"{t0:.4f},{name},{st},{(time.time()-t0)*1000:.2f}\n")

async def main():
    conn = aiohttp.TCPConnector(limit=512)
    async with aiohttp.ClientSession(connector=conn) as sess:
        with open(OUT, "w") as f:
            f.write("t,endpoint,status,lat_ms\n"); tasks = set(); end = time.time() + DUR; nxt = time.time()
            while nxt < end:
                nxt += random.expovariate(RATE); d = nxt - time.time()
                if d > 0: await asyncio.sleep(d)
                t = asyncio.create_task(one(sess, f)); tasks.add(t); t.add_done_callback(tasks.discard)
            await asyncio.gather(*tasks)
asyncio.run(main())

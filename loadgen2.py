"""Open-loop Poisson load generator for two DeathStarBench apps.
APP=social: mixed-workload.lua mix (60% home-timeline, 30% user-timeline, 10% compose-post), nginx on :8080.
APP=hotel : mixed-workload_type_1.lua mix (60% search, 39% recommend, 0.5% user login, 0.5% reserve), frontend on :5000.
Usage: APP=... python3 loadgen2.py RATE DUR OUT.csv   (one line per request: t_send,endpoint,status,lat_ms)
"""
import asyncio, aiohttp, random, string, sys, time, os
RATE, DUR, OUT = float(sys.argv[1]), float(sys.argv[2]), sys.argv[3]
APP = os.environ.get("APP", "social")
def rs(n): return "".join(random.choices(string.ascii_letters + string.digits, k=n))

def social():
    B = "http://localhost:8080"; NU = 962; r = random.random(); u = random.randrange(NU)
    if r < 0.6:
        s = random.randrange(100); return "home", "GET", f"{B}/wrk2-api/home-timeline/read?user_id={u}&start={s}&stop={s+10}", None
    if r < 0.9:
        s = random.randrange(100); return "user", "GET", f"{B}/wrk2-api/user-timeline/read?user_id={u}&start={s}&stop={s+10}", None
    text = rs(256) + "".join(f" @username_{random.randrange(NU)}" for _ in range(random.randint(0, 5))) \
         + "".join(f" http://{rs(64)}" for _ in range(random.randint(0, 5)))
    nm = random.randint(0, 4)
    data = dict(username=f"username_{u}", user_id=str(u), text=text,
                media_ids="[" + ",".join(f'"{random.randrange(10**17, 10**18)}"' for _ in range(nm)) + "]",
                media_types="[" + ",".join('"png"' for _ in range(nm)) + "]", post_type="0")
    return "compose", "POST", f"{B}/wrk2-api/post/compose", data

def hotel():
    B = "http://localhost:5000"; c = random.random()
    lat = 38.0235 + (random.randint(0, 481) - 240.5) / 1000.0; lon = -122.095 + (random.randint(0, 325) - 157.0) / 1000.0
    def d(x): return f"2015-04-{x:02d}"
    if c < 0.6:
        i = random.randint(9, 23); o = random.randint(i + 1, 24)
        return "search", "GET", f"{B}/hotels?inDate={d(i)}&outDate={d(o)}&lat={lat}&lon={lon}", None
    if c < 0.99:
        q = random.choice(["dis", "rate", "price"]); return "recommend", "GET", f"{B}/recommendations?require={q}&lat={lat}&lon={lon}", None
    uid = random.randint(0, 500); un = f"Cornell_{uid}"; pw = str(uid) * 10
    if c < 0.995: return "user", "POST", f"{B}/user?username={un}&password={pw}", None
    i = random.randint(9, 23); o = i + random.randint(1, 5)
    return "reserve", "POST", (f"{B}/reservation?inDate={d(i)}&outDate={d(o)}&lat={lat}&lon={lon}&hotelId={random.randint(1, 80)}"
                               f"&customerName={un}&username={un}&password={pw}&number=1"), None
req = social if APP == "social" else hotel

async def one(sess, f):
    name, m, url, data = req(); t0 = time.time()
    try:
        async with sess.request(m, url, data=data, timeout=aiohttp.ClientTimeout(total=10)) as r:
            await r.read(); st = r.status
    except Exception: st = 0
    f.write(f"{t0:.4f},{name},{st},{(time.time()-t0)*1000:.2f}\n")

async def main():
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=512)) as sess:
        with open(OUT, "w") as f:
            f.write("t,endpoint,status,lat_ms\n"); tasks = set(); end = time.time() + DUR; nxt = time.time()
            while nxt < end:
                nxt += random.expovariate(RATE); dl = nxt - time.time()
                if dl > 0: await asyncio.sleep(dl)
                t = asyncio.create_task(one(sess, f)); tasks.add(t); t.add_done_callback(tasks.discard)
            await asyncio.gather(*tasks)
asyncio.run(main())

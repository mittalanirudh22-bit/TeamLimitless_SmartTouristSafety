"""Minimal load test: register N travellers, start tracking, then stream GPS fixes concurrently.

Usage: python scripts/loadtest.py --url http://localhost:8000 --travellers 50 --fixes 20 --concurrency 32
Registers real (test) travellers in the target database -- run it against a local or throwaway deployment.
"""
import argparse, asyncio, random, statistics, time
import httpx

REG = dict(nationality='Testland', phone='+91 90000 00000', emergency_name='Load Test', emergency_phone='+91 90000 00001', consent=True)


async def main(a):
    lim = httpx.Limits(max_connections=a.concurrency, max_keepalive_connections=a.concurrency)
    async with httpx.AsyncClient(base_url=a.url, timeout=60, limits=lim) as c:
        async def reg(i):
            r = await c.post('/api/travellers/register', json={**REG, 'full_name': f'Load Tester {i}'})
            r.raise_for_status()
            tok = {'X-Tracking-Token': r.json()['tracking_token']}
            (await c.post('/api/travellers/me/start', headers=tok)).raise_for_status()
            return tok
        t0 = time.time()
        toks = []
        for i in range(0, a.travellers, 10):  # registration is rate-limited per IP in prod; set high locally
            toks += await asyncio.gather(*[reg(j) for j in range(i, min(i + 10, a.travellers))])
        print(f'registered {len(toks)} travellers in {time.time() - t0:.1f}s')

        sem = asyncio.Semaphore(a.concurrency)
        lat, errs = [], 0

        async def walk(tok, k):
            nonlocal errs
            lat0, lon0 = 23.25 + random.random() * .02, 77.35 + random.random() * .06
            ts = time.time()
            for n in range(a.fixes):
                body = {'latitude': lat0 + n * 1e-4, 'longitude': lon0 + n * 1e-4,
                        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(ts + n * 5))}
                async with sem:
                    s = time.time()
                    try:
                        r = await c.post('/api/travellers/me/location', json=body, headers=tok)
                        r.raise_for_status()
                        lat.append(time.time() - s)
                    except Exception:
                        errs += 1
        t1 = time.time()
        await asyncio.gather(*[walk(t, k) for k, t in enumerate(toks)])
        dt = time.time() - t1
        lat.sort()
        q = lambda p: lat[min(len(lat) - 1, int(len(lat) * p))] * 1000 if lat else float('nan')
        print(f'accepted {len(lat)} fixes, {errs} errors in {dt:.1f}s -> {len(lat) / dt:.0f} fixes/s accepted by the API')
        print(f'API latency ms: p50={q(.5):.0f} p95={q(.95):.0f} p99={q(.99):.0f} max={lat[-1] * 1000 if lat else 0:.0f}')
        hdr = {'X-Ops-Token': a.ops_token} if a.ops_token else {}
        st = (await c.get('/api/ingest/stats', headers=hdr)).json()
        # In-process workers: wait until this process has handled everything it enqueued. With Redis the consumers are other
        # processes (their counters are not visible here); a fix leaves the stream only after it is committed, so depth 0 = drained.
        remote = st.get('backend') == 'redis'
        while st.get('queue_depth', 0) > 0 or (not remote and st.get('handled', 0) < st.get('enqueued', 0)):
            await asyncio.sleep(0.05)
            st = (await c.get('/api/ingest/stats', headers=hdr)).json()
        total = time.time() - t1
        print(f'fully processed in {total:.1f}s -> {len(lat) / total:.0f} fixes/s end-to-end '
              f'(backend={st["backend"]}, web-process batches={st["batches"]}, errors={st["errors"]})')
        s = time.time()
        r = await c.get('/api/tourists', headers={'X-Ops-Token': a.ops_token} if a.ops_token else {})
        print(f'/api/tourists -> {r.status_code}, {len(r.content) / 1024:.0f} KB in {(time.time() - s) * 1000:.0f} ms')

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--url', default='http://localhost:8000')
    p.add_argument('--travellers', type=int, default=50)
    p.add_argument('--fixes', type=int, default=20)
    p.add_argument('--concurrency', type=int, default=32)
    p.add_argument('--ops-token', default='')
    asyncio.run(main(p.parse_args()))

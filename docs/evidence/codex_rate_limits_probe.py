import json, subprocess, sys, time, select
p = subprocess.Popen(["codex","app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
def send(o): p.stdin.write(json.dumps(o)+"\n"); p.stdin.flush()
def recv(deadline):
    while time.time()<deadline:
        r,_,_=select.select([p.stdout],[],[],0.5)
        if r:
            line=p.stdout.readline()
            if not line: return None
            try: return json.loads(line)
            except ValueError: continue
    return None
send({"id":1,"method":"initialize","params":{"clientInfo":{"name":"agent-mindmap-quota-probe","title":"probe","version":"0.0.1"}}})
dl=time.time()+20; resp=None
while time.time()<dl:
    m=recv(dl)
    if m is None: break
    if m.get("id")==1: resp=m; break
print("initialize ok:", bool(resp and "result" in resp), "| result keys:", sorted((resp or {}).get("result",{}).keys()) if resp else None)
send({"method":"initialized"})
send({"id":2,"method":"account/rateLimits/read"})
dl=time.time()+25; out=None
while time.time()<dl:
    m=recv(dl)
    if m is None: break
    if m.get("id")==2: out=m; break
p.terminate()
if not out: print("no response"); sys.exit(1)
if "error" in out: print("error:", json.dumps(out["error"])[:300]); sys.exit(1)
r=out["result"]
def win(w): return None if not w else {k:w.get(k) for k in ("usedPercent","windowDurationMins","resetsAt")}
rl=r.get("rateLimits") or {}
print(json.dumps({"top_keys":sorted(r.keys()),"planType":rl.get("planType"),"limitId":rl.get("limitId"),"primary":win(rl.get("primary")),"secondary":win(rl.get("secondary")),"ordinaryUsageAllowed":r.get("ordinaryUsageAllowed"),"by_limit_ids":sorted((r.get("rateLimitsByLimitId") or {}).keys())}, indent=1))

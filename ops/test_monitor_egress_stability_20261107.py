#!/usr/bin/env python3
"""Offline regression tests for real monitor candidate; no network or state writes."""
import importlib.util
import inspect
import json
import sys
from unittest.mock import patch


def main(path):
    spec=importlib.util.spec_from_file_location("monitor_egress_v2_candidate",path)
    monitor=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(monitor)
    assert monitor.RECOVERY_STABLE_SECONDS==900
    body=inspect.getsource(monitor.collect_checks)
    assert '"--connect-timeout", "10"' in body
    assert '"--max-time", "18"' in body
    assert 'command_diagnostic(proxy_command, timeout=21)' in body
    assert 'proxy_retried = True' in body

    def step(state,ok,t):
        return monitor.update_states(state,{"proxy:telegram-egress":(ok,"HTTP 302" if ok else "curl exit 28")},t)
    state={"checks":{}}
    state,q=step(state,False,1000)
    assert not q['down']
    state,q=step(state,False,1120)
    assert len(q['down'])==1 and not q['up']
    monitor.mark_delivered(state,"down",["proxy:telegram-egress"],1120)
    # A burst of successes must NOT emit a premature UP.
    state,q=step(state,True,1240)
    state,q=step(state,True,1360)
    assert not q['up']
    # One failed request inside the recovery hold restarts the clock.
    state,q=step(state,False,1480)
    assert state["checks"]["proxy:telegram-egress"]["alarm"]
    assert not q['down']
    state,q=step(state,True,1600)
    for t in [1720,1840,1960,2080,2200,2320,2440]:
        state,q=step(state,True,t)
        assert not q['up']
    state,q=step(state,True,2560)
    assert len(q['up'])==1 and not state["checks"]["proxy:telegram-egress"]["alarm"]
    assert "15 минут" in q['up'][0][1]
    assert state["checks"]["proxy:telegram-egress"]["recovered_at"]==1600
    monitor.mark_delivered(state,"up",["proxy:telegram-egress"],2560)
    assert not state["checks"]["proxy:telegram-egress"]["notified"]
    # New genuine outage after a stable recovery must still alert promptly.
    state,q=step(state,False,2680)
    state,q=step(state,False,2800)
    assert len(q['down'])==1

    # Exercise real collect_checks' retry path with fake subprocesses.
    # Probe source contains exactly one network target and two attempts max.
    import tempfile
    import pathlib
    original_timeout=monitor.command_diagnostic
    calls=[]
    def fake_cmd(argv,*,timeout=7):
        if 'socks5h://127.0.0.1:1089' in argv:
            calls.append((argv,timeout))
            return (False,'000','curl exit 28') if len(calls)==1 else (True,'302','')
        return True,'200',''
    with patch.object(monitor,"SERVICES",()), \
         patch.object(monitor,"DOCKER_CONTAINERS",()), \
         patch.object(monitor,"SITES",()), \
         patch.object(monitor,"command_diagnostic",side_effect=fake_cmd), \
         patch.object(monitor.time,"sleep",return_value=None), \
         patch.object(monitor.socket,"create_connection",side_effect=OSError("synthetic")):
        result=monitor.collect_checks()
    assert result["proxy:telegram-egress"][0] is True
    assert "со второй попытки" in result["proxy:telegram-egress"][1]
    assert len(calls)==2 and all(t==21 for _,t in calls)
    assert all("--connect-timeout" in a and a[a.index("--connect-timeout")+1]=="10" for a,_ in calls)
    json.dumps(state,ensure_ascii=False)
    print("PASS: 10s connection timeout; retry on isolated failure; 15min stable recovery; chronology; no repeated DOWN during flapping; real down after recovery.")
    print("NETWORK_CALLS=0 TELEGRAM_MESSAGES=0 REAL_STATE_WRITES=0")


if __name__=="__main__":
    main(sys.argv[1])

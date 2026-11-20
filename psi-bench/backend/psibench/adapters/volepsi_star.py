"""Naive multi-party baseline built from VOLE-PSI: a star of two-party PSIs.

The Leader (last party) runs n-1 VOLE-PSI receiver instances in parallel, one per other party, and intersects
the pairwise results. All other parties are VOLE-PSI senders. This is NOT an equivalent of a multi-party PSI:
the Leader learns every pairwise intersection L ∩ S_i, not only the final intersection. It is a performance
reference for what a real MPSI protocol (BZS-MPSI) has to beat.
"""
from __future__ import annotations

from pathlib import Path

from .. import config, datasets
from .base import Adapter, Collected, PartyPlan, Plan, RunSpec
from .volepsi import parse_log

BASE_PORT = 1212

LEADER_SCRIPT = r"""
set -u
FE={fe}
N={n}
LEADER_IP={ip}
pids=()
for i in $(seq 0 $((N-2))); do
  $FE -in /data/party_$((N-1)).csv -r 1 -out /out/pair_$i.csv -ip $LEADER_IP:$(({base}+i)) -v > /out/recv_$i.log 2>&1 &
  pids+=($!)
done
rc=0
for p in "${{pids[@]}}"; do wait $p || rc=1; done
if [ $rc -ne 0 ]; then exit $rc; fi
export LC_ALL=C
sort /out/pair_0.csv > /tmp/cur.txt
for i in $(seq 1 $((N-2))); do
  sort /out/pair_$i.csv > /tmp/next.txt
  comm -12 /tmp/cur.txt /tmp/next.txt > /tmp/merged.txt
  mv /tmp/merged.txt /tmp/cur.txt
done
cp /tmp/cur.txt /out/result.csv
"""


class VolePsiStarAdapter(Adapter):
    name = "volepsi-star"
    min_parties = 3
    max_parties = None

    def plan(self, spec: RunSpec) -> Plan:
        self.validate(spec)
        if not spec.dataset_dir:
            raise ValueError("volepsi-star needs input files")
        n = spec.n_parties
        leader = n - 1
        leader_ip = config.party_ip(leader)
        fe = config.FRONTEND_IN_IMAGE["volepsi"]
        img = config.IMAGES["volepsi"]
        parties = []
        for i in range(n - 1):
            argv = [fe, "-in", f"/data/party_{i}.csv", "-r", "0", "-out", "/out/ignored.csv",
                    "-ip", f"{leader_ip}:{BASE_PORT + i}", "-v"]
            parties.append(PartyPlan(i, "sender", "docker", argv, image=img, ip=config.party_ip(i),
                                     wait_for=[f"listen_p{leader}_{BASE_PORT + i}"]))
        script = LEADER_SCRIPT.format(fe=fe, n=n, ip=leader_ip, base=BASE_PORT)
        parties.append(PartyPlan(leader, "leader (n-1 receivers)", "docker", ["bash", "-c", script], image=img,
                                 ip=leader_ip, announce=[BASE_PORT + i for i in range(n - 1)]))
        # the leader's rusage only reports its largest child; the container's peak covers all receivers
        return Plan(parties=parties, use_cgroup_peak=True)

    def collect(self, spec: RunSpec, plan: Plan, run_dir: Path, metrics: dict[int, dict]) -> Collected:
        c = Collected()
        leader = spec.n_parties - 1
        for p in plan.parties:
            if p.idx == leader:
                logs = sorted((run_dir / f"party_{leader}").glob("recv_*.log"))
                c.party_reported[p.idx] = {"receiver_logs": len(logs),
                                           "instances": [parse_log(l.read_text(errors="replace")) for l in logs[:1]]}
            else:
                log = run_dir / f"party_{p.idx}" / "stdout.log"
                c.party_reported[p.idx] = parse_log(log.read_text(errors="replace")) if log.exists() else {}
        c.reported = {
            "mode": "naive star of two-party VOLE-PSI (n-1 parallel instances at the leader)",
            "privacy_note": "leader learns each pairwise intersection, not only the final one",
        }
        c.check = datasets.check_result(spec.dataset_dir, run_dir / f"party_{leader}" / "result.csv")
        return c

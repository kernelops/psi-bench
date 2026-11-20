"""Generate two 32-hex-char CSV sets with a known intersection (ground truth)."""
import secrets
import sys
from pathlib import Path

out = Path(sys.argv[1])
n_common, n_recv, n_send = int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
out.mkdir(parents=True, exist_ok=True)
common = [secrets.token_hex(16) for _ in range(n_common)]
recv = common + [secrets.token_hex(16) for _ in range(n_recv - n_common)]
send = common + [secrets.token_hex(16) for _ in range(n_send - n_common)]
(out / "recv.csv").write_text("\n".join(recv) + "\n")
(out / "send.csv").write_text("\n".join(send) + "\n")
(out / "truth.txt").write_text("\n".join(sorted(common)) + "\n")
print(f"wrote {out}: recv={len(recv)} send={len(send)} common={len(common)}")

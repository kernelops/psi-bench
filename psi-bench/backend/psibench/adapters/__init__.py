from __future__ import annotations

from .base import Adapter


def get_adapter(protocol: str) -> Adapter:
    # imported lazily so a missing build of one protocol does not break the others
    if protocol == "volepsi":
        from .volepsi import VolePsiAdapter
        return VolePsiAdapter()
    if protocol == "bzs":
        from .bzs import BzsAdapter
        return BzsAdapter()
    if protocol in ("pepsi", "pepsi-large"):
        from .pepsi import PepsiAdapter
        return PepsiAdapter(protocol)
    if protocol == "pepsi-e2e":
        from .pepsi_e2e import PepsiE2EAdapter
        return PepsiE2EAdapter()
    if protocol == "bzs-perf":
        from .bzs_perf import BzsPerfAdapter
        return BzsPerfAdapter()
    if protocol == "volepsi-perf":
        from .volepsi_perf import VolePsiPerfAdapter
        return VolePsiPerfAdapter()
    if protocol == "volepsi-star":
        from .volepsi_star import VolePsiStarAdapter
        return VolePsiStarAdapter()
    raise ValueError(f"unknown protocol {protocol!r}; choose one of {', '.join(PROTOCOLS)}")


# "pepsi"/"pepsi-large" = upstream benchmark binaries (synthetic data); "pepsi-e2e" = real-file driver
PROTOCOLS = ("volepsi", "bzs", "pepsi", "pepsi-large", "pepsi-e2e", "volepsi-perf", "bzs-perf", "volepsi-star")
# protocols that generate their own random inputs and take no dataset files
SYNTHETIC_ONLY = ("pepsi", "pepsi-large", "volepsi-perf", "bzs-perf")

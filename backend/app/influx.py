"""InfluxDB Flux queries with counter-reset handling.

Counter resets (e.g. a node reboot resetting command counters) are detected
when a delta goes negative: the delta is floored at 0 and a reset annotation
is attached to that point.
"""
from __future__ import annotations

from typing import Any

import httpx


class InfluxClient:
    def __init__(self, url: str, org: str, token: str):
        self.url = url.rstrip("/")
        self.org = org
        self.token = token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Token {self.token}",
                "Content-Type": "application/vnd.flux", "Accept": "application/csv"}

    async def query(self, flux: str) -> list[dict[str, Any]]:
        """Execute Flux, parse annotated CSV into list of records."""
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{self.url}/api/v2/query",
                             params={"org": self.org},
                             headers=self._headers(),
                             content=flux)
            r.raise_for_status()
            return parse_annotated_csv(r.text)

    # ---- domain queries ----
    async def frames_history(self, node_id: int, days: int = 7) -> list[dict[str, Any]]:
        flux = f'''
from(bucket: "zwave")
  |> range(start: -{days}d)
  |> filter(fn: (r) => r._measurement == "zwave_frames" and r.node_id == "{node_id}")
  |> aggregateWindow(every: 1h, fn: sum, createEmpty: false)
'''
        return await self.query(flux)

    async def rssi_history(self, node_id: int, days: int = 7) -> list[dict[str, Any]]:
        flux = f'''
from(bucket: "zwave")
  |> range(start: -{days}d)
  |> filter(fn: (r) => r._measurement == "zwave_rssi" and r.node_id == "{node_id}")
  |> aggregateWindow(every: 5m, fn: mean, createEmpty: false)
'''
        return await self.query(flux)

    async def controller_history(self, days: int = 7) -> list[dict[str, Any]]:
        flux = f'''
from(bucket: "zwave")
  |> range(start: -{days}d)
  |> filter(fn: (r) => r._measurement == "zwave_controller")
'''
        return await self.query(flux)

    async def drops_history(self, node_id: int, days: int = 7) -> list[dict[str, Any]]:
        flux = f'''
from(bucket: "zwave")
  |> range(start: -{days}d)
  |> filter(fn: (r) => r._measurement == "zwave_drops" and r.node_id == "{node_id}")
'''
        return await self.query(flux)

    async def latest_cumulative(self, measurement: str, field: str,
                                node_id: int | None = None) -> float:
        filt = f' and r.node_id == "{node_id}"' if node_id is not None else ""
        flux = f'''
from(bucket: "zwave")
  |> range(start: -30d)
  |> filter(fn: (r) => r._measurement == "{measurement}" and r._field == "{field}"{filt})
  |> last()
'''
        rows = await self.query(flux)
        for r in rows:
            try:
                return float(r.get(field, r.get("_value")))
            except (TypeError, ValueError):
                continue
        return 0.0


def compute_deltas(points: list[dict[str, Any]], value_key: str = "_value",
                   time_key: str = "_time") -> list[dict[str, Any]]:
    """Convert cumulative counters into deltas with counter-reset handling:
    negative deltas are floored at 0 and annotated reset=True."""
    out: list[dict[str, Any]] = []
    prev: float | None = None
    for p in points:
        try:
            cur = float(p.get(value_key, 0))
        except (TypeError, ValueError):
            cur = 0.0
        rec = dict(p)
        if prev is None:
            rec["delta"] = 0
            rec["reset"] = False
        else:
            d = cur - prev
            if d < 0:
                rec["delta"] = 0
                rec["reset"] = True
            else:
                rec["delta"] = d
                rec["reset"] = False
        rec["cumulative"] = cur
        out.append(rec)
        prev = cur
    return out


def parse_annotated_csv(text: str) -> list[dict[str, Any]]:
    """Parse InfluxDB annotated CSV (#group,#datatype,... then tables separated
    by blank lines with #constant header rows)."""
    records: list[dict[str, Any]] = []
    header: list[str] | None = None
    for raw in text.splitlines():
        line = raw.rstrip("\n").rstrip("\r")
        if not line:
            header = None
            continue
        if line.startswith("#"):
            continue
        cols = line.split(",")
        if header is None:
            header = cols
            continue
        rec: dict[str, Any] = {}
        for k, v in zip(header, cols):
            if k in ("", "result", "table"):
                continue
            rec[k] = v
        records.append(rec)
    return records

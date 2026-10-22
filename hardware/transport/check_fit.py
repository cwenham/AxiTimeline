"""Report each STL's size as laid out for printing, and whether it fits the Prusa Core One's bed.

The part's height is its Z extent; its footprint may be turned 90 degrees on the bed.
"""

import struct
import sys
from pathlib import Path

BED = (250.0, 220.0, 270.0)


def vertices(path: Path):
    data = path.read_bytes()
    if data[:5] == b"solid" and b"facet" in data[:400]:
        for line in data.decode("ascii", "replace").splitlines():
            parts = line.split()
            if parts and parts[0] == "vertex":
                yield tuple(float(v) for v in parts[1:4])
    else:
        (count,) = struct.unpack_from("<I", data, 80)
        for i in range(count):
            values = struct.unpack_from("<12f", data, 84 + i * 50)
            for k in range(3):
                yield values[3 + 3 * k : 6 + 3 * k]


def main(paths: list[str]) -> int:
    failed = False
    for name in paths:
        path = Path(name)
        points = list(vertices(path))
        if not points:
            print(f"{path.stem:22s} EMPTY")
            failed = True
            continue
        lo = [min(p[i] for p in points) for i in range(3)]
        hi = [max(p[i] for p in points) for i in range(3)]
        size = [hi[i] - lo[i] for i in range(3)]
        footprint_ok = (size[0] <= BED[0] and size[1] <= BED[1]) or (size[1] <= BED[0] and size[0] <= BED[1])
        ok = footprint_ok and size[2] <= BED[2] and abs(lo[2]) < 0.05
        note = "" if abs(lo[2]) < 0.05 else f"  (lowest point at z={lo[2]:.2f}, not on the bed)"
        print(f"{path.stem:22s} {size[0]:6.1f} x {size[1]:6.1f} x {size[2]:6.1f}  {'fits' if ok else 'DOES NOT FIT'}{note}")
        failed |= not ok
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

import zipfile
from typing import BinaryIO, Iterator
from lxml import etree

def norm_ts(value: str | None) -> str | None:
    if not value:
        return None
    return value[:19]

def to_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None

def open_export(path: str) -> BinaryIO:
    if path.lower().endswith(".zip"):
        zf = zipfile.ZipFile(path)
        name = next((n for n in zf.namelist() if n.endswith("export.xml")), None)
        if name is None:
            zf.close()
            raise ValueError("No export.xml found in zip")
        return zf.open(name)
    return open(path, "rb")

def _minutes_to_seconds(v: str | None, unit: str | None) -> float | None:
    n = to_float(v)
    if n is None:
        return None
    return n * 60.0 if (unit or "min").startswith("min") else n

def iter_elements(fileobj: BinaryIO) -> Iterator[tuple[str, dict]]:
    context = etree.iterparse(fileobj, events=("end",), tag=("Record", "Workout"))
    for _, el in context:
        if el.tag == "Record":
            v = el.get("value")
            yield ("record", {
                "type": el.get("type"),
                "source_name": el.get("sourceName"),
                "unit": el.get("unit"),
                "value_num": to_float(v),
                "value_text": v if to_float(v) is None else None,
                "start_time": norm_ts(el.get("startDate")),
                "end_time": norm_ts(el.get("endDate")),
            })
        else:  # Workout
            yield ("workout", {
                "activity_type": el.get("workoutActivityType"),
                "duration_sec": _minutes_to_seconds(el.get("duration"), el.get("durationUnit")),
                "energy_kcal": to_float(el.get("totalEnergyBurned")),
                "distance": to_float(el.get("totalDistance")),
                "unit": el.get("totalDistanceUnit"),
                "start_time": norm_ts(el.get("startDate")),
                "end_time": norm_ts(el.get("endDate")),
            })
        # free memory: clear element and its preceding siblings
        el.clear()
        while el.getprevious() is not None:
            del el.getparent()[0]

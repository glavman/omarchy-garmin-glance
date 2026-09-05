#!/usr/bin/env python3
"""Read-only InfluxDB 1.x adapter, JSON contract v1 (Python 3.9+).

Config: private JSON object with url, database, username, password, timezone,
and tags (string-to-string equality filters). Defaults require no config.
Only literal loopback addresses/localhost may use HTTP; remote URLs need HTTPS.
Credentials are sent only in Basic Authorization, never in query parameters.

Summary lookup uses the latest valid nonnull value per field within 30 days.
Body Battery is fresh through 2 hours,
steps on the current local date, and sleep/HRV through 36 hours after sleep end.
Charts show 24 hours of Body Battery and seven local dates of steps/sleep;
daily points use the latest record, never a sum. Missing chart days are null.
dailyStepGoal is NOT written by the inspected upstream, so goal is omitted.

GROUP BY * preserves source tags. Multiple series or differing tag identities
across measurements are refused. Untagged, already-merged data cannot be
disambiguated here. A read-only database user is recommended as defense in depth.
doctor probes the same SELECTs but emits no health values and never uses cache.
Exit codes: 0 for usable results (including partial/cached/demo), 1 for error.
"""

import argparse
import base64
import copy
from datetime import datetime, time, timedelta, timezone
import fcntl
import hashlib
import http.client
import ipaddress
import json
import math
import os
from pathlib import Path
import signal
import socket
import stat
import sys
import tempfile
from time import monotonic
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


UTC = timezone.utc
MAX_BYTES = 1024 * 1024
TIMEOUT = 5
FETCH_BUDGET = 10
DEFAULTS = {"url": "http://127.0.0.1:8086", "database": "GarminStats",
            "timezone": "Europe/Dublin", "username": "", "password": "", "tags": {}}
FIELDS = {"BodyBatteryIntraday": ("BodyBatteryLevel",),
          "DailyStats": ("totalSteps",),
          "SleepSummary": ("sleepScore", "avgOvernightHrv")}
METRICS = {"bodyBattery": ("BodyBatteryIntraday", "BodyBatteryLevel", "score"),
           "steps": ("DailyStats", "totalSteps", "steps"),
           "sleep": ("SleepSummary", "sleepScore", "score"),
           "hrv": ("SleepSummary", "avgOvernightHrv", "ms")}


class Failure(Exception):
    """Only these stable codes may cross the CLI boundary."""


def iso(value):
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone")
    return parsed.astimezone(UTC)


def number(value, field):
    return ((type(value) is int or type(value) is float and math.isfinite(value))
            and value >= 0
            and (field not in ("BodyBatteryLevel", "sleepScore") or value <= 100))


def decode(raw):
    def invalid(_):
        raise ValueError("constant")
    return json.loads(raw, parse_constant=invalid)


def private_read(path, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077):
            raise ValueError("permissions")
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("size")
    return decode(raw)


def load_config(path=None):
    explicit = path is not None
    path = Path(path) if path is not None else Path.home() / ".config/omarchy-garmin-glance/connection.json"
    config = copy.deepcopy(DEFAULTS)
    try:
        try:
            supplied = private_read(path, 16384)
        except FileNotFoundError:
            # An explicitly requested config must exist.
            if explicit:
                raise ValueError("missing")
            supplied = {}
        if not isinstance(supplied, dict) or supplied.keys() - DEFAULTS.keys():
            raise ValueError("config")
        config.update(supplied)
        for key in DEFAULTS.keys() - {"tags"}:
            if not isinstance(config[key], str) or len(config[key]) > 2048:
                raise ValueError("string")
        if not config["database"] or not config["timezone"]:
            raise ValueError("empty")
        tags = config["tags"]
        if not isinstance(tags, dict) or len(tags) > 16:
            raise ValueError("tags")
        for key, value in tags.items():
            if (not isinstance(key, str) or not isinstance(value, str) or not key
                    or len(key) > 128 or len(value) > 256
                    or any(ord(c) < 32 for c in key + value)):
                raise ValueError("tag")
        url = urllib.parse.urlsplit(config["url"])
        if (url.scheme not in ("http", "https") or not url.hostname
                or url.username is not None or url.password is not None
                or url.query or url.fragment or url.path not in ("", "/")
                or any(ord(c) <= 32 for c in config["url"])):
            raise ValueError("url")
        port = url.port
        if port == 0:
            raise ValueError("port")
        host = url.hostname
        if url.scheme == "http":
            if host == "localhost":
                host = "127.0.0.1"  # Never resolve localhost through DNS.
            elif not ipaddress.ip_address(host).is_loopback:
                raise ValueError("remote_http")
        host = "[" + host + "]" if ":" in host else host
        config["url"] = url.scheme + "://" + host + (":" + str(port) if port else "")
        ZoneInfo(config["timezone"])
        return config
    except (OSError, ValueError, TypeError, RecursionError, ZoneInfoNotFoundError):
        raise Failure("invalid_config") from None


def empty(now, zone, status="error", error=None):
    return {"schemaVersion": 1, "status": status, "error": error,
            "fetchedAt": iso(now), "timezone": zone,
            "metrics": {key: {"value": None, "time": None, "date": None,
                               "state": "missing", "unit": spec[2], "expiresAt": None}
                        for key, spec in METRICS.items()},
            "charts": {"bodyBattery": [], "steps": [], "sleep": []},
            "chartsFetchedAt": None}


def refresh_states(result, now):
    zone = ZoneInfo(result["timezone"])
    for key, metric in result["metrics"].items():
        if metric["value"] is None:
            metric["state"] = "missing"
            metric["expiresAt"] = None
            continue
        when = timestamp(metric["time"])
        metric["date"] = when.astimezone(zone).date().isoformat()
        deadline = (datetime.combine(when.astimezone(zone).date() + timedelta(days=1), time(), zone)
                    if key == "steps" else when + timedelta(hours=2 if key == "bodyBattery" else 36))
        metric["expiresAt"] = iso(deadline)
        age = now - when
        fresh = (metric["date"] == now.astimezone(zone).date().isoformat()
                 if key == "steps" else age <= timedelta(hours=2 if key == "bodyBattery" else 36))
        metric["state"] = "fresh" if age >= timedelta(0) and fresh else "stale"


def quoted(value, quote):
    return quote + value.replace("\\", "\\\\").replace(quote, "\\" + quote) + quote


def queries(config, now, charts):
    zone = ZoneInfo(config["timezone"])
    start = datetime.combine(now.astimezone(zone).date() - timedelta(days=6), time(), zone)
    specs = [(name, now - timedelta(days=30), 1, False, (field,))
             for name, field, _ in METRICS.values()]
    if charts:
        specs.extend((name, now - timedelta(hours=24) if name == "BodyBatteryIntraday" else start,
                      2000 if name == "BodyBatteryIntraday" else 1000, True, FIELDS[name]) for name in FIELDS)
    statements = []
    for name, since, limit, is_chart, fields in specs:
        conditions = ["time >= '" + iso(since) + "'", "time <= '" + iso(now) + "'"]
        if not is_chart:
            # Field predicates skip sparse rows without losing the field's timestamp.
            conditions.append(quoted(fields[0], '"') + " >= 0")
            if fields[0] in ("BodyBatteryLevel", "sleepScore"):
                conditions.append(quoted(fields[0], '"') + " <= 100")
        conditions.extend(quoted(k, '"') + " = " + quoted(v, "'") for k, v in sorted(config["tags"].items()))
        statements.append("SELECT " + ",".join(quoted(f, '"') for f in fields)
                          + " FROM " + quoted(name, '"') + " WHERE " + " AND ".join(conditions)
                          + " GROUP BY * ORDER BY time DESC LIMIT " + str(limit + int(is_chart)) + " SLIMIT 2")
    return specs, statements


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Failure("redirect_refused")


def request(config, query, timeout=TIMEOUT):
    def timed_out(*_):
        raise TimeoutError

    url = config["url"] + "/query?" + urllib.parse.urlencode({"db": config["database"], "q": query})
    headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
    if config["username"] or config["password"]:
        token = base64.b64encode((config["username"] + ":" + config["password"]).encode()).decode("ascii")
        headers["Authorization"] = "Basic " + token
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    previous_handler = signal.signal(signal.SIGALRM, timed_out)
    try:
        # Socket timeouts alone do not bound DNS, headers, or a trickling body.
        signal.setitimer(signal.ITIMER_REAL, timeout)
        with opener.open(urllib.request.Request(url, headers=headers, method="GET"), timeout=timeout) as response:
            if response.status != 200:
                raise Failure("http_error")
            size = response.headers.get("Content-Length")
            if size is not None and (int(size) < 0 or int(size) > MAX_BYTES):
                raise Failure("response_too_large")
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise Failure("response_too_large")
            if size is not None and len(raw) != int(size):
                raise Failure("invalid_response")
            return decode(raw)
    except urllib.error.HTTPError as exc:
        code = "auth_error" if exc.code in (401, 403) else "redirect_refused" if 300 <= exc.code < 400 else "http_error"
        exc.close()
        raise Failure(code) from None
    except (TimeoutError, socket.timeout):
        raise Failure("timeout") from None
    except urllib.error.URLError as exc:
        raise Failure("timeout" if isinstance(exc.reason, TimeoutError) else "network_error") from None
    except (ValueError, UnicodeError, RecursionError, http.client.HTTPException):
        raise Failure("invalid_response") from None
    except OSError:
        raise Failure("network_error") from None
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def fetch(config, now, charts=False):
    deadline = monotonic() + FETCH_BUDGET
    specs, statements = queries(config, now, charts)
    payload = request(config, ";".join(statements))
    result = empty(now, config["timezone"], "ok")
    sources = set()
    rows_by_spec = []
    try:
        if not isinstance(payload, dict):
            raise ValueError("object")
        if "error" in payload:
            raise Failure("query_error")
        results = payload["results"]
        if not isinstance(results, list) or len(results) != len(specs):
            raise ValueError("results")
        execution_failed = False
        for index, ((name, since, limit, is_chart, fields), item) in enumerate(zip(specs, results)):
            if (not isinstance(item, dict) or type(item.get("statement_id")) is not int
                    or item["statement_id"] != index):
                raise ValueError("statement")
            # InfluxDB stops the batch at an execution error. Retry only skipped
            # statements, once each: at most len(specs) requests including the batch.
            remaining = deadline - monotonic()
            if item.get("error") == "not executed" and execution_failed and remaining > 0:
                try:
                    retry = request(config, statements[index], timeout=min(TIMEOUT, remaining))
                except Failure:
                    pass  # Keep earlier live results even if a recovery request fails.
                else:
                    if not isinstance(retry, dict):
                        raise ValueError("retry")
                    if "error" not in retry:
                        recovered = retry["results"]
                        if (not isinstance(recovered, list) or len(recovered) != 1
                                or not isinstance(recovered[0], dict)
                                or type(recovered[0].get("statement_id")) is not int
                                or recovered[0]["statement_id"] != 0):
                            raise ValueError("retry statement")
                        item = {**recovered[0], "statement_id": index}
            if "error" in item:
                if item["error"] != "not executed":
                    execution_failed = True
                result.update(status="partial", error="query_error")
                rows_by_spec.append(None)
                continue
            if item.get("partial"):
                raise Failure("truncated_response")
            series = item.get("series", [])
            if not isinstance(series, list):
                raise ValueError("series")
            if len(series) > 1:
                raise Failure("ambiguous_source")
            rows = []
            for entry in series:
                if entry["name"] != name:
                    raise ValueError("measurement")
                if entry.get("partial"):
                    raise Failure("truncated_response")
                tags = entry.get("tags", {})
                if (not isinstance(tags, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                                     for k, v in tags.items())):
                    raise ValueError("tags")
                if any(tags.get(k) != v for k, v in config["tags"].items()):
                    raise Failure("ambiguous_source")
                sources.add(json.dumps(tags, sort_keys=True, separators=(",", ":")))
                if len(sources) > 1:
                    raise Failure("ambiguous_source")
                columns, values = entry["columns"], entry["values"]
                if (not isinstance(columns, list) or not all(isinstance(c, str) for c in columns)
                        or len(set(columns)) != len(columns) or "time" not in columns
                        or set(columns) - {"time", *fields} or not isinstance(values, list)):
                    raise ValueError("columns")
                if len(values) > limit:
                    raise Failure("truncated_response")
                for values_row in values:
                    if not isinstance(values_row, list) or len(values_row) != len(columns):
                        raise ValueError("row")
                    row = dict(zip(columns, values_row))
                    when = timestamp(row["time"])
                    if not since <= when <= now:
                        raise ValueError("range")
                    for field in fields:
                        if row.get(field) is not None and not number(row[field], field):
                            row[field] = None
                            result["status"] = "partial"
                    row["time"] = iso(when)
                    rows.append(row)
            rows.sort(key=lambda row: timestamp(row["time"]), reverse=True)
            rows_by_spec.append(rows)
    except (KeyError, ValueError, TypeError, OverflowError):
        raise Failure("invalid_response") from None
    zone = ZoneInfo(config["timezone"])
    for index, (key, (name, field, _)) in enumerate(METRICS.items()):
        rows = rows_by_spec[index]
        if rows:
            row = rows[0]
            result["metrics"][key].update(value=row.get(field), time=row["time"],
                                          date=timestamp(row["time"]).astimezone(zone).date().isoformat())
    refresh_states(result, now)
    if any(m["state"] != "fresh" for m in result["metrics"].values()):
        result["status"] = "partial"
    if charts:
        if any(rows is not None for rows in rows_by_spec[4:]):
            result["chartsFetchedAt"] = iso(now)
        result["charts"]["bodyBattery"] = [{"time": row["time"], "value": row.get("BodyBatteryLevel")}
                                             for row in reversed(rows_by_spec[4] or [])]
        for key, index, field in (("steps", 5, "totalSteps"), ("sleep", 6, "sleepScore")):
            if rows_by_spec[index] is None:
                continue
            days = {}
            for row in rows_by_spec[index]:
                day = timestamp(row["time"]).astimezone(zone).date().isoformat()
                if day not in days:
                    days[day] = row.get(field)
            today = now.astimezone(zone).date()
            result["charts"][key] = [{"date": (today - timedelta(days=n)).isoformat(),
                                       "value": days.get((today - timedelta(days=n)).isoformat())}
                                      for n in range(6, -1, -1)]
    return result, next(iter(sources), None)


def cache_location(config):
    identity = {k: v for k, v in config.items() if k != "password"}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    root = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "omarchy-garmin-glance"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise Failure("cache_error")
    return root / (key + ".json"), key


def read_cache(path, key, config, now):
    try:
        envelope = private_read(path, MAX_BYTES)
        if not isinstance(envelope, dict) or envelope["identity"] != key:
            return None
        result = envelope["data"]
        if (not isinstance(result, dict)
                or not isinstance(result.get("metrics"), dict) or not isinstance(result.get("charts"), dict)
                or result["schemaVersion"] != 1 or result["timezone"] != config["timezone"]
                or result["status"] not in ("ok", "partial")
                or result["error"] not in (None, "query_error")
                or timestamp(result["fetchedAt"]) > now
                or set(result["metrics"]) != set(METRICS)
                or set(result["charts"]) != {"bodyBattery", "steps", "sleep"}
                or not (envelope["source"] is None or isinstance(envelope["source"], str))):
            return None
        # Reconstruct instead of forwarding unrecognized cache content to the UI.
        clean = empty(timestamp(result["fetchedAt"]), config["timezone"], result["status"], result["error"])
        for metric, spec in METRICS.items():
            value = result["metrics"][metric]
            if value["value"] is not None and not number(value["value"], spec[1]):
                return None
            when = timestamp(value["time"]) if value["time"] is not None else None
            if (value["value"] is not None and when is None) or (when and when > timestamp(result["fetchedAt"])):
                return None
            clean["metrics"][metric].update(value=value["value"], time=iso(when) if when else None,
                                             date=when.astimezone(ZoneInfo(config["timezone"])).date().isoformat() if when else None)
        chart_time = result["chartsFetchedAt"]
        if chart_time is not None:
            if timestamp(chart_time) > timestamp(result["fetchedAt"]):
                return None
            clean["chartsFetchedAt"] = iso(timestamp(chart_time))
        for chart, points in result["charts"].items():
            if not isinstance(points, list) or len(points) > (2000 if chart == "bodyBattery" else 7):
                return None
            if points and chart_time is None:
                return None
            axis = "time" if chart == "bodyBattery" else "date"
            for point in points:
                if point["value"] is not None and not number(point["value"], METRICS[chart][1]):
                    return None
                coordinate = iso(timestamp(point[axis])) if axis == "time" else datetime.strptime(point[axis], "%Y-%m-%d").date().isoformat()
                clean["charts"][chart].append({axis: coordinate, "value": point["value"]})
        refresh_states(clean, now)
        return {"data": clean, "source": envelope["source"]}
    except (OSError, ValueError, KeyError, TypeError, OverflowError, RecursionError):
        return None


def write_cache(path, key, result, source):
    raw = json.dumps({"identity": key, "source": source, "data": result}, allow_nan=False).encode()
    if len(raw) > MAX_BYTES:
        raise Failure("cache_error")
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=".cache-", dir=path.parent)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def run(command, config, now, charts=False):
    if command == "doctor":
        result, _ = fetch(config, now)
        return empty(now, config["timezone"], result["status"], result["error"])
    path, key = cache_location(config)
    fd = os.open(path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(fd, "a") as lock:
        info = os.fstat(lock.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise Failure("cache_error")
        previous = read_cache(path, key, config, now)
        if command == "cache":
            if previous is None:
                raise Failure("cache_miss")
            result = previous["data"]
            result["status"] = "cached"
        else:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                if previous is None:
                    raise Failure("fetch_locked") from None
                result = previous["data"]
                result.update(status="cached", error="fetch_locked")
            else:
                try:
                    result, source = fetch(config, now, charts)
                    if previous is not None and (source is None or source == previous["source"]):
                        source = previous["source"]
                        for metric, value in result["metrics"].items():
                            if value["value"] is None:
                                result["metrics"][metric] = copy.deepcopy(previous["data"]["metrics"][metric])
                        refresh_states(result, now)
                        if not charts or result["chartsFetchedAt"] is None or all(
                                value["value"] is None for points in result["charts"].values() for value in points):
                            result["charts"] = previous["data"]["charts"]
                            result["chartsFetchedAt"] = previous["data"]["chartsFetchedAt"]
                        elif result["error"] == "query_error":
                            for chart, points in result["charts"].items():
                                if not points and previous["data"]["charts"][chart]:
                                    result["charts"][chart] = previous["data"]["charts"][chart]
                                    # The bundle timestamp must not rejuvenate retained points.
                                    result["chartsFetchedAt"] = previous["data"]["chartsFetchedAt"]
                    write_cache(path, key, result, source)
                except (Failure, OSError) as exc:
                    code = str(exc) if isinstance(exc, Failure) else "cache_error"
                    if previous is None:
                        raise Failure(code) from None
                    result = previous["data"]
                    result.update(status="cached", error=code)
        if not charts:
            result = copy.deepcopy(result)
            result["charts"] = {"bodyBattery": [], "steps": [], "sleep": []}
            result["chartsFetchedAt"] = None
        return result


def demo(now, charts):
    result = empty(now, DEFAULTS["timezone"], "demo")
    zone = ZoneInfo(result["timezone"])
    for key, value in {"bodyBattery": 73, "steps": 4321, "sleep": 82, "hrv": 48}.items():
        when = now - timedelta(hours=8) if key in ("sleep", "hrv") else now
        result["metrics"][key].update(value=value, time=iso(when), date=when.astimezone(zone).date().isoformat())
    refresh_states(result, now)
    if charts:
        result["chartsFetchedAt"] = iso(now)
        result["charts"]["bodyBattery"] = [
            {"time": iso(now - timedelta(minutes=n * 5)),
             "value": round(55 + 18 * math.cos(n / 288 * 2 * math.pi), 1)}
            for n in range(288, -1, -1)]
        for key, value in (("steps", 4321), ("sleep", 82)):
            result["charts"][key] = [{"date": (now.astimezone(zone).date() - timedelta(days=n)).isoformat(),
                                       "value": value - n} for n in range(6, -1, -1)]
    return result


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Failure("invalid_arguments")


def main(argv=None):
    now = datetime.now(UTC)
    zone = DEFAULTS["timezone"]
    try:
        parser = Parser(add_help=False, allow_abbrev=False)
        parser.add_argument("command", choices=("fetch", "doctor", "cache"))
        parser.add_argument("--config")
        parser.add_argument("--charts", action="store_true")
        parser.add_argument("--demo", action="store_true")
        args = parser.parse_args(argv)
        if (args.demo and args.command != "fetch") or (args.charts and args.command == "doctor"):
            raise Failure("invalid_arguments")
        if args.demo:
            result = demo(now, args.charts)
        else:
            config = load_config(args.config)
            zone = config["timezone"]
            result = run(args.command, config, now, args.charts)
    except Failure as exc:
        result = empty(now, zone, error=str(exc))
    except OSError:
        result = empty(now, zone, error="cache_error")
    except Exception:
        # Never expose exception text, URLs, credentials, or server response bodies.
        result = empty(now, zone, error="internal_error")
    print(json.dumps(result, allow_nan=False, separators=(",", ":")))
    return int(result["status"] == "error")


if __name__ == "__main__":
    sys.exit(main())

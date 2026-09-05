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
History uses seven completed source-local dates, including daily peak Body
Battery, and latest nonnull sleep/HRV per field. Activity is a single raw summary.
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
HISTORY_FIELDS = {"bodyBattery": "bodyBatteryHighestValue", "steps": "totalSteps",
                  "sleep": "sleepScore", "hrv": "avgOvernightHrv"}
WELLNESS = {"sleepDuration": ("SleepSummary", "sleepTimeSeconds", "seconds"),
            "restingHeartRate": ("DailyStats", "restingHeartRate", "bpm"),
            "trainingReadiness": ("TrainingReadiness", "score", "score"),
            "stress": ("StressIntraday", "stressLevel", "score")}
SUPPLEMENTAL_FIELDS = {key: spec[1] for key, spec in WELLNESS.items()}
ACTIVITY_DETAILS = ("averageHR", "maxHR", "movingDuration", "averageSpeed", "maxSpeed",
                    "elevationGain", "elevationLoss", "aerobicTrainingEffect",
                    "anaerobicTrainingEffect", "activityTrainingLoad")
ACTIVITY_FIELDS = {"type": "activityType", "durationSeconds": "elapsedDuration",
                   "distanceMeters": "distance", "calories": "calories", "bmrCalories": "bmrCalories",
                   **{field: field for field in ACTIVITY_DETAILS}}
ACTIVITIES_FIELDS = {key: ACTIVITY_FIELDS[key] for key in
                     ("type", "durationSeconds", "distanceMeters", "calories")}
OPTIONAL_ERRORS = {"query_error", "invalid_response", "truncated_response", "ambiguous_source",
                   "source_unavailable", "timeout", "network_error", "auth_error", "http_error",
                   "redirect_refused", "response_too_large"}


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
            and (field not in ("BodyBatteryLevel", "bodyBatteryHighestValue", "sleepScore",
                               "score", "stressLevel") or value <= 100))


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


def load_config(path=None, *, auto_demo=False):
    """Return None only for an absent default config when explicitly opted in."""
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
            if auto_demo:
                return None
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
    day_start = datetime.combine(now.astimezone(ZoneInfo(zone)).date(), time(), ZoneInfo(zone))
    return {"schemaVersion": 1, "status": status, "error": error,
            "fetchedAt": iso(now), "timezone": zone, "device": None,
            "sourceDayStart": iso(day_start), "sourceDayEnd": iso(day_start + timedelta(days=1)),
            "metrics": {key: {"value": None, "time": None, "date": None,
                               "state": "missing", "unit": spec[2], "expiresAt": None}
                        for key, spec in METRICS.items()},
            "charts": {"bodyBattery": [], "steps": [], "sleep": []},
            "chartsFetchedAt": None,
            "history": {key: [] for key in HISTORY_FIELDS}, "historyFetchedAt": None,
            "latestActivity": None, "activityFetchedAt": None,
            "activityError": None, "historyError": None,
            "activities": None, "activitiesFetchedAt": None, "activitiesError": None,
            "wellness": {key: {"value": None, "time": None, "date": None,
                                "state": "missing", "unit": spec[2], "expiresAt": None}
                         for key, spec in WELLNESS.items()},
            "wellnessFetchedAt": None, "wellnessError": None,
            "supplementalHistory": {key: [] for key in WELLNESS},
            "supplementalHistoryFetchedAt": None, "supplementalHistoryError": None,
            "stressSeries": [], "stressFetchedAt": None, "stressError": None}


def device_from_source(source):
    """Expose only the upstream Device label, which may be user-customized."""
    try:
        tags = decode(source)
    except (ValueError, TypeError, RecursionError):
        return None
    if (not isinstance(tags, dict)
            or any(not isinstance(k, str) or not isinstance(v, str) for k, v in tags.items())):
        return None
    name = tags.get("Device", "")
    if any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in name):
        return None
    name = name.strip()
    if not name or len(name) > 80 or not name.isprintable() or name.casefold() in ("unknown", "garmin"):
        return None
    return {"name": name, "source": "Device"}


def refresh_states(result, now):
    zone = ZoneInfo(result["timezone"])
    result["sourceDate"] = now.astimezone(zone).date().isoformat()
    day_start = datetime.combine(now.astimezone(zone).date(), time(), zone)
    result["sourceDayStart"] = iso(day_start)
    result["sourceDayEnd"] = iso(day_start + timedelta(days=1))
    for key, metric in {**result["metrics"], **result.get("wellness", {})}.items():
        if metric["value"] is None:
            metric["state"] = "missing"
            metric["expiresAt"] = None
            continue
        when = timestamp(metric["time"])
        metric["date"] = when.astimezone(zone).date().isoformat()
        daily = key in ("steps", "restingHeartRate", "trainingReadiness")
        hours = 2 if key in ("bodyBattery", "stress") else 36
        deadline = (datetime.combine(when.astimezone(zone).date() + timedelta(days=1), time(), zone)
                    if daily else when + timedelta(hours=hours))
        metric["expiresAt"] = iso(deadline)
        age = now - when
        fresh = (metric["date"] == now.astimezone(zone).date().isoformat()
                 if daily else age <= timedelta(hours=hours))
        metric["state"] = "fresh" if age >= timedelta(0) and fresh else "stale"


def quoted(value, quote):
    return quote + value.replace("\\", "\\\\").replace(quote, "\\" + quote) + quote


def queries(config, now, charts):
    zone = ZoneInfo(config["timezone"])
    start = datetime.combine(now.astimezone(zone).date() - timedelta(days=6), time(), zone)
    specs = [(name, now - timedelta(days=30), 1, False, (field,))
             for name, field, _ in METRICS.values()]
    if charts:
        # Keep rolling charts while also covering the full 25-hour source day.
        intraday_start = min(now - timedelta(hours=24),
                             datetime.combine(now.astimezone(zone).date(), time(), zone))
        specs.extend((name, intraday_start if name == "BodyBatteryIntraday" else start,
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


def fetch(config, now, charts=False, extras=True, previous=None):
    deadline = monotonic() + FETCH_BUDGET
    specs, statements = queries(config, now, charts)
    payload = request(config, ";".join(statements), timeout=min(TIMEOUT, FETCH_BUDGET))
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
    source = next(iter(sources), None)
    result["device"] = device_from_source(source)
    if extras:
        # Chart-only or untagged results cannot establish an activity/account scope.
        established = source if any(m["value"] is not None for m in result["metrics"].values()) else None
        cached = (previous["data"] if previous is not None and established == previous["source"]
                  and optional_source(established, config) is not None else None)
        fetch_extras(config, now, charts, established, deadline, result, cached)
        refresh_states(result, now)
    return result, source


def optional_source(source, config):
    try:
        tags = decode(source)
        if (isinstance(tags, dict) and tags
                and all(isinstance(k, str) and k and isinstance(v, str) and v for k, v in tags.items())
                and all(tags.get(k) == v for k, v in config["tags"].items())):
            return tags
    except (ValueError, TypeError, RecursionError):
        pass
    return None


def activity_connect_id(value, activity_id):
    if type(value) is int and 0 < value < 10**32:
        value = str(value)
    if (isinstance(value, str) and 1 <= len(value) <= 32
            and all("0" <= c <= "9" for c in value) and int(value) > 0 and value == activity_id):
        return value
    return None


def activity_summary(row, since, until):
    # Upstream's selected non-placeholder row is timestamped at activity start.
    when = timestamp(row["time"])
    kind = row.get("activityType")
    if (not since <= when <= until or not isinstance(kind, str) or not kind.strip()
            or len(kind) > 80 or not kind.isprintable() or kind.strip() == "No Activity"):
        raise ValueError("activity")
    selector = {}
    if "ActivityID" in row:
        value = row["ActivityID"]
        if not isinstance(value, str) or not 1 <= len(value) <= 32 or not all("0" <= c <= "9" for c in value):
            raise ValueError("activity id")
        selector["id"] = value
        # The manual FIT importer hashes ActivityID; only the normal collector
        # also writes the original Garmin ID in the Activity_ID field.
        connect_id = activity_connect_id(row.get("Activity_ID"), value)
        if connect_id is not None:
            selector["connectId"] = connect_id
    for field, key in (("ActivitySelector", "selector"), ("gpsSelector", "gpsSelector")):
        if field in row:
            value = row[field]
            if not isinstance(value, str) or not value.strip() or len(value) > 256 or not value.isprintable():
                raise ValueError("activity selector")
            selector[key] = value
    return {"time": iso(when), "type": kind, **selector,
            **{key: row.get(field) if number(row.get(field), field)
               and (field not in ("averageHR", "maxHR", "averageSpeed", "maxSpeed") or row[field] > 0) else None
                for key, field in ACTIVITY_FIELDS.items() if key != "type"}}


def activities_bundle(rows, fetched, zone):
    today = fetched.astimezone(zone).date()
    start = datetime.combine(today - timedelta(days=6), time(), zone)
    end = datetime.combine(today + timedelta(days=1), time(), zone)
    if len(rows) > 500:
        raise Failure("truncated_response")
    versions, latest = {}, {}
    for row in rows:
        summary = activity_summary(row, start, fetched)
        item = {"id": summary["id"], "time": summary["time"],
                "date": timestamp(summary["time"]).astimezone(zone).date().isoformat(),
                **{key: summary[key] for key in ACTIVITIES_FIELDS}}
        if "connectId" in summary:
            item["connectId"] = summary["connectId"]
        version = (item["id"], item["time"])
        if version in versions and versions[version] != item:
            previous_version = versions[version]
            if ({k: v for k, v in previous_version.items() if k != "connectId"}
                    != {k: v for k, v in item.items() if k != "connectId"}):
                raise ValueError("conflicting activity")
            # Conflicting provenance only disables the link, not the activity.
            previous_version.pop("connectId", None)
            item.pop("connectId", None)
        versions[version] = item
        previous = latest.get(item["id"])
        if previous is None or timestamp(item["time"]) > timestamp(previous["time"]):
            latest[item["id"]] = item
    # Stable ID tie-breaking makes the output independent of response row order.
    items = sorted(latest.values(), key=lambda item: (-timestamp(item["time"]).timestamp(), item["id"]))
    return {"startDate": start.date().isoformat(), "endDate": today.isoformat(),
            "from": int(start.timestamp() * 1000), "to": int(end.timestamp() * 1000), "items": items}


def gps_selector(config, tags, activity_id, since, until, deadline):
    try:
        if (not isinstance(activity_id, str) or not activity_id.strip()
                or len(activity_id) > 256 or not activity_id.isprintable()):
            return None
        remaining = deadline - monotonic()
        if remaining <= 0:
            return None
        expected = {**tags, "ActivityID": activity_id}
        conditions = ["time >= '" + iso(since) + "'", "time <= '" + iso(until) + "'"]
        conditions.extend(quoted(k, '"') + " = " + quoted(v, "'") for k, v in sorted(expected.items()))
        # FIT's selector uses its first record time, not the summary start time.
        payload = request(config, 'SELECT *::field FROM "ActivityGPS" WHERE ' + " AND ".join(conditions)
                          + " GROUP BY * ORDER BY time ASC LIMIT 1 SLIMIT 2", timeout=min(TIMEOUT, remaining))
        if not isinstance(payload, dict) or "error" in payload:
            return None
        items = payload["results"]
        if not isinstance(items, list) or len(items) != 1:
            return None
        item = items[0]
        if (not isinstance(item, dict) or type(item.get("statement_id")) is not int
                or item["statement_id"] != 0 or "error" in item or item.get("partial")):
            return None
        series = item.get("series", [])
        if not isinstance(series, list) or len(series) != 1:
            return None
        entry = series[0]
        if not isinstance(entry, dict) or entry.get("name") != "ActivityGPS" or entry.get("partial"):
            return None
        row_tags = entry["tags"]
        if not isinstance(row_tags, dict):
            return None
        selector = row_tags.get("ActivitySelector")
        if (not isinstance(selector, str) or not selector.strip() or len(selector) > 256
                or not selector.isprintable()
                or {k: v for k, v in row_tags.items() if k != "ActivitySelector"} != expected):
            return None
        columns, values = entry["columns"], entry["values"]
        if (not isinstance(columns, list) or not all(isinstance(c, str) for c in columns)
                or len(set(columns)) != len(columns) or "time" not in columns
                or not isinstance(values, list) or len(values) != 1
                or not isinstance(values[0], list) or len(values[0]) != len(columns)
                or not since <= timestamp(values[0][columns.index("time")]) <= until):
            return None
        return selector
    except (Failure, KeyError, ValueError, TypeError, OverflowError, RecursionError):
        return None


def fetch_extras(config, now, charts, source, deadline, result, cached=None):
    tags = optional_source(source, config)
    zone = ZoneInfo(config["timezone"])
    today = now.astimezone(zone).date()
    start = datetime.combine(today - timedelta(days=7), time(), zone)
    end = datetime.combine(today, time(), zone)
    jobs = [("activity", [("ActivitySummary", (*ACTIVITY_FIELDS.values(), "Activity_ID"))], ())]
    if charts:
        jobs.append(("history", [("DailyStats", ("bodyBatteryHighestValue", "totalSteps")),
                                  ("SleepSummary", ("sleepScore", "avgOvernightHrv"))], ()))
    # Independent statements prevent Influx's "not executed" cascade from hiding
    # healthy optional measurements, notably when TrainingReadiness is absent.
    jobs.extend(("wellness", [(name, (field,))], (key,))
                for key, (name, field, _) in WELLNESS.items())
    if charts:
        jobs.extend(("supplementalHistory", [(name, fields)], keys) for name, fields, keys in (
            ("SleepSummary", ("sleepTimeSeconds",), ("sleepDuration",)),
            ("DailyStats", ("restingHeartRate",), ("restingHeartRate",)),
            ("TrainingReadiness", ("score",), ("trainingReadiness",))))
        jobs.append(("stressHistory", [("StressIntraday", ("stressLevel",))] * 7, ("stress",)))
        jobs.append(("stress", [("StressIntraday", ("stressLevel",))], ()))
        jobs.append(("activities", [("ActivitySummary", (*ACTIVITIES_FIELDS.values(), "Activity_ID"))], ()))
    failed = {kind: set() for kind in ("wellness", "supplementalHistory", "stress")}
    activity_id = None
    for kind, specs, keys in jobs:
        stress_history = kind == "stressHistory"
        if stress_history:
            kind = "supplementalHistory"
        try:
            if tags is None:
                raise Failure("source_unavailable")
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise Failure("timeout")
            activity = kind == "activity"
            activities = kind == "activities"
            activity_rows = activity or activities
            daily = kind in ("history", "supplementalHistory")
            since, until = ((start, end) if daily else
                            (now - (timedelta(days=365) if activity else timedelta(days=30)
                                    if kind == "wellness" else timedelta(hours=24)), now))
            if kind == "stress":
                since = min(since, end)
            if activities:
                since = datetime.combine(today - timedelta(days=6), time(), zone)
            limit = 1 if activity or kind == "wellness" or stress_history else 2000 if kind == "stress" else 999
            if activities:
                limit = 500
            statements = []
            for index, (name, fields) in enumerate(specs):
                if stress_history:
                    # Calendar arithmetic keeps each selector aligned across DST.
                    since, until = start + timedelta(days=index), start + timedelta(days=index + 1)
                conditions = ["time >= '" + iso(since) + "'",
                              "time " + ("<" if daily else "<=") + " '" + iso(until) + "'"]
                conditions.extend(quoted(k, '"') + " = " + quoted(v, "'") for k, v in sorted(tags.items()))
                if activity_rows:
                    conditions.append('"activityType" != \'No Activity\'')
                if stress_history:
                    conditions.extend(('"stressLevel" >= 0', '"stressLevel" <= 100'))
                if kind == "wellness":
                    conditions.append(quoted(fields[0], '"') + " >= 0")
                    if keys[0] in ("trainingReadiness", "stress"):
                        conditions.append(quoted(fields[0], '"') + " <= 100")
                # Activity IDs are tags: GROUP BY * would make LIMIT 1 per activity.
                statements.append("SELECT " + ('MEAN("stressLevel") AS "stressLevel"' if stress_history else
                                               ",".join(quoted(f, '"') for f in fields))
                                  + (",*::tag" if activity_rows else "") + " FROM " + quoted(name, '"')
                                  + " WHERE " + " AND ".join(conditions)
                                  + (" GROUP BY * SLIMIT 2" if stress_history else
                                      " ORDER BY time DESC LIMIT 1" if activity else
                                      " ORDER BY time DESC LIMIT 501" if activities else
                                     " GROUP BY * ORDER BY time DESC LIMIT "
                                     + str(limit + int(daily or kind == "stress")) + " SLIMIT 2"))
            payload = request(config, ";".join(statements), timeout=min(TIMEOUT, remaining))
            if not isinstance(payload, dict):
                raise ValueError("payload")
            if "error" in payload:
                raise Failure("query_error")
            items = payload["results"]
            if not isinstance(items, list) or len(items) != len(specs):
                raise ValueError("results")
            rows = []
            for index, ((name, fields), item) in enumerate(zip(specs, items)):
                if stress_history:
                    since, until = start + timedelta(days=index), start + timedelta(days=index + 1)
                if (not isinstance(item, dict) or type(item.get("statement_id")) is not int
                        or item["statement_id"] != index):
                    raise ValueError("statement")
                if "error" in item:
                    raise Failure("query_error")
                if item.get("partial"):
                    raise Failure("truncated_response")
                series = item.get("series", [])
                if not isinstance(series, list):
                    raise ValueError("series")
                if len(series) > 1:
                    raise Failure("ambiguous_source")
                for entry in series:
                    if not isinstance(entry, dict) or entry["name"] != name:
                        raise ValueError("measurement")
                    if entry.get("partial"):
                        raise Failure("truncated_response")
                    entry_tags = entry.get("tags", {})
                    if (not isinstance(entry_tags, dict)
                            or any(not isinstance(k, str) or not isinstance(v, str) for k, v in entry_tags.items())):
                        raise ValueError("tags")
                    columns, values = entry["columns"], entry["values"]
                    if (not isinstance(columns, list) or not all(isinstance(c, str) for c in columns)
                            or len(set(columns)) != len(columns) or "time" not in columns
                            or not isinstance(values, list)
                            or (stress_history and set(columns) != {"time", "stressLevel"})
                            or (not activity_rows and set(columns) - {"time", *fields})):
                        raise ValueError("columns")
                    if len(values) > limit:
                        # At the history cap, completeness cannot be established.
                        raise Failure("truncated_response")
                    if not activity_rows and entry_tags != tags:
                        raise Failure("ambiguous_source")
                    for values_row in values:
                        if not isinstance(values_row, list) or len(values_row) != len(columns):
                            raise ValueError("row")
                        row = dict(zip(columns, values_row))
                        row_tags = dict(entry_tags)
                        if activity_rows:
                            for key in set(columns) - {"time", *fields}:
                                value = row[key]
                                if value is None:
                                    continue  # Absent optional tags in a mixed tag schema.
                                if not isinstance(value, str) or (key in row_tags and row_tags[key] != value):
                                    raise ValueError("tag column")
                                row_tags[key] = value
                            selector = row_tags.pop("ActivitySelector", None)
                            row_id = row_tags.pop("ActivityID", None)
                            if row_tags != tags:
                                raise Failure("ambiguous_source")
                            row.pop("ActivitySelector", None)
                            row.pop("ActivityID", None)
                            if row_id is not None:
                                row["ActivityID"] = row_id
                            if activity:
                                activity_id = row_id
                            if activity and selector is not None:
                                row["ActivitySelector"] = selector
                        when = timestamp(row["time"])
                        if stress_history:
                            # Ungrouped aggregates use the lower bound or Influx's
                            # epoch timestamp, not the time of an individual sample.
                            if when not in (since, datetime(1970, 1, 1, tzinfo=UTC)):
                                raise ValueError("aggregate time")
                            value = row.get("stressLevel")
                            if value is not None and not number(value, "stressLevel"):
                                raise ValueError("stress mean")
                            row["time"] = iso(since)
                        elif not since <= when <= until or (daily and when == until):
                            raise ValueError("range")
                        rows.append(row)
            if activity:
                result["latestActivity"] = activity_summary(rows[0], since, until) if rows else None
            elif activities:
                result["activities"] = activities_bundle(rows, now, zone)
            elif kind == "wellness":
                if rows:
                    row = rows[0]
                    value = row.get(specs[0][1][0])
                    if not number(value, specs[0][1][0]):
                        raise ValueError("wellness value")
                    result["wellness"][keys[0]].update(value=value, time=iso(timestamp(row["time"])))
            elif kind == "stress":
                result["stressSeries"] = [
                    {"time": iso(timestamp(row["time"])),
                     "value": row.get("stressLevel") if number(row.get("stressLevel"), "stressLevel") else None}
                    for row in sorted(rows, key=lambda r: timestamp(r["time"]))]
            elif kind == "supplementalHistory":
                days = {key: {} for key in keys}
                for row in sorted(rows, key=lambda r: timestamp(r["time"]), reverse=True):
                    day = timestamp(row["time"]).astimezone(zone).date().isoformat()
                    for key in keys:
                        value = row.get(SUPPLEMENTAL_FIELDS[key])
                        if day not in days[key] and number(value, SUPPLEMENTAL_FIELDS[key]):
                            days[key][day] = value
                for key in keys:
                    result[kind][key] = [
                        {"date": (today - timedelta(days=n)).isoformat(),
                         "value": days[key].get((today - timedelta(days=n)).isoformat())}
                        for n in range(7, 0, -1)]
            else:
                days = {key: {} for key in HISTORY_FIELDS}
                for row in sorted(rows, key=lambda r: timestamp(r["time"]), reverse=True):
                    day = timestamp(row["time"]).astimezone(zone).date().isoformat()
                    for key, field in HISTORY_FIELDS.items():
                        if field not in row or day in days[key]:
                            continue
                        value = row[field]
                        if value is not None and not number(value, field):
                            raise ValueError("history value")
                        if key in ("sleep", "hrv") and value is None:
                            continue
                        days[key][day] = value
                result["history"] = {
                    key: [{"date": (today - timedelta(days=n)).isoformat(),
                           "value": days[key].get((today - timedelta(days=n)).isoformat())}
                          for n in range(7, 0, -1)] for key in HISTORY_FIELDS}
            result[kind + "FetchedAt"] = iso(now)
        except Failure as exc:
            result[kind + "Error"] = str(exc) if str(exc) in OPTIONAL_ERRORS else "invalid_response"
            if kind in failed:
                failed[kind].update(keys or ("stressSeries",))
        except (KeyError, ValueError, TypeError, OverflowError, RecursionError):
            result[kind + "Error"] = "invalid_response"
            if kind in failed:
                failed[kind].update(keys or ("stressSeries",))
    if result["latestActivity"] is not None and tags is not None:
        selector = gps_selector(config, tags, activity_id, now - timedelta(days=365), now, deadline)
        if selector is not None:
            result["latestActivity"]["gpsSelector"] = selector
    if cached is not None:
        for kind, fields in failed.items():
            skipped = not charts and kind != "wellness"
            if skipped:
                fields = set(WELLNESS) if kind == "supplementalHistory" else {"stressSeries"}
                result[kind + "Error"] = cached[kind + "Error"]
            retained = False
            for key in fields:
                if kind == "stress":
                    result[key] = copy.deepcopy(cached[key])
                    retained = True
                else:
                    result[kind][key] = copy.deepcopy(cached[kind][key])
                    retained = retained or cached[kind + "FetchedAt"] is not None
            if retained or skipped:
                # A mixed bundle must not rejuvenate the cached portion.
                result[kind + "FetchedAt"] = cached[kind + "FetchedAt"]


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
        clean["device"] = device_from_source(envelope["source"])
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
        for kind in ("activity", "activities", "history", "wellness", "supplementalHistory", "stress"):
            error = result.get(kind + "Error")
            if error is not None and (not isinstance(error, str) or error not in OPTIONAL_ERRORS):
                return None
            clean[kind + "Error"] = error
        if optional_source(envelope["source"], config) is not None:
            for kind in ("activity", "activities", "history"):
                fetched = result.get(kind + "FetchedAt")
                if fetched is not None:
                    fetched = timestamp(fetched)
                    if fetched > timestamp(result["fetchedAt"]):
                        return None
                    clean[kind + "FetchedAt"] = iso(fetched)
                if kind == "activity":
                    activity = result.get("latestActivity")
                    if activity is not None:
                        if not isinstance(activity, dict) or fetched is None:
                            return None
                        row = {field: activity.get(key) for key, field in ACTIVITY_FIELDS.items()}
                        row["time"] = activity["time"]
                        if "id" in activity:
                            row["ActivityID"] = activity["id"]
                        if "connectId" in activity:
                            marker = activity["connectId"]
                            if not isinstance(marker, str) or activity_connect_id(marker, activity.get("id")) != marker:
                                return None
                            row["Activity_ID"] = marker
                        if "selector" in activity:
                            row["ActivitySelector"] = activity["selector"]
                        if "gpsSelector" in activity:
                            row["gpsSelector"] = activity["gpsSelector"]
                        clean["latestActivity"] = activity_summary(row, fetched - timedelta(days=365), fetched)
                elif kind == "activities":
                    bundle = result.get(kind)
                    if bundle is not None:
                        if (not isinstance(bundle, dict) or fetched is None
                                or not isinstance(bundle.get("items"), list) or len(bundle["items"]) > 500):
                            return None
                        rows = []
                        for item in bundle["items"]:
                            if "connectId" in item:
                                marker = item["connectId"]
                                if not isinstance(marker, str) or activity_connect_id(marker, item["id"]) != marker:
                                    return None
                            rows.append({"ActivityID": item["id"], "time": item["time"],
                                         "Activity_ID": item.get("connectId"),
                                         **{field: item.get(key) for key, field in ACTIVITIES_FIELDS.items()}})
                        rebuilt = activities_bundle(rows, fetched, ZoneInfo(config["timezone"]))
                        if (bundle["startDate"] != rebuilt["startDate"] or bundle["endDate"] != rebuilt["endDate"]
                                or len(rebuilt["items"]) != len(rows)
                                or any(item["date"] != timestamp(item["time"]).astimezone(
                                    ZoneInfo(config["timezone"])).date().isoformat() for item in bundle["items"])):
                            return None
                        clean[kind] = rebuilt
                else:
                    history = result.get("history", {key: [] for key in HISTORY_FIELDS})
                    if not isinstance(history, dict) or set(history) != set(HISTORY_FIELDS):
                        return None
                    dates = ([(fetched.astimezone(ZoneInfo(config["timezone"])).date() - timedelta(days=n)).isoformat()
                              for n in range(7, 0, -1)] if fetched else [])
                    for key, points in history.items():
                        if not isinstance(points, list) or len(points) not in (0, 7):
                            return None
                        if points and (fetched is None or [p["date"] for p in points] != dates):
                            return None
                        for point in points:
                            value = point["value"]
                            if value is not None and not number(value, HISTORY_FIELDS[key]):
                                return None
                            clean["history"][key].append({"date": point["date"], "value": value})
            for kind in ("wellness", "supplementalHistory", "stress"):
                fetched = result.get(kind + "FetchedAt")
                if fetched is not None:
                    fetched = timestamp(fetched)
                    if fetched > timestamp(result["fetchedAt"]):
                        return None
                    clean[kind + "FetchedAt"] = iso(fetched)
                if kind == "wellness":
                    metrics = result.get(kind, clean[kind])
                    if not isinstance(metrics, dict) or set(metrics) != set(WELLNESS):
                        return None
                    for key, metric in metrics.items():
                        value = metric["value"]
                        when = timestamp(metric["time"]) if metric["time"] is not None else None
                        # Partial refreshes can contain live points newer than the
                        # conservative bundle timestamp, but never newer than fetch.
                        if (value is not None and (not number(value, WELLNESS[key][1])
                                                  or when is None or fetched is None)
                                or when is not None and when > timestamp(result["fetchedAt"])):
                            return None
                        clean[kind][key].update(value=value, time=iso(when) if when else None)
                elif kind == "supplementalHistory":
                    history = result.get(kind, clean[kind])
                    if not isinstance(history, dict) or set(history) != set(WELLNESS):
                        return None
                    for key, points in history.items():
                        if not isinstance(points, list) or len(points) not in (0, 7):
                            return None
                        if points:
                            if fetched is None:
                                return None
                            last = datetime.strptime(points[-1]["date"], "%Y-%m-%d").date()
                            today = timestamp(result["fetchedAt"]).astimezone(ZoneInfo(config["timezone"])).date()
                            earliest = fetched.astimezone(ZoneInfo(config["timezone"])).date() - timedelta(days=1)
                            if not earliest <= last < today or [p["date"] for p in points] != [
                                    (last - timedelta(days=n)).isoformat() for n in range(6, -1, -1)]:
                                return None
                        for point in points:
                            value = point["value"]
                            if value is not None and not number(value, SUPPLEMENTAL_FIELDS[key]):
                                return None
                            clean[kind][key].append({"date": point["date"], "value": value})
                else:
                    points = result.get("stressSeries", [])
                    if not isinstance(points, list) or len(points) > 2000 or points and fetched is None:
                        return None
                    since = (min(fetched - timedelta(hours=24), datetime.combine(
                        fetched.astimezone(ZoneInfo(config["timezone"])).date(), time(), ZoneInfo(config["timezone"])))
                        if fetched is not None else None)
                    last = None
                    for point in points:
                        when, value = timestamp(point["time"]), point["value"]
                        if (not since <= when <= fetched
                                or last is not None and when < last
                                or value is not None and not number(value, "stressLevel")):
                            return None
                        clean["stressSeries"].append({"time": iso(when), "value": value})
                        last = when
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


def source_day_bounds(result):
    zone = ZoneInfo(result["timezone"])
    for kind in ("metrics", "wellness", "history", "supplementalHistory"):
        for records in result[kind].values():
            for point in records if isinstance(records, list) else [records]:
                point.pop("from", None)
                point.pop("to", None)
                if point.get("date") is None:
                    continue
                start = datetime.combine(datetime.strptime(point["date"], "%Y-%m-%d").date(), time(), zone)
                try:
                    # Local calendar arithmetic, not 24 hours of UTC, preserves DST.
                    end = start + timedelta(days=1)
                except OverflowError:
                    continue
                lower, upper = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
                if lower < upper:
                    point.update({"from": lower, "to": upper})
    return result


def run(command, config, now, charts=False):
    if command == "doctor":
        result, _ = fetch(config, now, extras=False)
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
                    result, source = fetch(config, now, charts, previous=previous)
                    if (previous is not None and source == previous["source"]
                            and optional_source(source, config) is not None
                            and any(m["value"] is not None for m in result["metrics"].values())):
                        for kind, field in (("activity", "latestActivity"), ("history", "history"),
                                            ("activities", "activities")):
                            if result[kind + "Error"] is not None or (kind != "activity" and not charts):
                                result[field] = copy.deepcopy(previous["data"][field])
                                result[kind + "FetchedAt"] = previous["data"][kind + "FetchedAt"]
                                if kind != "activity" and not charts:
                                    result[kind + "Error"] = previous["data"][kind + "Error"]
                    if previous is not None and (source is None or source == previous["source"]):
                        source = previous["source"]
                        result["device"] = device_from_source(source)
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
            result["history"] = {key: [] for key in HISTORY_FIELDS}
            result["historyFetchedAt"] = None
            result["supplementalHistory"] = {key: [] for key in WELLNESS}
            result["supplementalHistoryFetchedAt"] = None
            result["supplementalHistoryError"] = None
            result["stressSeries"] = []
            result["stressFetchedAt"] = None
            result["stressError"] = None
            result["activities"] = None
            result["activitiesFetchedAt"] = None
            result["activitiesError"] = None
        return source_day_bounds(result)


def demo(now, charts):
    result = empty(now, DEFAULTS["timezone"], "demo")
    result["device"] = {"name": "Forerunner 965", "source": "demo"}
    zone = ZoneInfo(result["timezone"])
    today = now.astimezone(zone).date()
    history = {
        "bodyBattery": [78, 91, 85, 67, 81, 88, 92],
        "steps": [8247, 10683, 7132, 11896, 6421, 9358, 12846],
        "sleep": [76, 88, 83, 69, 81, 87, 84],
        "hrv": [43, 51, 48, 39, 46, 53, 50],
        "sleepDuration": [25920, 29580, 27660, 22800, 26820, 29100, 28200],
        "restingHeartRate": [54, 49, 51, 57, 53, 48, 50],
        "trainingReadiness": [62, 86, 74, 42, 67, 83, 79],
        "stress": [31, 22, 27, 43, 29, 24, 26],
    }
    # Local-hour anchors keep refreshes stable and give the day a sleep/work/rest rhythm.
    profiles = {
        "bodyBattery": [(0, 24), (2, 43), (4, 66), (7, 92), (9, 84), (12, 65),
                        (13, 63), (16, 47), (18, 34), (21, 23), (23, 18), (24, 24)],
        "stress": [(0, 12), (3, 8), (6, 11), (7, 18), (9, 36), (11, 48),
                   (13, 19), (15, 42), (17, 32), (19, 24), (21, 17), (24, 12)],
        "steps": [(0, 0), (6, 0), (7, 284), (9, 1826), (12, 3618), (13, 5427),
                  (16, 6732), (18, 8249), (20, 10386), (22, 11274), (24, 11312)],
    }

    def sample(key, when):
        local = when.astimezone(zone)
        hour = local.hour + local.minute / 60 + local.second / 3600
        for (start, low), (end, high) in zip(profiles[key], profiles[key][1:]):
            if start <= hour < end:
                value = low + (high - low) * (hour - start) / (end - start)
                if key == "stress":
                    slot = local.hour * 12 + local.minute // 5
                    value += ((slot * 17 + slot * slot * 3) % 23 - 11) * (0.35 if hour < 7 else 1)
                    if slot in (112, 113, 135, 179, 180, 203):
                        value += 24
                return round(max(0, min(100, value)) if key != "steps" else value)

    wake = datetime.combine(today, time(7), zone)
    if wake > now:
        wake -= timedelta(days=1)
    sleep_values = {"sleep": 86, "hrv": 52, "sleepDuration": 28500}
    if wake.date() != today:
        sleep_values = {key: history[key][-1] for key in sleep_values}
    for key, value in {"bodyBattery": sample("bodyBattery", now), "steps": sample("steps", now),
                       "sleep": sleep_values["sleep"], "hrv": sleep_values["hrv"]}.items():
        when = wake if key in ("sleep", "hrv") else now
        result["metrics"][key].update(value=value, time=iso(when), date=when.astimezone(zone).date().isoformat())
    for key, value in {"sleepDuration": sleep_values["sleepDuration"], "restingHeartRate": 49,
                       "trainingReadiness": 82, "stress": sample("stress", now)}.items():
        when = wake if key == "sleepDuration" else now
        result["wellness"][key].update(value=value, time=iso(when))
    result["wellnessFetchedAt"] = iso(now)
    refresh_states(result, now)
    result["latestActivity"] = {
        "id": "9000000000000001", "time": iso(datetime.combine(today - timedelta(days=1), time(17, 40), zone)),
        "type": "Running", "durationSeconds": 2538, "distanceMeters": 7520,
        "calories": 526, "bmrCalories": 49,
        **dict(zip(ACTIVITY_DETAILS, (148, 172, 2496, 3.013, 4.62, 68, 64, 3.4, 0.8, 112)))}
    result["activityFetchedAt"] = iso(now)
    if charts:
        sessions = [
            (1, time(17, 40), "Running", 2538, 7520, 526),
            (2, time(12, 15), "Walking", 2142, 2840, 156),
            (3, time(18, 10), "Cycling", 4680, 28400, 684),
            (4, time(7, 30), "Strength Training", 2760, 0, 238),
            (5, time(8, 20), "Running", 1872, 5180, 362),
            (6, time(10, 5), "Hiking", 5820, 6730, 472),
        ]
        result["activities"] = activities_bundle([
            {"ActivityID": "900000000000000" + str(index + 1),
             "time": iso(datetime.combine(today - timedelta(days=days), start, zone)),
             "activityType": kind, "elapsedDuration": duration, "distance": distance, "calories": calories}
            for index, (days, start, kind, duration, distance, calories) in enumerate(sessions)], now, zone)
        result["activitiesFetchedAt"] = iso(now)
        result["supplementalHistoryFetchedAt"] = iso(now)
        result["stressFetchedAt"] = iso(now)
        for key in result["wellness"]:
            result["supplementalHistory"][key] = [
                {"date": (today - timedelta(days=7 - index)).isoformat(), "value": value}
                for index, value in enumerate(history[key])]
        result["stressSeries"] = [
            {"time": iso(now - timedelta(minutes=n * 5)), "value": sample("stress", now - timedelta(minutes=n * 5))}
            for n in range(288, -1, -1)]
        result["historyFetchedAt"] = iso(now)
        for key in result["metrics"]:
            result["history"][key] = [
                {"date": (today - timedelta(days=7 - index)).isoformat(), "value": value}
                for index, value in enumerate(history[key])]
        result["chartsFetchedAt"] = iso(now)
        result["charts"]["bodyBattery"] = [
            {"time": iso(now - timedelta(minutes=n * 5)), "value": sample("bodyBattery", now - timedelta(minutes=n * 5))}
            for n in range(288, -1, -1)]
        for key in ("steps", "sleep"):
            result["charts"][key] = [dict(point) for point in result["history"][key][1:]] + [
                {"date": today.isoformat(), "value": result["metrics"][key]["value"] if key == "steps" or wake.date() == today else None}]
    return source_day_bounds(result)


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
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--demo", action="store_true")
        mode.add_argument("--auto-demo", action="store_true")
        args = parser.parse_args(argv)
        if ((args.demo and args.command != "fetch")
                or ((args.charts or args.auto_demo) and args.command == "doctor")):
            raise Failure("invalid_arguments")
        if args.demo:
            result = demo(now, args.charts)
        else:
            config = load_config(args.config, auto_demo=args.auto_demo)
            if config is None:
                result = demo(now, args.charts)
            else:
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

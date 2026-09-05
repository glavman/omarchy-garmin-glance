"""Bounded, read-only coach data contracts (Python 3.9+, stdlib only).

fetch_context is the expanded v2 session reader; see its docstring below.
fetch_data retains the original internal v1 contract documented here.

fetch_data(config, now, days, metrics, history=False) takes a connection config
already validated by backend.load_config(), an aware datetime, 1..90 calendar
days, and a nonempty unique list of at most four backend.METRICS names. Call on
the main thread, outside an active SIGALRM timer (as with backend.request).
No cache, filesystem access, retries, arbitrary queries, or caller date ranges.

Exact success schema (only requested metric keys are present):
  {schemaVersion: 1, status: "ok"|"partial", fetchedAt: UTC ISO timestamp,
   timezone: IANA name, window: {start: UTC ISO, end: UTC ISO, days: integer},
   sourceFingerprint: lowercase SHA256 hex|null, metrics: {name: metric}}
The inclusive window starts at local midnight days-1 dates before today and
ends at now. All timestamps use UTC Z; dates use the configured timezone.

Summary metric:
  {unit: "score"|"steps"|"ms", value: number|null, time: UTC ISO|null,
   date: YYYY-MM-DD|null, state: "fresh"|"stale"|"missing",
   expiresAt: UTC ISO|null}
The latest valid value wins, including zero. The database filters each field
with >=0 (and <=100 for scores), then returns at most one row per series.
Missing values have null time/date.
Freshness and expiry are exactly backend.refresh_states semantics. Status is
partial if any metric is missing/stale or any nonnull invalid value was seen.

History metric (steps, sleep, hrv ONLY):
  {unit: "steps"|"score"|"ms",
   samples: [{date: YYYY-MM-DD, value: number|null, time: UTC ISO|null,
              complete: boolean}],
   coverage: {completedDays: integer, validCompletedDays: integer,
              missingCompletedDays: integer, completedFraction: number|null,
              firstAvailableDate: YYYY-MM-DD|null,
              lastAvailableDate: YYYY-MM-DD|null},
   summary: {mean: number|null}}
Samples are ascending, exactly one per requested local date, latest VALID
sample per date (not a sum). Null days have null time. complete means the date
has ended, NOT that its measurements are complete; today is always false.
Coverage counts only completed dates. Fraction is null when days=1. First/last
refer to valid samples in this window, including today. Mean uses only valid
completed dates, excluding missing dates and today, and is null if none exist.
History status is partial if any date lacks a valid sample (including today)
or an invalid nonnull value was seen. Today's incomplete flag alone is not an
error. Coverage is availability, not a baseline or a medical interpretation.

Identity must match configured tag filters and be identical across every
returned series, even empty series. Fingerprint hashes UTF-8 canonical JSON
of the observed tags (sort_keys=True, separators=(",", ":"), ensure_ascii=True).
No series means null; an observed untagged series hashes {}. Raw tags and
connection details never appear in output. This digest is not authentication,
cannot distinguish already-merged untagged data, and must be compared by the
launcher across calls alongside its pinned config fingerprint. sourceFingerprint
is internal helper metadata: the launcher must remove it before sending the
envelope to the model.

Limits: one POST, <=4 allowlisted SELECTs, bind parameters for time/tag values,
GROUP BY * / SLIMIT 2, <=1 row per summary metric or <=5000 history rows TOTAL,
1 MiB response AND output, and a
10-second wall-clock alarm covering transport, parsing, and aggregation.
History LIMIT 5001 is an overflow sentinel, never silently discarded. Dense
history windows may fail. Summary uses LIMIT 1 even for 90 days. Caller metrics
are never interpolated as identifiers.
Failures raise backend.Failure with stable codes: invalid_arguments,
invalid_config, invalid_response, query_error, ambiguous_source,
truncated_response, response_too_large, timeout, network_error, auth_error,
http_error, redirect_refused. Query errors fail the entire call; no fabricated
coverage is returned. SIGALRM ownership violations use invalid_arguments.
"""

import base64
from datetime import datetime, time, timedelta
import hashlib
import http.client
import json
import re
import signal
import threading
from time import monotonic
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import backend


MAX_ROWS = 5000
MAX_BYTES = 1024 * 1024
FETCH_BUDGET = 10
CONTEXT_BUDGET = 20
CONTEXT_METRICS = {**backend.METRICS, **backend.WELLNESS}
ACTIVITY_LIMIT = 500


def fetch_context(config, now, days, metrics=None, history=False, activities=True):
    """V2: all schema-supported summaries + activities, or bounded daily history.

    Independent jobs preserve healthy data on query/transport failure. Structural,
    identity and overflow failures fail closed. One 20s budget covers all jobs,
    aggregation, freshness and encoding. Each job gets at most 2s. Exhausting the
    whole budget fails with timeout; individual job timeouts remain partial.
    No cache, retry, extra database, or dashboard extras path.
    History uses one selector per local date (stress: mean; others: last valid),
    never raw intraday rows. Body Battery history is the daily highest value.
    sourceFingerprint is private metadata and must be removed before handoff.

    Envelope: {schemaVersion:2, status:ok|partial, fetchedAt, timezone,
      window:{start,end,days}, sourceFingerprint, metrics, warnings:[{section,code}],
      activities?:{status,error,items,coverage:{count,firstAvailableDate,
                                             lastAvailableDate,complete}}}.
    Summary metrics retain v1 fields plus status/error. Daily metrics retain v1
    samples/coverage/summary plus status/error/aggregation. A mean's sample time
    is null, since no individual observation timestamp represents that mean.
    Metric statuses: ok, partial, missing (summary), unavailable. Activity
    statuses: ok, empty, partial, unavailable. Empty is not proof of no exercise;
    activities.coverage.complete only means the bounded query was not degraded.
    Errors/warnings contain stable codes only, never raw server text. Missing
    values stay null. Limits: <=9 form POSTs, <=90 selectors per history POST,
    1 MiB per response/output, <=500 raw activity rows (501 is a fatal overflow
    sentinel). Latest timestamp per validated private ActivityID wins; conflicting
    equal versions fail. IDs are stripped after deduplication, before output.
    """
    metrics = list(CONTEXT_METRICS) if metrics is None else metrics
    if (type(days) is not int or not 1 <= days <= 90
            or not isinstance(metrics, list) or len(metrics) > len(CONTEXT_METRICS)
            or any(not isinstance(k, str) or k not in CONTEXT_METRICS for k in metrics)
            or len(set(metrics)) != len(metrics) or not metrics and not activities
            or type(history) is not bool or type(activities) is not bool
            or not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None
            or threading.current_thread() is not threading.main_thread()
            or signal.getitimer(signal.ITIMER_REAL) != (0, 0)):
        raise backend.Failure("invalid_arguments")
    try:
        zone = ZoneInfo(config["timezone"])
        tags = config["tags"]
        if (not isinstance(tags, dict) or len(tags) > 16
                or any(not isinstance(k, str) or not isinstance(v, str) or not k
                       or len(k) > 128 or len(v) > 256 or any(ord(c) < 32 for c in k + v)
                       for k, v in tags.items())
                or {"ActivityID", "ActivitySelector"} & tags.keys()):
            raise ValueError("tags")
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError):
        raise backend.Failure("invalid_config") from None
    try:
        now = now.astimezone(backend.UTC)
        today = now.astimezone(zone).date()
        dates = [today - timedelta(days=n) for n in range(days - 1, -1, -1)]
        start = datetime.combine(dates[0], time(), zone).astimezone(backend.UTC)
    except (ValueError, OverflowError):
        raise backend.Failure("invalid_arguments") from None
    result = {"schemaVersion": 2, "status": "ok", "fetchedAt": backend.iso(now),
              "timezone": config["timezone"], "window": {"start": backend.iso(start),
              "end": backend.iso(now), "days": days}, "sourceFingerprint": None,
              "metrics": {}, "warnings": []}
    source = None
    deadline = monotonic() + CONTEXT_BUDGET

    def timed_out(*_):
        raise backend.Failure("timeout")

    def arm_deadline(limit=None):
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise backend.Failure("timeout")
        signal.setitimer(signal.ITIMER_REAL, remaining if limit is None else min(limit, remaining))

    def identify(observed):
        nonlocal source
        if (not isinstance(observed, dict)
                or any(not isinstance(k, str) or not k or not isinstance(v, str) or not v
                       for k, v in observed.items())):
            raise ValueError("tags")
        if not observed:
            raise backend.Failure("source_unavailable")
        identity = json.dumps(observed, sort_keys=True, separators=(",", ":"))
        if (any(observed.get(k) != v for k, v in tags.items())
                or source is not None and source != identity):
            raise backend.Failure("ambiguous_source")
        source = identity

    previous = signal.signal(signal.SIGALRM, timed_out)
    try:
        arm_deadline()
        # Activity is always requested first at launch, even with no wellbeing data.
        for key in (["activities"] if activities else []) + metrics:
            activity = key == "activities"
            name, field, unit = ("ActivitySummary", None, None) if activity else CONTEXT_METRICS[key]
            if history and key == "bodyBattery":
                name, field = "DailyStats", "bodyBatteryHighestValue"
            fields = list(backend.ACTIVITY_FIELDS.values()) if activity else [field]
            daily = history and not activity
            aggregation = "mean" if key == "stress" else "latest_valid"
            if daily and key == "bodyBattery":
                aggregation = "daily_highest"
            rows, invalid, error = [], False, None
            versions = {}
            try:
                arm_deadline(2)
                params, statements, bounds = {}, [], []
                for index, date in enumerate(dates if daily else [dates[0]]):
                    since = datetime.combine(date, time(), zone).astimezone(backend.UTC) if daily else start
                    until = (datetime.combine(date + timedelta(days=1), time(), zone).astimezone(backend.UTC)
                             if daily and date < today else now)
                    bounds.append((since, until))
                    params["start" + str(index)], params["end" + str(index)] = backend.iso(since), backend.iso(until)
                    predicates = ["time >= $start" + str(index),
                                  "time " + ("<" if daily and date < today else "<=") + " $end" + str(index)]
                    for n, (tag, value) in enumerate(sorted(tags.items())):
                        params["tag" + str(n)] = value
                        predicates.append(backend.quoted(tag, '"') + " = $tag" + str(n))
                    if activity:
                        predicates.append('"activityType" != \'No Activity\'')
                        select = ",".join(backend.quoted(f, '"') for f in fields) + ",*::tag"
                        suffix = " ORDER BY time DESC LIMIT 501"
                    else:
                        quoted = backend.quoted(field, '"')
                        predicates.append(quoted + " >= 0")
                        if unit == "score":
                            predicates.append(quoted + " <= 100")
                        select = (("MEAN" if key == "stress" else "LAST") + "(" + quoted + ") AS " + quoted
                                  if daily else quoted)
                        suffix = " GROUP BY *" + (" SLIMIT 2" if daily else " ORDER BY time DESC LIMIT 1 SLIMIT 2")
                    statements.append("SELECT " + select + " FROM " + backend.quoted(name, '"')
                                      + " WHERE " + " AND ".join(predicates) + suffix)
                payload = _request(config, ";".join(statements), params)
                if not isinstance(payload, dict):
                    raise ValueError("payload")
                if payload.get("partial"):
                    raise backend.Failure("truncated_response")
                if "error" in payload:
                    raise backend.Failure("query_error")
                items = payload["results"]
                if not isinstance(items, list) or len(items) != len(statements):
                    raise ValueError("results")
                for index, item in enumerate(items):
                    if (not isinstance(item, dict) or type(item.get("statement_id")) is not int
                            or item["statement_id"] != index):
                        raise ValueError("statement")
                    if item.get("partial"):
                        raise backend.Failure("truncated_response")
                    if "error" in item:
                        error = "query_error"
                        continue
                    series = item.get("series", [])
                    if not isinstance(series, list):
                        raise ValueError("series")
                    if len(series) > 1:
                        raise backend.Failure("ambiguous_source")
                    for entry in series:
                        if not isinstance(entry, dict) or entry["name"] != name:
                            raise ValueError("measurement")
                        if entry.get("partial"):
                            raise backend.Failure("truncated_response")
                        observed = entry.get("tags", {})
                        if not isinstance(observed, dict):
                            raise ValueError("tags")
                        if not activity:
                            identify(observed)
                        elif observed:
                            identify({k: v for k, v in observed.items() if k not in ("ActivityID", "ActivitySelector")})
                        columns, values = entry["columns"], entry["values"]
                        if (not isinstance(columns, list) or not all(isinstance(c, str) for c in columns)
                                or len(set(columns)) != len(columns) or "time" not in columns
                                or not activity and set(columns) - {"time", field}
                                or not isinstance(values, list)):
                            raise ValueError("columns")
                        if len(values) > (ACTIVITY_LIMIT if activity else 1):
                            raise backend.Failure("truncated_response")
                        for values_row in values:
                            if not isinstance(values_row, list) or len(values_row) != len(columns):
                                raise ValueError("row")
                            row = dict(zip(columns, values_row))
                            if activity:
                                row_tags = dict(observed)
                                for tag in set(columns) - {"time", *fields}:
                                    value = row[tag]
                                    if value is None:
                                        continue
                                    if not isinstance(value, str) or tag in row_tags and row_tags[tag] != value:
                                        raise ValueError("tag column")
                                    row_tags[tag] = value
                                activity_id = row_tags.pop("ActivityID", None)
                                if not isinstance(activity_id, str) or not re.fullmatch(r"[0-9]{1,32}", activity_id):
                                    raise ValueError("activity id")
                                row_tags.pop("ActivitySelector", None)
                                identify(row_tags)
                            when = backend.timestamp(row["time"])
                            since, until = bounds[index]
                            if daily and key == "stress":
                                if when not in (since, datetime(1970, 1, 1, tzinfo=backend.UTC)):
                                    raise ValueError("aggregate time")
                            elif not since <= when <= until or daily and dates[index] < today and when == until:
                                raise ValueError("range")
                            if activity:
                                version = (activity_id, when)
                                data = {f: row.get(f) for f in fields}
                                if version in versions and versions[version] != data:
                                    raise ValueError("conflicting activity")
                                versions[version] = data
                                # Treat imported labels as data, not user-authored prose.
                                kind = row.get("activityType")
                                if not isinstance(kind, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_ -]{0,79}", kind) or kind == "No Activity":
                                    invalid = True
                                    continue
                                clean = {"_id": activity_id, "time": backend.iso(when),
                                         "date": when.astimezone(zone).date().isoformat(), "type": kind}
                                for output, f in backend.ACTIVITY_FIELDS.items():
                                    if output == "type":
                                        continue
                                    value = row.get(f)
                                    valid = backend.number(value, f) and (f not in ("averageHR", "maxHR", "averageSpeed", "maxSpeed") or value > 0)
                                    clean[output] = value if valid else None
                                    invalid |= value is not None and not valid
                                rows.append(clean)
                            else:
                                value = row.get(field)
                                if value is not None and not backend.number(value, field):
                                    invalid = True
                                    value = None
                                rows.append({"date": dates[index].isoformat() if daily else when.astimezone(zone).date().isoformat(),
                                             "value": value, "time": backend.iso(when) if value is not None and not (daily and key == "stress") else None})
            except backend.Failure as exc:
                if str(exc) not in {"query_error", "timeout", "network_error", "auth_error", "http_error"}:
                    raise
                error = str(exc)
            finally:
                # Restore the whole-call timer during aggregation and final output.
                arm_deadline()
            if error or invalid:
                result["warnings"].append({"section": key, "code": error or "invalid_values"})
            if activity:
                rows.sort(key=lambda r: (-backend.timestamp(r["time"]).timestamp(), r["_id"]))
                latest = {}
                for row in rows:
                    activity_id = row.pop("_id")
                    latest.setdefault(activity_id, row)
                rows = list(latest.values())
                result["activities"] = {"status": "unavailable" if error and not rows else "partial" if error or invalid else "ok" if rows else "empty",
                                        "error": error, "items": rows,
                                        "coverage": {"count": len(rows), "firstAvailableDate": min((r["date"] for r in rows), default=None),
                                                     "lastAvailableDate": max((r["date"] for r in rows), default=None),
                                                     "complete": not error and not invalid}}
                partial = bool(error or invalid)
            elif daily:
                by_date = {r["date"]: r for r in rows}
                samples = [{**by_date.get(date.isoformat(), {"date": date.isoformat(), "value": None, "time": None}),
                            "complete": date < today} for date in dates]
                completed = [r["value"] for r in samples if r["complete"] and r["value"] is not None]
                available = [r["date"] for r in samples if r["value"] is not None]
                partial = bool(error or invalid or len(available) != days)
                result["metrics"][key] = {"unit": unit, "status": "unavailable" if error and not available else "partial" if partial else "ok",
                    "error": error, "aggregation": aggregation, "samples": samples, "coverage": {
                    "completedDays": days - 1, "validCompletedDays": len(completed), "missingCompletedDays": days - 1 - len(completed),
                    "completedFraction": len(completed) / (days - 1) if days > 1 else None,
                    "firstAvailableDate": available[0] if available else None, "lastAvailableDate": available[-1] if available else None},
                    "summary": {"mean": sum(v / len(completed) for v in completed) if completed else None}}
            else:
                row = next((r for r in rows if r["value"] is not None), {"value": None, "time": None, "date": None})
                result["metrics"][key] = {**row, "unit": unit, "state": "missing", "expiresAt": None,
                                          "status": "unavailable" if error else "partial" if invalid else "missing" if row["value"] is None else "ok", "error": error}
                partial = bool(error or invalid or row["value"] is None)
            if partial:
                result["status"] = "partial"
        if not history:
            refresh_context(result, now)
        if source is not None:
            result["sourceFingerprint"] = hashlib.sha256(source.encode()).hexdigest()
        if len(json.dumps(result, allow_nan=False, separators=(",", ":")).encode()) > MAX_BYTES:
            raise backend.Failure("response_too_large")
        if monotonic() >= deadline:
            raise backend.Failure("timeout")
        return result
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        raise backend.Failure("invalid_response") from None
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def refresh_context(result, now):
    """Reuse backend freshness without adding dashboard fields to the envelope."""
    backend.refresh_states({"timezone": result["timezone"], "metrics": result["metrics"]}, now)
    for metric in result["metrics"].values():
        if metric["state"] != "fresh":
            result["status"] = "partial"
            if metric["status"] == "ok":
                metric["status"] = "partial"


def _request(config, query, params):
    # Only internal allowlisted SELECT builders call this transport. POST keeps
    # long daily queries and bound values out of URLs; it does not grant writes.
    url = config["url"] + "/query"
    data = urllib.parse.urlencode({
        "db": config["database"], "q": query,
        "params": json.dumps(params, separators=(",", ":"), allow_nan=False)}).encode("ascii")
    headers = {"Accept": "application/json", "Accept-Encoding": "identity",
               "Content-Type": "application/x-www-form-urlencoded"}
    if config["username"] or config["password"]:
        token = base64.b64encode((config["username"] + ":" + config["password"]).encode()).decode("ascii")
        headers["Authorization"] = "Basic " + token
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), backend.NoRedirect())
    try:
        with opener.open(urllib.request.Request(url, data=data, headers=headers, method="POST"),
                         timeout=FETCH_BUDGET) as response:
            if response.status != 200:
                raise backend.Failure("http_error")
            size = response.headers.get("Content-Length")
            if size is not None and (int(size) < 0 or int(size) > MAX_BYTES):
                raise backend.Failure("response_too_large")
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise backend.Failure("response_too_large")
            if size is not None and len(raw) != int(size):
                raise backend.Failure("invalid_response")
            return backend.decode(raw)
    except urllib.error.HTTPError as exc:
        code = ("auth_error" if exc.code in (401, 403) else
                "redirect_refused" if 300 <= exc.code < 400 else "http_error")
        exc.close()
        raise backend.Failure(code) from None
    except urllib.error.URLError as exc:
        raise backend.Failure("timeout" if isinstance(exc.reason, TimeoutError) else "network_error") from None
    except TimeoutError:
        raise backend.Failure("timeout") from None
    except (ValueError, UnicodeError, RecursionError, http.client.HTTPException):
        raise backend.Failure("invalid_response") from None
    except OSError:
        raise backend.Failure("network_error") from None


def fetch_data(config, now, days, metrics, history=False):
    """Return the documented v1 envelope or raise a sanitized backend.Failure."""
    if (type(days) is not int or not 1 <= days <= 90
            or not isinstance(metrics, list) or not 1 <= len(metrics) <= 4
            or any(not isinstance(key, str) or key not in backend.METRICS for key in metrics)
            or len(set(metrics)) != len(metrics) or type(history) is not bool
            or history and "bodyBattery" in metrics
            or not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None
            or threading.current_thread() is not threading.main_thread()
            or signal.getitimer(signal.ITIMER_REAL) != (0, 0)):
        raise backend.Failure("invalid_arguments")
    try:
        zone = ZoneInfo(config["timezone"])
        tags = config["tags"]
        if (not isinstance(tags, dict) or len(tags) > 16
                or any(not isinstance(k, str) or not isinstance(v, str) or not k
                       or len(k) > 128 or len(v) > 256
                       or any(ord(c) < 32 for c in k + v) for k, v in tags.items())):
            raise ValueError("tags")
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError):
        raise backend.Failure("invalid_config") from None
    try:
        now = now.astimezone(backend.UTC)
        today = now.astimezone(zone).date()
        dates = [today - timedelta(days=n) for n in range(days - 1, -1, -1)]
        start = datetime.combine(dates[0], time(), zone).astimezone(backend.UTC)
    except (ValueError, OverflowError):
        raise backend.Failure("invalid_arguments") from None

    def timed_out(*_):
        raise backend.Failure("timeout")

    previous_handler = signal.signal(signal.SIGALRM, timed_out)
    try:
        signal.setitimer(signal.ITIMER_REAL, FETCH_BUDGET)
        params = {"start": backend.iso(start), "end": backend.iso(now)}
        conditions = ["time >= $start", "time <= $end"]
        for index, (key, value) in enumerate(sorted(tags.items())):
            param = "tag" + str(index)
            params[param] = value
            conditions.append(backend.quoted(key, '"') + " = $" + param)
        statements = []
        for key in metrics:
            name, field, _ = backend.METRICS[key]
            predicates = conditions.copy()
            if not history:
                predicates.append(backend.quoted(field, '"') + " >= 0")
                if field in ("BodyBatteryLevel", "sleepScore"):
                    predicates.append(backend.quoted(field, '"') + " <= 100")
            statements.append("SELECT " + backend.quoted(field, '"') + " FROM "
                              + backend.quoted(name, '"') + " WHERE " + " AND ".join(predicates)
                              + " GROUP BY * ORDER BY time DESC LIMIT "
                              + str(MAX_ROWS + 1 if history else 1) + " SLIMIT 2")
        payload = _request(config, ";".join(statements), params)
        result = {"schemaVersion": 1, "status": "ok", "fetchedAt": backend.iso(now),
                  "timezone": config["timezone"], "window": {"start": backend.iso(start),
                  "end": backend.iso(now), "days": days}, "sourceFingerprint": None, "metrics": {}}
        if not isinstance(payload, dict):
            raise ValueError("object")
        if "error" in payload:
            raise backend.Failure("query_error")
        if payload.get("partial"):
            raise backend.Failure("truncated_response")
        results = payload["results"]
        if not isinstance(results, list) or len(results) != len(metrics):
            raise ValueError("results")
        source = None
        row_count = 0
        for index, (key, item) in enumerate(zip(metrics, results)):
            name, field, unit = backend.METRICS[key]
            if (not isinstance(item, dict) or type(item.get("statement_id")) is not int
                    or item["statement_id"] != index):
                raise ValueError("statement")
            if "error" in item:
                raise backend.Failure("query_error")
            if item.get("partial"):
                raise backend.Failure("truncated_response")
            series = item.get("series", [])
            if not isinstance(series, list):
                raise ValueError("series")
            if len(series) > 1:
                raise backend.Failure("ambiguous_source")
            daily = {}
            for entry in series:
                if not isinstance(entry, dict) or entry["name"] != name:
                    raise ValueError("measurement")
                if entry.get("partial"):
                    raise backend.Failure("truncated_response")
                observed = entry.get("tags", {})
                if (not isinstance(observed, dict)
                        or any(not isinstance(k, str) or not isinstance(v, str) for k, v in observed.items())):
                    raise ValueError("tags")
                identity = json.dumps(observed, sort_keys=True, separators=(",", ":"))
                if (any(observed.get(k) != v for k, v in tags.items())
                        or source is not None and source != identity):
                    raise backend.Failure("ambiguous_source")
                source = identity
                columns, values = entry["columns"], entry["values"]
                if (not isinstance(columns, list) or len(columns) != 2
                        or not all(isinstance(c, str) for c in columns)
                        or set(columns) != {"time", field} or not isinstance(values, list)):
                    raise ValueError("columns")
                row_count += len(values)
                if not history and len(values) > 1:
                    raise ValueError("summary row limit")
                if row_count > MAX_ROWS:
                    raise backend.Failure("truncated_response")
                seen = set()
                for row in values:
                    if not isinstance(row, list) or len(row) != len(columns):
                        raise ValueError("row")
                    when = backend.timestamp(row[columns.index("time")])
                    if not start <= when <= now or when in seen:
                        raise ValueError("timestamp")
                    seen.add(when)
                    value = row[columns.index(field)]
                    if value is None:
                        continue
                    if not backend.number(value, field):
                        result["status"] = "partial"
                        continue
                    date = when.astimezone(zone).date().isoformat()
                    if date not in daily or when > daily[date][0]:
                        daily[date] = (when, value)
            if not history:
                when, value = max(daily.values(), default=(None, None), key=lambda pair: pair[0])
                result["metrics"][key] = {"unit": unit, "value": value,
                    "time": backend.iso(when) if when is not None else None,
                    "date": None, "state": "missing", "expiresAt": None}
                continue
            samples = []
            for date in dates:
                when, value = daily.get(date.isoformat(), (None, None))
                samples.append({"date": date.isoformat(), "value": value,
                                "time": backend.iso(when) if when is not None else None,
                                "complete": date < today})
            completed = [s["value"] for s in samples if s["complete"] and s["value"] is not None]
            available = [s["date"] for s in samples if s["value"] is not None]
            # Divide first to avoid overflowing a finite floating-point sum.
            mean = sum(value / len(completed) for value in completed) if completed else None
            result["metrics"][key] = {"unit": unit, "samples": samples, "coverage": {
                "completedDays": days - 1, "validCompletedDays": len(completed),
                "missingCompletedDays": days - 1 - len(completed),
                "completedFraction": len(completed) / (days - 1) if days > 1 else None,
                "firstAvailableDate": available[0] if available else None,
                "lastAvailableDate": available[-1] if available else None}, "summary": {"mean": mean}}
            if len(available) != days:
                result["status"] = "partial"
        if not history:
            # Share metric mutations without adding dashboard fields to the coach envelope.
            backend.refresh_states({"timezone": result["timezone"], "metrics": result["metrics"]}, now)
            if any(m["state"] != "fresh" for m in result["metrics"].values()):
                result["status"] = "partial"
        if source is not None:
            result["sourceFingerprint"] = hashlib.sha256(source.encode()).hexdigest()
        if len(json.dumps(result, allow_nan=False, separators=(",", ":")).encode()) > MAX_BYTES:
            raise backend.Failure("response_too_large")
        return result
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        raise backend.Failure("invalid_response") from None
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)

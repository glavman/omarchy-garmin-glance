"""Synthetic data only; every HTTP request is to an ephemeral loopback fixture."""

import contextlib
import copy
from datetime import datetime, timedelta
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit


SPEC = importlib.util.spec_from_file_location("backend", Path(__file__).resolve().parents[1] / "backend.py")
b = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(b)
NOW = datetime(2026, 9, 5, 10, tzinfo=b.UTC)
TAGS = {"Device": "Fixture", "Database_Name": "GarminStats"}


def payload(now=NOW, charts=False, tags=None):
    results = []
    specs = [(name, (field,)) for name, field, _ in b.METRICS.values()]
    if charts:
        specs.extend(b.FIELDS.items())
    for index, (name, fields) in enumerate(specs):
        when = now - timedelta(hours=8) if name == "SleepSummary" else now
        results.append({"statement_id": index, "series": [{"name": name, "tags": TAGS if tags is None else tags,
                        "columns": ["time", *fields], "values": [[b.iso(when), *([0] * len(fields))]]}]})
    return {"results": results}


def activity_payload(tags=None, **fields):
    row = {"time": b.iso(NOW - timedelta(hours=1)), "activityType": "running",
           "elapsedDuration": 1800, "distance": 5000, "calories": 350, "bmrCalories": 40,
            **(TAGS if tags is None else tags), "ActivityID": "123", "Activity_ID": 123,
            "ActivitySelector": "synthetic",
           **fields}
    return {"results": [{"statement_id": 0, "series": [{"name": "ActivitySummary",
                         "columns": list(row), "values": [list(row.values())]}]}]}


def history_payload(daily=None, sleep=None, tags=None):
    return {"results": [
        {"statement_id": index, "series": [{"name": name, "tags": TAGS if tags is None else tags,
         "columns": ["time", *fields], "values": rows or []}]}
        for index, (name, fields, rows) in enumerate([
            ("DailyStats", ("bodyBatteryHighestValue", "totalSteps"), daily),
             ("SleepSummary", ("sleepScore", "avgOvernightHrv"), sleep)])]}


def activities_payload(*rows, tags=None):
    fields = ("activityType", "elapsedDuration", "distance", "calories")
    columns = ["time", *fields, *(TAGS if tags is None else tags), "ActivityID", "ActivitySelector", "Activity_ID"]
    values = []
    for fields_row in rows:
        row = {"time": b.iso(NOW), "activityType": "running", "elapsedDuration": 1800,
               "distance": 5000, "calories": 350, **(TAGS if tags is None else tags),
               "ActivityID": "123", "ActivitySelector": "synthetic", "Activity_ID": 123, **fields_row}
        values.append([row.get(key) for key in columns])
    return {"results": [{"statement_id": 0, "series": [
        {"name": "ActivitySummary", "columns": columns, "values": values}]}]}


def supplemental_payload(name, fields, rows=(), tags=None):
    return {"results": [{"statement_id": 0, "series": [
        {"name": name, "tags": TAGS if tags is None else tags,
         "columns": ["time", *fields], "values": list(rows)}]}]}


def stress_history_payload(query, values=(0, None, 25.5, 100, None, 40, 50), tags=None):
    results = []
    for index, statement in enumerate(query.split(";")):
        start = statement.split("time >= '")[1].split("'")[0]
        item = supplemental_payload("StressIntraday", ("stressLevel",),
                                    [[start, values[index]]], tags)["results"][0]
        results.append({**item, "statement_id": index})
    return {"results": results}


class BackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                query = parse_qs(urlsplit(self.path).query)["q"][0]
                optional = ("gps" if 'FROM "ActivityGPS"' in query else
                            "activities" if query.endswith("ORDER BY time DESC LIMIT 501") else
                            "activity" if query.startswith('SELECT "activityType"') else
                            "history" if query.startswith('SELECT "bodyBatteryHighestValue"') else None)
                supplemental = query.startswith('SELECT MEAN(') or any(
                    query.startswith('SELECT "' + field + '"') for field in
                    ("sleepTimeSeconds", "restingHeartRate", "score", "stressLevel"))
                # Keep the original base-query/recovery assertions independent of extras.
                (cls.gps_requests if optional == "gps" else cls.activities_requests if optional == "activities"
                 else cls.supplemental_requests if supplemental
                 else cls.optional_requests if optional else cls.requests).append(
                    (self.command, self.path, dict(self.headers)))
                self.send_response(cls.http_status)
                if cls.http_status == 302:
                    self.send_header("Location", cls.url + "/redirect-target")
                response = getattr(cls, optional + "_response") if optional else cls.response
                if supplemental:
                    response = cls.supplemental_response(query)
                if cls.statements is not None and not optional and not supplemental:
                    query = parse_qs(urlsplit(self.path).query)["q"][0]
                    submitted = cls.statements if query == ";".join(cls.statements) else [query]
                    results = []
                    stopped = False
                    for index, statement in enumerate(submitted):
                        item = copy.deepcopy(cls.response["results"][cls.statements.index(statement)])
                        if stopped:
                            item = {"error": "not executed"}
                        item["statement_id"] = index
                        results.append(item)
                        stopped = "error" in item
                    response = {"results": results}
                raw = cls.raw if cls.raw is not None else json.dumps(response).encode()
                if cls.content_length != "omit":
                    self.send_header("Content-Length", str(cls.content_length if cls.content_length is not None else len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *_):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.url = "http://127.0.0.1:" + str(cls.server.server_port)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {"XDG_CACHE_HOME": self.temp.name,
                                          "http_proxy": "http://127.0.0.1:1", "HTTP_PROXY": "http://127.0.0.1:1",
                                          "https_proxy": "http://127.0.0.1:1", "NO_PROXY": "", "no_proxy": ""})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.config = copy.deepcopy(b.DEFAULTS)
        self.config["url"] = self.url
        type(self).response = payload()
        type(self).requests = []
        type(self).optional_requests = []
        type(self).gps_requests = []
        type(self).activities_requests = []
        type(self).activities_response = {"results": [{"statement_id": 0}]}
        type(self).gps_response = {"results": [{"statement_id": 0}]}
        type(self).supplemental_requests = []
        type(self).supplemental_response = staticmethod(lambda query: {
            "results": [{"statement_id": n} for n in range(query.count('SELECT MEAN(') or 1)]})
        type(self).activity_response = {"results": [{"statement_id": 0}]}
        type(self).history_response = {"results": [{"statement_id": 0}, {"statement_id": 1}]}
        type(self).http_status = 200
        type(self).raw = None
        type(self).content_length = None
        type(self).statements = None

    def config_file(self, contents):
        path = Path(self.temp.name) / "connection.json"
        path.write_text(json.dumps(contents))
        path.chmod(0o600)
        return path

    def cli(self, *args):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = b.main(list(args))
        self.assertEqual(errors.getvalue(), "")
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        self.assertLess(len(output.getvalue()), b.MAX_BYTES)
        return code, json.loads(output.getvalue())

    def test_zero_and_verified_mappings(self):
        result = b.run("fetch", self.config, NOW)
        self.assertEqual(result["status"], "ok")
        for metric in result["metrics"].values():
            self.assertEqual(metric["value"], 0)
            self.assertEqual(metric["state"], "fresh")
            self.assertIsNotNone(metric["time"])
        query = parse_qs(urlsplit(self.requests[0][1]).query)["q"][0]
        for field in ("BodyBatteryLevel", "totalSteps", "sleepScore", "avgOvernightHrv"):
            self.assertIn('"' + field + '"', query)
        self.assertNotIn("goal", result["metrics"]["steps"])
        self.assertNotIn("dailyStepGoal", query)
        self.assertEqual(len(self.requests), 1)

    def test_null_and_missing_preserve_timestamp(self):
        self.response["results"][0]["series"][0]["values"][0][1] = None
        self.response["results"][1].pop("series")
        result = b.run("fetch", self.config, NOW)
        self.assertEqual(result["status"], "partial")
        self.assertIsNone(result["metrics"]["bodyBattery"]["value"])
        self.assertEqual(result["metrics"]["bodyBattery"]["time"], b.iso(NOW))
        self.assertEqual(result["metrics"]["steps"]["state"], "missing")
        self.assertIsNone(result["metrics"]["steps"]["time"])

    def test_device_label_from_validated_tagged_fetch(self):
        for name in ("Forerunner 965", "f\u00e9nix 7", "My trail watch", "x" * 80):
            with self.subTest(name=name):
                tags = {"Device": "  " + name + "  ", "User_ID": "private-user",
                        "Database_Name": "private-database", "Serial": "private-serial"}
                type(self).response = payload(charts=True, tags=tags)
                result, source = b.fetch(self.config, NOW, charts=True)
                self.assertEqual(result["device"], {"name": name, "source": "Device"})
                self.assertEqual(json.loads(source), tags)
                self.assertNotIn("private-", json.dumps(result))
                self.assertEqual(result["status"], "ok")

    def test_unknown_and_invalid_device_labels(self):
        invalid = ["", "   ", "Unknown", " unknown ", "Garmin", " GARMIN ", "x" * 81,
                   "watch\u200b", "watch\u202e", "watch\ud800"]
        invalid.extend("watch" + chr(code) for code in (*range(32), *range(127, 160)))
        for tags in ({}, {"device": "Wrong case"}, {"User_ID": "private-user"},
                     *({"Device": name} for name in invalid)):
            with self.subTest(tags=tags):
                type(self).response = payload(tags=tags)
                result, _ = b.fetch(self.config, NOW)
                self.assertIsNone(result["device"])
                self.assertEqual(result["status"], "ok")
        self.assertIsNone(b.empty(NOW, self.config["timezone"])["device"])

    def test_device_cache_reconstruction_and_old_cache(self):
        b.run("fetch", self.config, NOW)
        path, key = b.cache_location(self.config)
        original = json.loads(path.read_text())
        for source, expected in ((original["source"], {"name": "Fixture", "source": "Device"}),
                                 (json.dumps({"Device": " f\u00e9nix 7 ", "User_ID": "private-user"}),
                                  {"name": "f\u00e9nix 7", "source": "Device"}),
                                 (None, None), ("{}", None), ('{"Device":"Unknown"}', None),
                                 ('{"Device":"watch\\u007f"}', None),
                                 ('{"Device":42}', None), ('{"Device":[]}', None),
                                 ('{"Device":"Watch","User_ID":42}', None),
                                 ("not json", None), ("[]", None), ("null", None)):
            for old_cache in (False, True):
                with self.subTest(source=source, old_cache=old_cache):
                    envelope = copy.deepcopy(original)
                    envelope["source"] = source
                    if old_cache:
                        envelope["data"].pop("device")
                    else:
                        envelope["data"]["device"] = {"name": "private-forged", "source": "demo",
                                                      "User_ID": "private-user"}
                    path.write_text(json.dumps(envelope))
                    cached = b.read_cache(path, key, self.config, NOW)["data"]
                    self.assertEqual(cached["device"], expected)
                    self.assertEqual(cached["metrics"], original["data"]["metrics"])
                    self.assertNotIn("private-", json.dumps(cached))

    def test_all_missing(self):
        type(self).response = {"results": [{"statement_id": n} for n in range(4)]}
        result = b.run("fetch", self.config, NOW)
        self.assertEqual(result["status"], "partial")
        self.assertTrue(all(m["state"] == "missing" for m in result["metrics"].values()))
        self.assertIsNone(result["device"])

    def test_stale_boundaries_and_cache_reassessment(self):
        result = b.run("fetch", self.config, NOW)
        b.refresh_states(result, NOW + timedelta(hours=2))
        self.assertEqual(result["metrics"]["bodyBattery"]["state"], "fresh")
        cached = b.run("cache", self.config, NOW + timedelta(hours=2, seconds=1))
        self.assertEqual(cached["metrics"]["bodyBattery"]["state"], "stale")
        self.assertEqual(cached["fetchedAt"], b.iso(NOW))
        cached = b.run("cache", self.config, NOW + timedelta(hours=28))
        self.assertEqual(cached["metrics"]["sleep"]["state"], "fresh")
        self.assertEqual(cached["metrics"]["steps"]["state"], "stale")
        cached = b.run("cache", self.config, NOW + timedelta(hours=28, seconds=1))
        self.assertEqual(cached["metrics"]["hrv"]["state"], "stale")
        self.assertEqual(len(self.requests), 1)

    def test_local_dates_and_actual_sleep_end(self):
        now = datetime(2026, 9, 5, 0, 15, tzinfo=b.UTC)
        type(self).response = payload(now)
        self.response["results"][1]["series"][0]["values"][0][0] = "2026-09-04T23:00:00Z"
        result = b.run("fetch", self.config, now)
        self.assertEqual(result["metrics"]["steps"]["date"], "2026-09-05")
        self.assertEqual(result["metrics"]["steps"]["state"], "fresh")
        self.assertEqual(result["metrics"]["sleep"]["date"], "2026-09-04")
        self.assertEqual(result["metrics"]["sleep"]["state"], "fresh")

    def test_expiry_deadlines_and_cache_reconstruction(self):
        result = b.run("fetch", self.config, NOW)
        for key, expected in (("bodyBattery", NOW + timedelta(hours=2)),
                              ("steps", NOW.replace(hour=23)),
                              ("sleep", NOW + timedelta(hours=28)),
                              ("hrv", NOW + timedelta(hours=28))):
            self.assertEqual(result["metrics"][key]["expiresAt"], b.iso(expected))
        path, identity = b.cache_location(self.config)
        envelope = json.loads(path.read_text())
        for metric in envelope["data"]["metrics"].values():
            metric["expiresAt"] = "untrusted cached deadline"
        envelope["data"]["sourceDayStart"] = "untrusted cached midnight"
        envelope["data"]["sourceDayEnd"] = "untrusted cached next midnight"
        path.write_text(json.dumps(envelope))
        cached = b.read_cache(path, identity, self.config, NOW + timedelta(hours=3))["data"]
        self.assertEqual(cached["sourceDate"], "2026-09-05")
        self.assertEqual(cached["sourceDayStart"], "2026-09-04T23:00:00Z")
        self.assertEqual(cached["sourceDayEnd"], "2026-09-05T23:00:00Z")
        next_day = b.read_cache(path, identity, self.config, NOW + timedelta(days=1))["data"]
        self.assertEqual(next_day["sourceDate"], "2026-09-06")
        self.assertEqual(next_day["sourceDayStart"], "2026-09-05T23:00:00Z")
        self.assertEqual(next_day["sourceDayEnd"], "2026-09-06T23:00:00Z")
        self.assertEqual([m["expiresAt"] for m in cached["metrics"].values()],
                         [m["expiresAt"] for m in result["metrics"].values()])
        for metric in b.empty(NOW, self.config["timezone"])["metrics"].values():
            self.assertIsNone(metric["expiresAt"])
        result["metrics"]["steps"]["value"] = None
        b.refresh_states(result, NOW)
        self.assertIsNone(result["metrics"]["steps"]["expiresAt"])
        self.assertTrue(all(m["expiresAt"] is not None for m in b.demo(NOW, True)["metrics"].values()))

    def test_source_day_bounds_fetch_cache_and_dst(self):
        for day, start, end, hours in (
                ("2026-03-29", "2026-03-29T00:00:00Z", "2026-03-29T23:00:00Z", 23),
                ("2026-10-25", "2026-10-24T23:00:00Z", "2026-10-26T00:00:00Z", 25)):
            with self.subTest(day=day):
                now = b.timestamp(end) + timedelta(hours=1)
                sample = b.timestamp(start) + timedelta(hours=12)
                type(self).response = payload(sample, charts=True)
                self.wellness_fixture(sample)
                type(self).history_response = history_payload(daily=[[b.iso(sample), 0, 0]])
                expected = {"from": int(b.timestamp(start).timestamp() * 1000),
                            "to": int(b.timestamp(end).timestamp() * 1000)}
                for command in ("fetch", "cache"):
                    result = b.run(command, self.config, now, charts=True)
                    self.assertEqual(result["schemaVersion"], 1)
                    self.assertNotEqual(result["sourceDate"], day)
                    for kind in ("metrics", "wellness", "history", "supplementalHistory"):
                        for records in result[kind].values():
                            point = records[-1] if isinstance(records, list) else records
                            self.assertEqual(point["date"], day)
                            self.assertEqual({key: point[key] for key in expected}, expected)
                            self.assertEqual(point["to"] - point["from"], hours * 3600000)
                    self.assertIsNone(result["history"]["sleep"][-1]["value"])
                    self.assertEqual(result["metrics"]["steps"]["value"], 0)

    def test_source_day_bounds_old_cache_and_retained_series(self):
        type(self).response = payload(charts=True)
        self.wellness_fixture()
        initial = b.run("fetch", self.config, NOW, charts=True)
        path, identity = b.cache_location(self.config)
        original = json.loads(path.read_text())
        later = NOW + timedelta(days=2)
        for forged in (False, True):
            envelope = copy.deepcopy(original)
            for kind in ("metrics", "wellness", "history", "supplementalHistory"):
                for records in envelope["data"][kind].values():
                    for point in records if isinstance(records, list) else [records]:
                        if forged:
                            point.update({"from": "private-forged", "to": 1, "secret": "private-tag"})
                        else:
                            point.pop("from", None)
                            point.pop("to", None)
            path.write_text(json.dumps(envelope))
            cached = b.run("cache", self.config, later, charts=True)
            self.assertNotIn("private-", json.dumps(cached))
            for kind in ("history", "supplementalHistory"):
                self.assertEqual(cached[kind], initial[kind])
            for kind in ("metrics", "wellness"):
                for key, point in cached[kind].items():
                    self.assertEqual(point["from"], initial[kind][key]["from"])
                    self.assertEqual(point["to"], initial[kind][key]["to"])
        type(self).response = payload(later, charts=True)
        self.wellness_fixture(later)
        healthy = type(self).supplemental_response
        type(self).supplemental_response = staticmethod(lambda query: (
            {"error": "private-error"} if 'FROM "TrainingReadiness"' in query else healthy(query)))
        type(self).history_response = {"error": "private-error"}
        retained = b.run("fetch", self.config, later, charts=True)
        self.assertEqual(retained["history"], initial["history"])
        self.assertEqual(retained["supplementalHistory"]["trainingReadiness"],
                         initial["supplementalHistory"]["trainingReadiness"])
        self.assertEqual(retained["wellness"]["trainingReadiness"]["from"],
                         initial["wellness"]["trainingReadiness"]["from"])
        self.assertGreater(retained["supplementalHistory"]["sleepDuration"][-1]["from"],
                           retained["supplementalHistory"]["trainingReadiness"][-1]["from"])
        cached = b.run("cache", self.config, later, charts=True)
        self.assertEqual(cached["supplementalHistory"], retained["supplementalHistory"])
        self.assertNotIn("private-", json.dumps(retained))

    def test_source_day_bounds_null_metrics_and_cli_output(self):
        type(self).response = payload(charts=True)
        self.response["results"][0]["series"][0]["values"][0][1] = None
        self.response["results"][1].pop("series")
        config = self.config_file({"url": self.url})
        with patch.object(b, "datetime", wraps=datetime) as clock:
            clock.now.return_value = NOW
            for command in ("fetch", "cache"):
                code, result = self.cli(command, "--config", str(config), "--charts")
                self.assertEqual(code, 0)
                missing = result["metrics"]["steps"]
                self.assertIsNone(missing["value"])
                self.assertIsNone(missing["date"])
                self.assertNotIn("from", missing)
                self.assertNotIn("to", missing)
                dated = result["metrics"]["bodyBattery"]
                self.assertIsNone(dated["value"])
                self.assertEqual(dated["state"], "missing")
                self.assertEqual(dated["date"], "2026-09-05")
                self.assertEqual(dated["from"], 1788562800000)
                self.assertEqual(dated["to"], 1788649200000)
                for point in result["wellness"].values():
                    self.assertNotIn("from", point)
                    self.assertNotIn("to", point)
        demo = b.demo(NOW, True)
        self.assertIn("from", demo["metrics"]["steps"])
        self.assertIn("to", demo["supplementalHistory"]["sleepDuration"][-1])

    def test_steps_expiry_uses_source_midnight_across_dst(self):
        for sample, expiry, hours in (("2026-03-29T00:00:00Z", "2026-03-29T23:00:00Z", 23),
                                       ("2026-10-24T23:00:00Z", "2026-10-26T00:00:00Z", 25)):
            with self.subTest(sample=sample):
                now = b.timestamp(sample)
                type(self).response = payload(now)
                result, _ = b.fetch(self.config, now)
                self.assertEqual(result["sourceDayStart"], sample)
                self.assertEqual(result["sourceDayEnd"], expiry)
                self.assertEqual(b.empty(now, self.config["timezone"])["sourceDayEnd"], expiry)
                self.assertEqual(result["metrics"]["steps"]["expiresAt"], expiry)
                self.assertEqual(b.timestamp(expiry) - now, timedelta(hours=hours))
                b.refresh_states(result, b.timestamp(expiry) - timedelta(microseconds=1))
                self.assertEqual(result["sourceDayStart"], sample)
                self.assertEqual(result["sourceDayEnd"], expiry)
                self.assertEqual(result["metrics"]["steps"]["state"], "fresh")
                b.refresh_states(result, b.timestamp(expiry))
                self.assertEqual(result["sourceDayStart"], expiry)
                self.assertEqual(result["metrics"]["steps"]["state"], "stale")

    def test_dst_chart_calendar_boundaries(self):
        for now, start in ((datetime(2026, 3, 30, 12, tzinfo=b.UTC), "2026-03-24T00:00:00Z"),
                           (datetime(2026, 10, 26, 12, tzinfo=b.UTC), "2026-10-19T23:00:00Z")):
            with self.subTest(now=now):
                type(self).response = payload(now, charts=True)
                result, _ = b.fetch(self.config, now, charts=True)
                query = parse_qs(urlsplit(self.requests[-1][1]).query)["q"][0]
                self.assertIn("time >= '" + start + "'", query.split(";")[5])
                self.assertEqual(len(result["charts"]["steps"]), 7)
                self.assertEqual(len({p["date"] for p in result["charts"]["sleep"]}), 7)
                self.assertIsNone(result["charts"]["steps"][0]["value"])

    def test_intraday_charts_cover_rolling_day_and_full_fall_dst_source_day(self):
        for instant, start, day_start, day_end in (
                ("2026-09-05T10:00:00Z", "2026-09-04T10:00:00Z",
                 "2026-09-04T23:00:00Z", "2026-09-05T23:00:00Z"),
                ("2026-03-29T22:30:00Z", "2026-03-28T22:30:00Z",
                 "2026-03-29T00:00:00Z", "2026-03-29T23:00:00Z"),
                ("2026-10-25T23:30:00Z", "2026-10-24T23:00:00Z",
                 "2026-10-24T23:00:00Z", "2026-10-26T00:00:00Z")):
            with self.subTest(now=instant):
                now = b.timestamp(instant)
                type(self).response = payload(now, charts=True)
                self.response["results"][4]["series"][0]["values"] = [[instant, 20], [start, 80]]

                def response(query):
                    if query.startswith('SELECT "stressLevel"') and "LIMIT 2001" in query:
                        self.assertIn("time >= '" + start + "'", query)
                        return supplemental_payload("StressIntraday", ("stressLevel",),
                                                    [[instant, 20], [start, 80]])
                    return {"results": [{"statement_id": n}
                                        for n in range(query.count('SELECT MEAN(') or 1)]}

                type(self).supplemental_response = staticmethod(response)
                result = b.run("fetch", self.config, now, charts=True)
                query = parse_qs(urlsplit(self.requests[-1][1]).query)["q"][0].split(";")[4]
                self.assertIn("time >= '" + start + "'", query)
                self.assertEqual(result["status"], "ok")
                self.assertIsNone(result["stressError"])
                expected = [{"time": start, "value": 80}, {"time": instant, "value": 20}]
                self.assertEqual(result["charts"]["bodyBattery"], expected)
                self.assertEqual(result["stressSeries"], expected)
                self.assertEqual(result["sourceDayStart"], day_start)
                self.assertEqual(result["sourceDayEnd"], day_end)
                for read_at in (now, b.timestamp(day_end)):
                    cached = b.run("cache", self.config, read_at, charts=True)
                    self.assertEqual(cached["charts"], result["charts"])
                    self.assertEqual(cached["stressSeries"], expected)
                    self.assertEqual(cached["sourceDayStart"], day_start if read_at == now else day_end)
                    self.assertEqual(cached["sourceDayEnd"], day_end if read_at == now else
                                     b.iso(b.timestamp(day_end) + timedelta(days=1)))

    def test_daily_chart_latest_not_sum_and_sorted_body_battery(self):
        type(self).response = payload(charts=True)
        self.response["results"][5]["series"][0]["values"] = [[b.iso(NOW - timedelta(hours=1)), 500], [b.iso(NOW), 800]]
        self.response["results"][4]["series"][0]["values"] = [[b.iso(NOW), 0], [b.iso(NOW - timedelta(hours=1)), 20]]
        result = b.run("fetch", self.config, NOW, charts=True)
        self.assertEqual(result["charts"]["steps"][-1]["value"], 800)
        self.assertEqual([p["value"] for p in result["charts"]["bodyBattery"]], [20, 0])
        self.assertEqual(len(self.requests), 1)

    def test_cache_retains_charts_without_refreshing_timestamp(self):
        type(self).response = payload(charts=True)
        initial = b.run("fetch", self.config, NOW, charts=True)
        type(self).response = payload(NOW + timedelta(hours=1))
        summary = b.run("fetch", self.config, NOW + timedelta(hours=1))
        self.assertEqual(summary["charts"]["steps"], [])
        cached = b.run("cache", self.config, NOW + timedelta(hours=1), charts=True)
        self.assertEqual(cached["charts"], initial["charts"])
        self.assertEqual(cached["chartsFetchedAt"], b.iso(NOW))
        self.assertEqual(cached["fetchedAt"], b.iso(NOW + timedelta(hours=1)))

    def test_changed_inferred_source_does_not_retain_charts(self):
        type(self).response = payload(charts=True)
        b.run("fetch", self.config, NOW, charts=True)
        type(self).response = payload(tags={**TAGS, "Device": "Other"})
        b.run("fetch", self.config, NOW)
        cached = b.run("cache", self.config, NOW, charts=True)
        self.assertEqual(cached["charts"]["steps"], [])
        self.assertIsNone(cached["chartsFetchedAt"])
        self.assertEqual(cached["device"], {"name": "Other", "source": "Device"})

    def test_identity_segregation_and_password_rotation(self):
        b.run("fetch", self.config, NOW)
        for key, value in (("url", "https://example.invalid"), ("database", "Other"),
                           ("username", "other"), ("timezone", "UTC"), ("tags", {"Device": "Other"})):
            with self.subTest(key=key), self.assertRaisesRegex(b.Failure, "^cache_miss$"):
                b.run("cache", {**self.config, key: value}, NOW)
        rotated = b.run("cache", {**self.config, "password": "synthetic-password"}, NOW)
        self.assertEqual(rotated["status"], "cached")
        self.assertEqual(len(self.requests), 1)

    def test_auth_failure_retains_valid_cache(self):
        b.run("fetch", self.config, NOW)
        type(self).http_status = 401
        result = b.run("fetch", self.config, NOW)
        self.assertEqual((result["status"], result["error"]), ("cached", "auth_error"))
        self.assertEqual(result["device"], {"name": "Fixture", "source": "Device"})
        self.assertEqual(b.run("cache", self.config, NOW)["error"], None)

    def test_malformed_responses(self):
        for raw in (b"{", b"[]", b'{"results":null}', b'{"results":[]}'):
            with self.subTest(raw=raw), self.assertRaisesRegex(b.Failure, "^invalid_response$"):
                type(self).raw = raw
                b.fetch(self.config, NOW)
        type(self).raw = None
        for value in (float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaisesRegex(b.Failure, "^invalid_response$"):
                type(self).response = payload()
                self.response["results"][0]["series"][0]["values"][0][1] = value
                b.fetch(self.config, NOW)

    def test_bad_timestamp_and_row_shape(self):
        for row in (("yesterday", 1), ("2026-09-05T10:00:00", 1), (b.iso(NOW),), (b.iso(NOW + timedelta(seconds=1)), 1)):
            with self.subTest(row=row), self.assertRaisesRegex(b.Failure, "^invalid_response$"):
                type(self).response = payload()
                self.response["results"][0]["series"][0]["values"] = [row]
                b.fetch(self.config, NOW)

    def test_response_size_and_truncation(self):
        type(self).content_length = b.MAX_BYTES + 1
        with self.assertRaisesRegex(b.Failure, "^response_too_large$"):
            b.fetch(self.config, NOW)
        type(self).raw = b" " * (b.MAX_BYTES + 1)
        type(self).content_length = "omit"
        with self.assertRaisesRegex(b.Failure, "^response_too_large$"):
            b.fetch(self.config, NOW)
        type(self).raw = b"{}"
        type(self).content_length = 100
        with self.assertRaisesRegex(b.Failure, "^invalid_response$"):
            b.fetch(self.config, NOW)
        type(self).raw = None
        type(self).content_length = None
        self.response["results"][0]["series"][0]["partial"] = True
        with self.assertRaisesRegex(b.Failure, "^truncated_response$"):
            b.fetch(self.config, NOW)
        type(self).response = payload(charts=True)
        self.response["results"][4]["series"][0]["values"] *= 2001
        with self.assertRaisesRegex(b.Failure, "^truncated_response$"):
            b.fetch(self.config, NOW, charts=True)

    def test_multiple_series_and_cross_measurement_sources_refused(self):
        b.run("fetch", self.config, NOW)
        self.response["results"][0]["series"] *= 2
        with self.assertRaisesRegex(b.Failure, "^ambiguous_source$"):
            b.fetch(self.config, NOW)
        cached = b.run("fetch", self.config, NOW)
        self.assertEqual((cached["status"], cached["error"]), ("cached", "ambiguous_source"))
        self.assertEqual(cached["device"], {"name": "Fixture", "source": "Device"})
        for tags in ({**TAGS, "User_ID": "other"}, {**TAGS, "Device": "Other"}):
            with self.subTest(tags=tags):
                type(self).response = payload()
                self.response["results"][1]["series"][0]["tags"] = tags
                with self.assertRaisesRegex(b.Failure, "^ambiguous_source$"):
                    b.fetch(self.config, NOW)

    def test_escaped_filters_get_only_auth_headers_and_no_proxies(self):
        tags = {'Device"\\': "watch'\\; DROP DATABASE x"}
        self.config.update(tags=tags, username="fixture-user", password="fixture-secret")
        type(self).response = payload(tags=tags)
        b.fetch(self.config, NOW)
        method, path, headers = self.requests[0]
        self.assertEqual(method, "GET")
        self.assertEqual(urlsplit(path).path, "/query")
        self.assertNotIn("fixture-secret", path)
        self.assertNotIn("fixture-user", path)
        self.assertTrue(headers["Authorization"].startswith("Basic "))
        query = parse_qs(urlsplit(path).query)["q"][0]
        self.assertIn('"Device\\"\\\\" = \'watch\\\'\\\\; DROP DATABASE x\'', query)
        self.assertTrue(query.startswith("SELECT "))
        self.assertIn("GROUP BY *", query)
        self.assertIn("SLIMIT 2", query)

    def test_redirect_auth_query_errors_are_sanitized(self):
        path = self.config_file({"url": self.url, "password": "fixture-secret"})
        for status, expected in ((302, "redirect_refused"), (401, "auth_error"), (403, "auth_error"), (500, "http_error")):
            with self.subTest(status=status):
                type(self).http_status = status
                type(self).raw = b"fixture-secret raw health record"
                code, result = self.cli("doctor", "--config", str(path))
                self.assertEqual(code, 1)
                self.assertEqual(result["error"], expected)
                self.assertIsNone(result["device"])
                self.assertNotIn("fixture-secret", json.dumps(result))
        self.assertEqual(len(self.requests), 4)
        type(self).http_status = 200
        type(self).raw = None
        type(self).response = {"error": "fixture-secret"}
        self.assertEqual(self.cli("doctor", "--config", str(path))[1]["error"], "query_error")

    def test_doctor_no_health_values_or_cache(self):
        type(self).response = payload(tags={"Device": "private-watch", "User_ID": "private-user"})
        path = self.config_file({"url": self.url})
        code, result = self.cli("doctor", "--config", str(path))
        self.assertEqual(code, 0)
        self.assertTrue(all(m["value"] is None for m in result["metrics"].values()))
        self.assertIsNone(result["device"])
        self.assertNotIn("private-", json.dumps(result))
        self.assertFalse((Path(self.temp.name) / "omarchy-garmin-glance").exists())

    def test_demo_bypasses_config_network_and_cache(self):
        with patch.object(b, "load_config", side_effect=AssertionError), patch.object(b, "request", side_effect=AssertionError):
            code, result = self.cli("fetch", "--demo", "--charts", "--config", "/does/not/exist")
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "demo")
        self.assertEqual(result["device"], {"name": "Forerunner 965", "source": "demo"})
        self.assertEqual(len(result["charts"]["steps"]), 7)
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_invalid_args_sanitized(self):
        for args in (("fetch", "--password", "fixture-secret"), ("doctor", "--demo"), ("unknown",), ()):
            code, result = self.cli(*args)
            self.assertEqual(code, 1)
            self.assertEqual(result["error"], "invalid_arguments")

    def test_private_config_and_url_policy(self):
        path = self.config_file({"url": self.url})
        self.assertEqual(b.load_config(path)["database"], "GarminStats")
        path.chmod(0o644)
        with self.assertRaisesRegex(b.Failure, "^invalid_config$"):
            b.load_config(path)
        for url in ("http://example.com", "http://127.0.0.1.evil", "http://user:pass@127.0.0.1",
                    "http://127.0.0.1?password=oops", "ftp://127.0.0.1", "http://127.0.0.1/path",
                    "http://127.0.0.1:bad", "http://127.0.0.1#fragment"):
            with self.subTest(url=url), self.assertRaisesRegex(b.Failure, "^invalid_config$"):
                b.load_config(self.config_file({"url": url}))
        for url in ("http://localhost:8086", "http://[::1]:8086", "https://remote.example"):
            with self.subTest(url=url):
                self.assertIn("://", b.load_config(self.config_file({"url": url}))["url"])
        for config in ({"timezone": "not/a/zone"}, {"tags": []}, {"tags": {"Device": 1}}, {"extra": 1}):
            with self.subTest(config=config), self.assertRaisesRegex(b.Failure, "^invalid_config$"):
                b.load_config(self.config_file(config))

    def test_default_config_missing_explicit_config_and_symlinks(self):
        with patch.dict(os.environ, {"HOME": self.temp.name}):
            self.assertEqual(b.load_config(), b.DEFAULTS)
            with self.assertRaisesRegex(b.Failure, "^invalid_config$"):
                b.load_config(Path(self.temp.name) / ".config/omarchy-garmin-glance/connection.json")
        target = self.config_file({"url": self.url})
        link = Path(self.temp.name) / "link.json"
        link.symlink_to(target)
        with self.assertRaisesRegex(b.Failure, "^invalid_config$"):
            b.load_config(link)

    def test_cache_private_atomic_and_corruption(self):
        b.run("fetch", self.config, NOW)
        path, key = b.cache_location(self.config)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(list(path.parent.glob(".cache-*")), [])
        self.assertNotIn("password", path.read_text())
        envelope = json.loads(path.read_text())
        envelope["data"]["metrics"]["steps"]["value"] = "bad"
        path.write_text(json.dumps(envelope))
        self.assertIsNone(b.read_cache(path, key, self.config, NOW))
        with self.assertRaisesRegex(b.Failure, "^cache_miss$"):
            b.run("cache", self.config, NOW)
        for invalid in ([], None, {"identity": key, "data": []},
                        {"identity": key, "data": {"metrics": {}, "charts": []}}):
            with self.subTest(invalid=invalid):
                path.write_text(json.dumps(invalid))
                self.assertIsNone(b.read_cache(path, key, self.config, NOW))

    def test_failed_atomic_write_keeps_previous_cache(self):
        b.run("fetch", self.config, NOW)
        path, _ = b.cache_location(self.config)
        before = path.read_bytes()
        with patch.object(b.os, "replace", side_effect=OSError):
            result = b.run("fetch", self.config, NOW)
        self.assertEqual((result["status"], result["error"]), ("cached", "cache_error"))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(path.parent.glob(".cache-*")), [])

    def test_cache_symlink_refused_and_lock_without_cache(self):
        path, _ = b.cache_location(self.config)
        target = self.config_file({})
        path.symlink_to(target)
        with self.assertRaisesRegex(b.Failure, "^cache_miss$"):
            b.run("cache", self.config, NOW)
        with path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(b.Failure, "^fetch_locked$"):
                b.run("fetch", self.config, NOW)
        self.assertEqual(len(self.requests), 0)

    def test_fetch_lock_returns_cache_without_network(self):
        b.run("fetch", self.config, NOW)
        path, _ = b.cache_location(self.config)
        with path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = b.run("fetch", self.config, NOW)
        self.assertEqual((result["status"], result["error"]), ("cached", "fetch_locked"))
        self.assertEqual(result["device"], {"name": "Fixture", "source": "Device"})
        self.assertEqual(len(self.requests), 1)

    def test_timeout_and_network_error(self):
        with patch.object(b.urllib.request.OpenerDirector, "open", side_effect=TimeoutError):
            with self.assertRaisesRegex(b.Failure, "^timeout$"):
                b.fetch(self.config, NOW)
        with patch.object(b.urllib.request.OpenerDirector, "open", side_effect=b.urllib.error.URLError("secret")):
            with self.assertRaisesRegex(b.Failure, "^network_error$"):
                b.fetch(self.config, NOW)

    def test_summary_latest_nonnull_per_field_keeps_its_timestamp(self):
        older = NOW - timedelta(days=2)
        self.response["results"][3]["series"][0]["values"] = [[b.iso(older), 42]]
        result, _ = b.fetch(self.config, NOW)
        self.assertEqual(result["metrics"]["sleep"]["state"], "fresh")
        self.assertEqual(result["metrics"]["hrv"]["time"], b.iso(older))
        self.assertEqual(result["metrics"]["hrv"]["state"], "stale")
        statements = parse_qs(urlsplit(self.requests[-1][1]).query)["q"][0].split(";")
        self.assertEqual(len(statements), 4)
        for statement, (_, field, _) in zip(statements, b.METRICS.values()):
            self.assertTrue(statement.startswith('SELECT "' + field + '" FROM '))
            self.assertIn('"' + field + '" >= 0', statement)
            self.assertIn("ORDER BY time DESC LIMIT 1 SLIMIT 2", statement)

    def test_metric_ranges_do_not_discard_unrelated_values(self):
        for index, key in enumerate(b.METRICS):
            invalid = [-1, "12", True, {}]
            if key in ("bodyBattery", "sleep"):
                invalid.extend([101, 1e100])
            for value in invalid:
                with self.subTest(metric=key, value=value):
                    type(self).response = payload()
                    self.response["results"][index]["series"][0]["values"][0][1] = value
                    result, _ = b.fetch(self.config, NOW)
                    self.assertEqual(result["status"], "partial")
                    self.assertIsNone(result["metrics"][key]["value"])
                    self.assertTrue(all(m["value"] == 0 for k, m in result["metrics"].items() if k != key))
        for index, value in ((0, 100), (1, 10**13), (2, 100), (3, 10**13)):
            type(self).response = payload()
            self.response["results"][index]["series"][0]["values"][0][1] = value
            self.assertEqual(list(b.fetch(self.config, NOW)[0]["metrics"].values())[index]["value"], value)

    def test_partial_refresh_preserves_cached_metric_without_rejuvenating_it(self):
        b.run("fetch", self.config, NOW)
        later = NOW + timedelta(hours=3)
        type(self).response = payload(later)
        self.response["results"][0].pop("series")
        self.response["results"][1]["series"][0]["values"][0][1] = 123456
        result = b.run("fetch", self.config, later)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["metrics"]["bodyBattery"]["value"], 0)
        self.assertEqual(result["metrics"]["bodyBattery"]["time"], b.iso(NOW))
        self.assertEqual(result["metrics"]["bodyBattery"]["state"], "stale")
        self.assertEqual(result["metrics"]["steps"]["value"], 123456)
        cached = b.run("cache", self.config, later)
        self.assertEqual(cached["metrics"], result["metrics"])
        self.assertEqual(result["device"], {"name": "Fixture", "source": "Device"})
        self.assertEqual(cached["device"], result["device"])

    def test_missing_refresh_and_changed_source_cache_safety(self):
        b.run("fetch", self.config, NOW)
        type(self).response = {"results": [{"statement_id": n} for n in range(4)]}
        result = b.run("fetch", self.config, NOW + timedelta(days=31))
        self.assertTrue(all(m["value"] == 0 and m["state"] == "stale" for m in result["metrics"].values()))
        self.assertEqual(result["device"], {"name": "Fixture", "source": "Device"})
        self.assertEqual(b.run("cache", self.config, NOW + timedelta(days=31))["device"], result["device"])
        type(self).response = payload(NOW + timedelta(days=31), tags={**TAGS, "User_ID": "other"})
        self.response["results"][0].pop("series")
        result = b.run("fetch", self.config, NOW + timedelta(days=31))
        self.assertIsNone(result["metrics"]["bodyBattery"]["value"])

    def test_statement_failure_keeps_live_unrelated_metrics_and_cached_charts(self):
        type(self).response = payload(charts=True)
        initial = b.run("fetch", self.config, NOW, charts=True)
        later = NOW + timedelta(hours=3)
        type(self).response = payload(later, charts=True)
        self.response["results"][0] = {"statement_id": 0, "error": "private server text"}
        self.response["results"][5] = {"statement_id": 5, "error": "private server text"}
        self.response["results"][1]["series"][0]["values"][0][1] = 100001
        type(self).statements = b.queries(self.config, later, True)[1]
        result = b.run("fetch", self.config, later, charts=True)
        self.assertEqual((result["status"], result["error"]), ("partial", "query_error"))
        self.assertEqual(result["metrics"]["bodyBattery"]["state"], "stale")
        self.assertEqual(result["metrics"]["steps"]["value"], 100001)
        self.assertEqual(result["charts"]["steps"], initial["charts"]["steps"])
        self.assertEqual(result["charts"]["bodyBattery"][-1]["time"], b.iso(later))
        self.assertEqual(result["chartsFetchedAt"], initial["chartsFetchedAt"])
        self.assertNotIn("private server text", json.dumps(result))
        self.assertEqual(b.run("cache", self.config, later)["metrics"], result["metrics"])
        self.assertEqual(len(self.requests), 8)  # One cache seed, then batch plus six retries.
        self.assertEqual([parse_qs(urlsplit(path).query)["q"][0] for _, path, _ in self.requests[2:]],
                         self.statements[1:])

    def test_chart_ranges_and_natural_body_battery_count(self):
        type(self).response = payload(charts=True)
        self.response["results"][4]["series"][0]["values"] = [
            [b.iso(NOW - timedelta(minutes=2 * n)), 100] for n in range(720)]
        self.response["results"][5]["series"][0]["values"][0][1] = 100001
        self.response["results"][6]["series"][0]["values"][0][1] = 101
        result = b.run("fetch", self.config, NOW, charts=True)
        self.assertEqual(len(result["charts"]["bodyBattery"]), 720)
        self.assertEqual(result["charts"]["steps"][-1]["value"], 100001)
        self.assertIsNone(result["charts"]["sleep"][-1]["value"])

    def test_cache_rejects_out_of_range_metrics_and_chart_values(self):
        type(self).response = payload(charts=True)
        b.run("fetch", self.config, NOW, charts=True)
        path, key = b.cache_location(self.config)
        original = json.loads(path.read_text())
        for section, name, value in (("metrics", "bodyBattery", 101), ("metrics", "sleep", -1),
                                     ("metrics", "steps", -1), ("metrics", "hrv", -1),
                                     ("charts", "bodyBattery", 101), ("charts", "sleep", 101),
                                     ("charts", "steps", -1)):
            with self.subTest(section=section, name=name):
                envelope = copy.deepcopy(original)
                target = envelope["data"][section][name]
                (target if section == "metrics" else target[-1])["value"] = value
                path.write_text(json.dumps(envelope))
                self.assertIsNone(b.read_cache(path, key, self.config, NOW))

    def test_upstream_optional_user_tag_and_chart_source_checks(self):
        for tags in (TAGS, {**TAGS, "User_ID": "synthetic-display-name"}, {}):
            with self.subTest(tags=tags):
                type(self).response = payload(charts=True, tags=tags)
                result, source = b.fetch(self.config, NOW, charts=True)
                self.assertEqual(result["status"], "ok")
                self.assertEqual(json.loads(source), tags)
        self.response["results"][6]["series"][0]["tags"] = TAGS
        with self.assertRaisesRegex(b.Failure, "^ambiguous_source$"):
            b.fetch(self.config, NOW, charts=True)
        type(self).response = payload()
        self.config["tags"] = {"User_ID": "selected"}
        with self.assertRaisesRegex(b.Failure, "^ambiguous_source$"):
            b.fetch(self.config, NOW)

    def test_statement_error_without_cache_keeps_other_metrics(self):
        type(self).response = payload(charts=True)
        self.response["results"][2] = {"statement_id": 2, "error": "private error"}
        self.response["results"][5] = {"statement_id": 5, "error": "private error"}
        type(self).statements = b.queries(self.config, NOW, True)[1]
        result = b.run("fetch", self.config, NOW, charts=True)
        self.assertEqual((result["status"], result["error"]), ("partial", "query_error"))
        self.assertIsNone(result["metrics"]["sleep"]["value"])
        self.assertTrue(all(m["value"] == 0 for k, m in result["metrics"].items() if k != "sleep"))
        self.assertEqual(len(result["charts"]["bodyBattery"]), 1)
        self.assertEqual(len(result["charts"]["sleep"]), 7)
        self.assertEqual(result["charts"]["steps"], [])
        self.assertEqual(len(self.requests), 5)
        self.assertEqual([parse_qs(urlsplit(path).query)["q"][0] for _, path, _ in self.requests[1:]],
                         self.statements[3:])

    def test_summary_recovery_preserves_quoted_semicolons(self):
        tags = {"Device": "watch'; SELECT secret\\"}
        self.config["tags"] = tags
        type(self).response = payload(tags=tags)
        self.response["results"][0] = {"statement_id": 0, "error": "private error"}
        type(self).statements = b.queries(self.config, NOW, False)[1]
        result, _ = b.fetch(self.config, NOW)
        self.assertEqual(len(self.requests), 4)
        self.assertTrue(all(m["state"] == "fresh" for k, m in result["metrics"].items() if k != "bodyBattery"))
        self.assertEqual([parse_qs(urlsplit(path).query)["q"][0] for _, path, _ in self.requests[1:]],
                         self.statements[1:])

    def test_recovery_validates_single_statement_before_remapping(self):
        initial = payload()
        initial["results"][2] = {"statement_id": 2, "error": "private error"}
        initial["results"][3] = {"statement_id": 3, "error": "not executed"}
        for retry in ([], {}, {"results": []}, {"results": [{"statement_id": 3}]},
                      {"results": [{"statement_id": False}]},
                      {"results": [{"statement_id": 0}, {"statement_id": 1}]}):
            with self.subTest(retry=retry), patch.object(b, "request", side_effect=[initial, retry]):
                with self.assertRaisesRegex(b.Failure, "^invalid_response$"):
                    b.fetch(self.config, NOW)
        recovered = {**payload()["results"][3], "statement_id": 0}
        with patch.object(b, "request", side_effect=[initial, {"results": [recovered]}]):
            result, _ = b.fetch(self.config, NOW, extras=False)
        self.assertEqual(result["metrics"]["hrv"]["state"], "fresh")
        self.assertEqual(recovered["statement_id"], 0)

    def test_recovery_failure_does_not_stop_later_healthy_statements(self):
        initial = {"results": [{"statement_id": n, "error": "private error" if n == 0 else "not executed"}
                               for n in range(4)]}
        recovered = {"results": [{**payload()["results"][3], "statement_id": 0}]}
        for failure in (b.Failure("timeout"), {"error": "private body"},
                        {"results": [{"statement_id": 0, "error": "not executed"}]}):
            with self.subTest(failure=failure), patch.object(
                    b, "request", side_effect=[initial, failure, failure, recovered]) as request:
                result, _ = b.fetch(self.config, NOW, extras=False)
                self.assertEqual(request.call_count, 4)
                self.assertEqual(result["metrics"]["hrv"]["state"], "fresh")
                self.assertEqual((result["status"], result["error"]), ("partial", "query_error"))
                self.assertNotIn("private", json.dumps(result))

    def test_recovery_shares_monotonic_budget_with_initial_batch(self):
        initial = payload()
        initial["results"][1:] = [{"statement_id": n, "error": "private error" if n == 1 else "not executed"}
                                  for n in range(1, 4)]
        with patch.object(b, "monotonic", side_effect=[100, 105, 105, 108, 110]), patch.object(
                b, "request", side_effect=[initial, b.Failure("timeout")]) as request:
            result, _ = b.fetch(self.config, NOW, extras=False)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args.kwargs["timeout"], 2)
        self.assertEqual(result["metrics"]["bodyBattery"]["state"], "fresh")
        self.assertEqual(result["metrics"]["hrv"]["state"], "missing")

    def test_request_wall_clock_timeout_and_alarm_cleanup(self):
        previous = b.signal.getsignal(b.signal.SIGALRM)
        with patch.object(b.urllib.request.OpenerDirector, "open", side_effect=lambda *a, **kw: time.sleep(1)):
            started = time.monotonic()
            with self.assertRaisesRegex(b.Failure, "^timeout$"):
                b.request(self.config, "SELECT", timeout=0.02)
            self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(b.signal.getsignal(b.signal.SIGALRM), previous)
        self.assertEqual(b.signal.getitimer(b.signal.ITIMER_REAL), (0, 0))


    def test_optional_empty_contract_and_old_cache_defaults(self):
        expected = {"history": {key: [] for key in b.HISTORY_FIELDS}, "historyFetchedAt": None,
                    "latestActivity": None, "activityFetchedAt": None,
                    "activities": None, "activitiesFetchedAt": None, "activitiesError": None,
                    "activityError": None, "historyError": None}
        self.assertEqual({key: b.empty(NOW, "UTC")[key] for key in expected}, expected)
        b.run("fetch", self.config, NOW)
        path, identity = b.cache_location(self.config)
        envelope = json.loads(path.read_text())
        for key in expected:
            envelope["data"].pop(key)
        path.write_text(json.dumps(envelope))
        cached = b.read_cache(path, identity, self.config, NOW)["data"]
        self.assertEqual({key: cached[key] for key in expected}, expected)

    def test_activity_every_fetch_projected_global_summary(self):
        tags = {**TAGS, "User_ID": "synthetic-user", "Account": "synthetic-account"}
        type(self).response = payload(tags=tags)
        type(self).activity_response = activity_payload(tags)
        for charts in (False, True):
            type(self).response = payload(charts=charts, tags=tags)
            result = b.run("fetch", self.config, NOW, charts)
            self.assertEqual(result["latestActivity"], {
                "id": "123", "connectId": "123",
                "time": b.iso(NOW - timedelta(hours=1)), "type": "running", "durationSeconds": 1800,
                "distanceMeters": 5000, "calories": 350, "bmrCalories": 40, "selector": "synthetic",
                **{key: None for key in b.ACTIVITY_DETAILS}})
            self.assertIsNone(result["activityError"])
            self.assertEqual(result["activityFetchedAt"], b.iso(NOW))
            query = parse_qs(urlsplit(self.optional_requests[-2 if charts else -1][1]).query)["q"][0]
            self.assertIn('FROM "ActivitySummary"', query)
            self.assertIn(',*::tag', query)
            self.assertIn('"Activity_ID"', query)
            self.assertIn('"activityType" != \'No Activity\'', query)
            self.assertTrue(query.endswith("ORDER BY time DESC LIMIT 1"))
            self.assertNotIn("GROUP BY", query)
            self.assertNotIn("LAST(", query)
            self.assertNotIn("activityName", query)
            self.assertIn("time >= '" + b.iso(NOW - timedelta(days=365)) + "'", query)
            for key, value in tags.items():
                self.assertIn('"' + key + '" = \'' + value + "'", query)
            self.assertNotIn("synthetic-account", json.dumps(result))
        self.assertEqual(len(self.optional_requests), 3)

    def test_activity_id_validated_reconciled_and_old_cache(self):
        for value in ("0", "00123", "9" * 32):
            for shape in ("projected", "metadata", "both", "null-column"):
                with self.subTest(value=value, shape=shape):
                    type(self).activity_response = activity_payload(ActivityID=value)
                    entry = self.activity_response["results"][0]["series"][0]
                    if shape != "projected":
                        entry["tags"] = {"ActivityID": value}
                    if shape == "metadata":
                        index = entry["columns"].index("ActivityID")
                        entry["columns"].pop(index)
                        entry["values"][0].pop(index)
                    elif shape == "null-column":
                        entry["values"][0][entry["columns"].index("ActivityID")] = None
                    result = b.run("fetch", self.config, NOW)
                    self.assertEqual(result["latestActivity"]["id"], value)
                    self.assertEqual(b.run("cache", self.config, NOW)["latestActivity"], result["latestActivity"])
        path, key = b.cache_location(self.config)
        original = json.loads(path.read_text())
        for value in (None, 123, True, {}, "", "123 ", "+123", "12/3", "9" * 33, "\u0661", "\u00b2", "12\n"):
            with self.subTest(value=value):
                envelope = copy.deepcopy(original)
                envelope["data"]["latestActivity"]["id"] = value
                path.write_text(json.dumps(envelope))
                self.assertIsNone(b.read_cache(path, key, self.config, NOW))
                type(self).activity_response = activity_payload(ActivityID=value)
                result, _ = b.fetch(self.config, NOW)
                if value is None:
                    self.assertNotIn("id", result["latestActivity"])
                else:
                    self.assertIsNone(result["latestActivity"])
                    self.assertEqual(result["activityError"], "invalid_response")
        original["data"]["latestActivity"].pop("id")
        path.write_text(json.dumps(original))
        self.assertNotIn("id", b.read_cache(path, key, self.config, NOW)["data"]["latestActivity"])

    def test_connect_id_requires_matching_collector_field(self):
        type(self).response = payload(charts=True)
        for activity_id, marker, expected in (
                ("123", 123, "123"), ("123", "123", "123"),
                ("9007199254740993", 9007199254740993, "9007199254740993"),
                ("9" * 32, int("9" * 32), "9" * 32), ("00123", "00123", "00123"),
                ("00123", 123, None), ("123", 456, None), ("123", "456", None),
                ("123", None, None), ("123", 123.0, None), ("123", True, None),
                ("123", -123, None), ("123", {}, None), ("123", "123 ", None),
                ("123", "\u0661\u0662\u0663", None), ("0", 0, None), ("0", "0", None),
                ("123", 10**32, None)):
            with self.subTest(activity_id=activity_id, marker=marker):
                fields = {"ActivityID": activity_id, "Activity_ID": marker}
                type(self).activity_response = activity_payload(**fields)
                type(self).activities_response = activities_payload(fields)
                result = b.run("fetch", self.config, NOW, True)
                for item in (result["latestActivity"], result["activities"]["items"][0]):
                    self.assertEqual(item["id"], activity_id)
                    if expected is None:
                        self.assertNotIn("connectId", item)
                    else:
                        self.assertEqual(item["connectId"], expected)
                    self.assertNotIn("Activity_ID", item)
                self.assertIsNone(result["activityError"])
                self.assertIsNone(result["activitiesError"])
                cached = b.run("cache", self.config, NOW, True)
                self.assertEqual(cached["latestActivity"], result["latestActivity"])
                self.assertEqual(cached["activities"], result["activities"])

    def test_connect_id_manual_import_without_marker_and_tag_not_field(self):
        type(self).response = payload(charts=True)
        synthetic_id = "9876543210987654321"
        for metadata in (False, True):
            type(self).activity_response = activity_payload(ActivityID=synthetic_id)
            type(self).activities_response = activities_payload({"ActivityID": synthetic_id})
            for response in (self.activity_response, self.activities_response):
                entry = response["results"][0]["series"][0]
                index = entry["columns"].index("Activity_ID")
                entry["columns"].pop(index)
                entry["values"][0].pop(index)
                if metadata:
                    # A numeric ID in series tags still does not establish provenance.
                    entry["tags"] = {"ActivityID": synthetic_id}
            result = b.run("fetch", self.config, NOW, True)
            for item in (result["latestActivity"], result["activities"]["items"][0]):
                self.assertEqual(item["id"], synthetic_id)
                self.assertNotIn("connectId", item)
            self.assertIsNone(result["activityError"])
            self.assertIsNone(result["activitiesError"])

    def test_connect_id_matches_reconciled_tag_not_just_column(self):
        type(self).response = payload(charts=True)
        for metadata_id, expected in (("123", "123"), ("456", None)):
            type(self).activity_response = activity_payload(ActivityID=None)
            type(self).activities_response = activities_payload({"ActivityID": None})
            for response in (self.activity_response, self.activities_response):
                response["results"][0]["series"][0]["tags"] = {"ActivityID": metadata_id}
            result, _ = b.fetch(self.config, NOW, True)
            for item in (result["latestActivity"], result["activities"]["items"][0]):
                self.assertEqual(item["id"], metadata_id)
                self.assertEqual(item.get("connectId"), expected)

    def test_connect_id_cache_marker_validation_and_old_cache_no_promotion(self):
        type(self).response = payload(charts=True)
        type(self).activity_response = activity_payload()
        type(self).activities_response = activities_payload({})
        initial = b.run("fetch", self.config, NOW, True)
        path, key = b.cache_location(self.config)
        original = json.loads(path.read_text())
        for section in ("latestActivity", "activities"):
            for value in (None, 123, True, {}, "", "456", "123 ", "9" * 33, "\u0661"):
                with self.subTest(section=section, value=value):
                    envelope = copy.deepcopy(original)
                    item = envelope["data"][section]
                    if section == "activities":
                        item = item["items"][0]
                    item["connectId"] = value
                    path.write_text(json.dumps(envelope))
                    self.assertIsNone(b.read_cache(path, key, self.config, NOW))
        for item in (original["data"]["latestActivity"], original["data"]["activities"]["items"][0]):
            item.pop("connectId")
            item["Activity_ID"] = 123  # Unknown cache fields cannot promote an old ID.
        path.write_text(json.dumps(original))
        cached = b.read_cache(path, key, self.config, NOW)["data"]
        for item in (cached["latestActivity"], cached["activities"]["items"][0]):
            self.assertEqual(item["id"], "123")
            self.assertNotIn("connectId", item)
            self.assertNotIn("Activity_ID", item)
        self.assertEqual(initial["latestActivity"]["connectId"], "123")
        self.assertEqual(initial["activities"]["items"][0]["connectId"], "123")

    def test_connect_id_dedupe_does_not_borrow_or_fail_on_missing_marker(self):
        type(self).response = payload(charts=True)
        for rows in (({}, {"Activity_ID": None}), ({"Activity_ID": None}, {}),
                     ({}, {"Activity_ID": 456}, {})):
            type(self).activities_response = activities_payload(*rows)
            result, _ = b.fetch(self.config, NOW, True)
            self.assertIsNone(result["activitiesError"])
            self.assertEqual(len(result["activities"]["items"]), 1)
            self.assertNotIn("connectId", result["activities"]["items"][0])
        type(self).activities_response = activities_payload(
            {"time": b.iso(NOW - timedelta(hours=1))}, {"Activity_ID": None})
        result, _ = b.fetch(self.config, NOW, True)
        self.assertNotIn("connectId", result["activities"]["items"][0])
        for item in (b.demo(NOW, True)["latestActivity"], *b.demo(NOW, True)["activities"]["items"]):
            self.assertNotIn("connectId", item)

    def test_activities_window_query_and_raw_contract(self):
        tags = {**TAGS, "User_ID": "private-user", "Account": "private-account"}
        self.config["tags"] = {"Device": "Fixture"}
        type(self).response = payload(charts=True, tags=tags)
        type(self).activities_response = activities_payload(
            {"ActivityID": "00123", "time": "2026-08-29T23:00:00Z", "distance": 0},
            {"ActivityID": "456", "time": b.iso(NOW), "calories": None}, tags=tags)
        result = b.run("fetch", self.config, NOW, True)
        bundle = result["activities"]
        self.assertEqual(set(bundle), {"startDate", "endDate", "from", "to", "items"})
        self.assertEqual(bundle["startDate"], "2026-08-30")
        self.assertEqual(bundle["endDate"], "2026-09-05")
        self.assertEqual(bundle["from"], int(b.timestamp("2026-08-29T23:00:00Z").timestamp() * 1000))
        self.assertEqual(bundle["to"], int(b.timestamp("2026-09-05T23:00:00Z").timestamp() * 1000))
        self.assertEqual([item["id"] for item in bundle["items"]], ["456", "00123"])
        self.assertEqual(bundle["items"][0], {"id": "456", "time": b.iso(NOW), "date": "2026-09-05",
            "type": "running", "durationSeconds": 1800, "distanceMeters": 5000, "calories": None})
        self.assertEqual(bundle["items"][1]["date"], "2026-08-30")
        self.assertEqual(bundle["items"][1]["distanceMeters"], 0)
        self.assertEqual(result["activitiesFetchedAt"], b.iso(NOW))
        self.assertIsNone(result["activitiesError"])
        self.assertNotIn("private-", json.dumps(result))
        self.assertEqual(len(self.activities_requests), 1)
        query = parse_qs(urlsplit(self.activities_requests[0][1]).query)["q"][0]
        self.assertTrue(query.startswith('SELECT "activityType","elapsedDuration","distance","calories","Activity_ID",*::tag FROM "ActivitySummary"'))
        self.assertTrue(query.endswith("ORDER BY time DESC LIMIT 501"))
        self.assertIn("time >= '2026-08-29T23:00:00Z'", query)
        self.assertIn("time <= '2026-09-05T10:00:00Z'", query)
        self.assertIn('"activityType" != \'No Activity\'', query)
        for key, value in tags.items():
            self.assertIn(b.quoted(key, '"') + " = " + b.quoted(value, "'"), query)
        for forbidden in ("GROUP BY", "SLIMIT", "SUM(", "LAST(", "bmrCalories"):
            self.assertNotIn(forbidden, query)

    def test_activities_dst_window_and_boundary_validation(self):
        for instant, start, end, hours in (
                ("2026-03-30T12:00:00Z", "2026-03-24T00:00:00Z", "2026-03-30T23:00:00Z", 167),
                ("2026-10-26T12:00:00Z", "2026-10-19T23:00:00Z", "2026-10-27T00:00:00Z", 169)):
            now = b.timestamp(instant)
            type(self).response = payload(now, True)
            for when, valid in ((start, True), (instant, True), (end, False),
                                (b.iso(b.timestamp(start) - timedelta(microseconds=1)), False),
                                (b.iso(now + timedelta(microseconds=1)), False)):
                with self.subTest(instant=instant, when=when):
                    type(self).activities_response = activities_payload({"time": when})
                    result, _ = b.fetch(self.config, now, True)
                    if valid:
                        self.assertEqual(result["activities"]["to"] - result["activities"]["from"], hours * 3600000)
                        self.assertEqual(result["activities"]["to"], int(b.timestamp(end).timestamp() * 1000))
                    else:
                        self.assertIsNone(result["activities"])
                        self.assertEqual(result["activitiesError"], "invalid_response")

    def test_activities_dedupe_latest_and_equal_time_conflicts(self):
        type(self).response = payload(charts=True)
        rows = [{"ActivityID": "2", "time": b.iso(NOW - timedelta(hours=1)), "distance": 100},
                {"ActivityID": "2", "distance": 200}, {"ActivityID": "1", "distance": 300}]
        for ordered in (rows, list(reversed(rows)), rows + [rows[1]]):
            type(self).activities_response = activities_payload(*ordered)
            result, _ = b.fetch(self.config, NOW, True)
            self.assertEqual([item["id"] for item in result["activities"]["items"]], ["1", "2"])
            self.assertEqual([item["distanceMeters"] for item in result["activities"]["items"]], [300, 200])
        # Conflicts in an older version cannot hide behind a newer row either.
        for conflicting in ({**rows[0], "distance": 999}, {**rows[1], "calories": 999}):
            type(self).activities_response = activities_payload(*rows, conflicting)
            result, _ = b.fetch(self.config, NOW, True)
            self.assertIsNone(result["activities"])
            self.assertEqual(result["activitiesError"], "invalid_response")

    def test_activities_raw_limit_before_dedupe(self):
        type(self).response = payload(charts=True)
        for count in (500, 501):
            type(self).activities_response = activities_payload(*([{}] * count))
            result, _ = b.fetch(self.config, NOW, True)
            if count == 500:
                self.assertEqual(len(result["activities"]["items"]), 1)
            else:
                self.assertIsNone(result["activities"])
                self.assertEqual(result["activitiesError"], "truncated_response")

    def test_activities_every_row_source_validated_before_dedupe(self):
        type(self).response = payload(charts=True)
        for foreign in ({"Device": "Other"}, {"Database_Name": "Other"}):
            type(self).activities_response = activities_payload({}, {"time": b.iso(NOW - timedelta(days=1)), **foreign})
            result, _ = b.fetch(self.config, NOW, True)
            self.assertIsNone(result["activities"])
            self.assertEqual(result["activitiesError"], "ambiguous_source")
        type(self).activities_response = activities_payload({})
        self.activities_response["results"][0]["series"][0]["tags"] = {"ActivityID": "456"}
        self.assertEqual(b.fetch(self.config, NOW, True)[0]["activitiesError"], "invalid_response")

    def test_activities_missing_invalid_id_and_malformed_rows_fail_bundle(self):
        type(self).response = payload(charts=True)
        for fields in ({"ActivityID": value} for value in (None, "", "12/3", "9" * 33, "\u0661", 123)):
            type(self).activities_response = activities_payload(fields)
            result, _ = b.fetch(self.config, NOW, True)
            self.assertIsNone(result["activities"])
            self.assertEqual(result["activitiesError"], "invalid_response")
            self.assertEqual((result["status"], result["error"]), ("ok", None))
        for mutation, error in (("row", "invalid_response"), ("partial", "truncated_response"),
                                ("series", "ambiguous_source"), ("placeholder", "invalid_response")):
            type(self).activities_response = activities_payload({})
            entry = self.activities_response["results"][0]["series"][0]
            if mutation == "row":
                entry["values"][0].pop()
            elif mutation == "partial":
                entry["partial"] = True
            elif mutation == "series":
                self.activities_response["results"][0]["series"] *= 2
            else:
                entry["values"][0][1] = "No Activity"
            self.assertEqual(b.fetch(self.config, NOW, True)[0]["activitiesError"], error)

    def test_activities_tag_metadata_and_nullable_numbers(self):
        type(self).response = payload(charts=True)
        for shape in ("metadata", "both", "null-column"):
            type(self).activities_response = activities_payload({"distance": -1, "calories": True, "elapsedDuration": "5"})
            entry = self.activities_response["results"][0]["series"][0]
            entry["tags"] = {**TAGS, "ActivityID": "123", "ActivitySelector": "synthetic"}
            if shape == "metadata":
                entry["columns"] = entry["columns"][:5]
                entry["values"][0] = entry["values"][0][:5]
            elif shape == "null-column":
                entry["values"][0][5:] = [None] * (len(entry["columns"]) - 5)
            result, _ = b.fetch(self.config, NOW, True)
            item = result["activities"]["items"][0]
            self.assertEqual(item["id"], "123")
            self.assertTrue(all(item[key] is None for key in ("durationSeconds", "distanceMeters", "calories")))

    def test_activities_cache_retention_empty_clear_and_runtime_strip(self):
        type(self).response = payload(charts=True)
        type(self).activities_response = activities_payload({})
        initial = b.run("fetch", self.config, NOW, True)
        later = NOW + timedelta(days=2)
        type(self).response = payload(later, True)
        type(self).activities_response = {"error": "private-error"}
        failed = b.run("fetch", self.config, later, True)
        self.assertEqual(failed["activities"], initial["activities"])
        self.assertEqual(failed["activitiesFetchedAt"], b.iso(NOW))
        self.assertEqual(failed["activitiesError"], "query_error")
        self.assertEqual((failed["status"], failed["error"]), ("ok", None))
        type(self).response = payload(later)
        for command in ("fetch", "cache"):
            stripped = b.run(command, self.config, later)
            for key in ("activities", "activitiesFetchedAt", "activitiesError"):
                self.assertIsNone(stripped[key])
        self.assertEqual(len(self.activities_requests), 2)
        cached = b.run("cache", self.config, later, True)
        for key in ("activities", "activitiesFetchedAt", "activitiesError"):
            self.assertEqual(cached[key], failed[key])
        type(self).http_status = 401
        self.assertEqual(b.run("fetch", self.config, later, True)["activities"], initial["activities"])
        type(self).http_status = 200
        type(self).response = payload(later, True)
        type(self).activities_response = activities_payload()
        cleared = b.run("fetch", self.config, later, True)
        self.assertEqual(cleared["activities"]["items"], [])
        self.assertEqual(cleared["activities"]["endDate"], "2026-09-07")
        self.assertEqual(cleared["activitiesFetchedAt"], b.iso(later))
        self.assertIsNone(cleared["activitiesError"])
        self.assertEqual(b.run("cache", self.config, later, True)["activities"], cleared["activities"])

    def test_activities_cache_source_isolation(self):
        for tags in ({**TAGS, "Device": "Other"}, {**TAGS, "User_ID": "Other"}, {}, None):
            type(self).response = payload(charts=True)
            type(self).activities_response = activities_payload({})
            b.run("fetch", self.config, NOW, True)
            type(self).response = (payload(charts=True, tags=tags) if tags is not None else
                                   {"results": [{"statement_id": n} for n in range(7)]})
            type(self).activities_response = {"error": "private-error"}
            result = b.run("fetch", self.config, NOW, True)
            self.assertIsNone(result["activities"])
            self.assertIsNone(result["activitiesFetchedAt"])
            self.assertIsNone(b.run("cache", self.config, NOW, True)["activities"])

    def test_activities_cache_reconstructs_bounds_and_rejects_malformed(self):
        type(self).response = payload(charts=True)
        type(self).activities_response = activities_payload({})
        initial = b.run("fetch", self.config, NOW, True)
        path, key = b.cache_location(self.config)
        original = json.loads(path.read_text())
        envelope = copy.deepcopy(original)
        bundle = envelope["data"]["activities"]
        bundle.update({"from": "forged", "to": 0, "private": "private"})
        bundle["items"][0].update({"selector": "private", "account": "private"})
        path.write_text(json.dumps(envelope))
        clean = b.read_cache(path, key, self.config, NOW + timedelta(days=10))["data"]
        self.assertEqual(clean["activities"], initial["activities"])
        self.assertNotIn("private", json.dumps(clean))
        for mutation in ("id", "date", "time", "duplicate", "oversize", "startDate", "endDate", "fetched", "error"):
            envelope = copy.deepcopy(original)
            bundle = envelope["data"]["activities"]
            if mutation == "id":
                bundle["items"][0]["id"] = "../123"
            elif mutation == "date":
                bundle["items"][0]["date"] = "2026-09-04"
            elif mutation == "time":
                bundle["items"][0]["time"] = b.iso(NOW + timedelta(seconds=1))
            elif mutation in ("duplicate", "oversize"):
                bundle["items"] *= 2 if mutation == "duplicate" else 501
            elif mutation in ("startDate", "endDate"):
                bundle[mutation] = "2026-01-01"
            elif mutation == "fetched":
                envelope["data"]["activitiesFetchedAt"] = None
            else:
                envelope["data"]["activitiesError"] = "private"
            path.write_text(json.dumps(envelope))
            self.assertIsNone(b.read_cache(path, key, self.config, NOW), mutation)

    def test_activities_order_deadline_and_no_gps_fanout(self):
        clock = [100]
        calls = []
        def respond(config, query, timeout):
            calls.append((query, timeout))
            if query.startswith('SELECT "BodyBatteryLevel"'):
                return payload(charts=True)
            if query.endswith("LIMIT 501"):
                self.assertEqual(timeout, 1)
                clock[0] = 110
                return activities_payload({}, {"ActivityID": "456"})
            if query.startswith('SELECT "activityType"'):
                return activity_payload()
            if query.startswith('SELECT "stressLevel"') and "LIMIT 2001" in query:
                clock[0] = 109
            return {"results": [{"statement_id": n} for n in range(query.count(";") + 1)]}
        with patch.object(b, "monotonic", side_effect=lambda: clock[0]), patch.object(b, "request", side_effect=respond):
            result, _ = b.fetch(self.config, NOW, True)
        self.assertEqual(len(result["activities"]["items"]), 2)
        self.assertTrue(calls[-1][0].endswith("LIMIT 501"))
        self.assertEqual(len(calls), 13)
        self.assertFalse(any('FROM "ActivityGPS"' in query for query, _ in calls))
        # An expired budget skips the overview entirely rather than starting a fresh one.
        with patch.object(b, "monotonic", side_effect=[100] + [110] * 30), patch.object(
                b, "request", return_value=payload(charts=True)) as request:
            result, _ = b.fetch(self.config, NOW, True)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(result["activitiesError"], "timeout")

    def test_activities_demo_and_doctor_no_requests(self):
        with patch.object(b, "request", side_effect=AssertionError):
            demo = b.demo(NOW, True)
            self.assertEqual(demo["activities"]["endDate"], "2026-09-05")
            self.assertEqual(len(demo["activities"]["items"]), 4)
            self.assertEqual(demo["activities"]["items"][0]["id"], demo["latestActivity"]["id"])
            self.assertEqual(demo["activities"]["items"][0]["time"], demo["latestActivity"]["time"])
            self.assertIsNone(b.demo(NOW, False)["activities"])
        result = b.run("doctor", self.config, NOW)
        self.assertIsNone(result["activities"])
        self.assertEqual(self.activities_requests, [])

    def test_activities_failure_isolation_and_single_latest_gps_lookup(self):
        for overview in (activities_payload({"ActivityID": "456"}), {"error": "private-error"},
                         b.Failure("network_error")):
            calls = []
            def respond(config, query, timeout):
                calls.append(query)
                if query.startswith('SELECT "BodyBatteryLevel"'):
                    return payload(charts=True)
                if query.endswith("LIMIT 501"):
                    if isinstance(overview, Exception):
                        raise overview
                    return overview
                if query.startswith('SELECT "activityType"'):
                    return activity_payload()
                if 'FROM "ActivityGPS"' in query:
                    self.assertIn('"ActivityID" = \'123\'', query)
                    return supplemental_payload("ActivityGPS", ("position_lat",), [[b.iso(NOW), 1]],
                        {**TAGS, "ActivityID": "123", "ActivitySelector": "gps-only"})
                return {"results": [{"statement_id": n} for n in range(query.count(";") + 1)]}
            with patch.object(b, "request", side_effect=respond):
                result, _ = b.fetch(self.config, NOW, True)
            self.assertTrue(calls[-2].endswith("LIMIT 501"))
            self.assertIn('FROM "ActivityGPS"', calls[-1])
            self.assertEqual(sum('FROM "ActivityGPS"' in query for query in calls), 1)
            self.assertEqual(result["latestActivity"]["gpsSelector"], "gps-only")
            self.assertEqual((result["status"], result["error"]), ("ok", None))
            self.assertIsNone(result["activityError"])
            self.assertNotIn("private-error", json.dumps(result))
            if result["activities"] is None:
                self.assertIn(result["activitiesError"], ("query_error", "network_error"))

    def test_activity_gps_selector_differs_from_summary(self):
        tags = {**TAGS, "User_ID": "private-user", "Account": "private-account"}
        type(self).response = payload(tags=tags)
        type(self).activity_response = activity_payload(tags, ActivitySelector="summary-start")
        type(self).gps_response = supplemental_payload("ActivityGPS", ("position_lat",),
            [[b.iso(NOW - timedelta(minutes=59)), 1]],
            {**tags, "ActivityID": "123", "ActivitySelector": "first-fit-record"})
        result = b.run("fetch", self.config, NOW)
        self.assertEqual(result["latestActivity"]["selector"], "summary-start")
        self.assertEqual(result["latestActivity"].get("gpsSelector"), "first-fit-record")
        self.assertNotIn("ActivityID", result["latestActivity"])
        self.assertEqual(len(self.gps_requests), 1)
        query = parse_qs(urlsplit(self.gps_requests[0][1]).query)["q"][0]
        for key, value in {**tags, "ActivityID": "123"}.items():
            self.assertIn('"' + key + '" = \'' + value + "'", query)
        self.assertNotIn("summary-start", query)
        self.assertIn("GROUP BY * ORDER BY time ASC LIMIT 1 SLIMIT 2", query)
        self.assertEqual(b.run("cache", self.config, NOW)["latestActivity"], result["latestActivity"])
        self.assertNotIn("private-", json.dumps(result))

    def test_activity_selector_reconciled_tags_and_cache(self):
        for selector in ("synthetic", "  Morning run & walk / #123?x=1  ", "caf\u00e9", "x" * 256,
                         "x" * 255 + "\U0001f41f"):
            for shape in ("projected", "metadata", "both", "null-column"):
                with self.subTest(selector=selector, shape=shape):
                    type(self).activity_response = activity_payload(ActivitySelector=selector)
                    entry = self.activity_response["results"][0]["series"][0]
                    if shape != "projected":
                        entry["tags"] = {**TAGS, "ActivityID": "123", "ActivitySelector": selector}
                    if shape == "metadata":
                        entry["columns"] = ["time", "activityType"]
                        entry["values"] = [[b.iso(NOW - timedelta(hours=1)), "running"]]
                    elif shape == "null-column":
                        entry["values"][0][entry["columns"].index("ActivitySelector")] = None
                    result = b.run("fetch", self.config, NOW)
                    self.assertEqual(result["latestActivity"]["selector"], selector)
                    self.assertEqual(result["latestActivity"]["time"], b.iso(NOW - timedelta(hours=1)))
                    self.assertNotIn("ActivityID", result["latestActivity"])
                    self.assertNotIn("ActivitySelector", result["latestActivity"])
                    self.assertEqual(b.run("cache", self.config, NOW)["latestActivity"], result["latestActivity"])

    def test_activity_gps_unavailable_does_not_drop_summary_or_retain_selector(self):
        type(self).activity_response = activity_payload()
        good = supplemental_payload("ActivityGPS", ("position_lat",), [[b.iso(NOW), 1]],
                                    {**TAGS, "ActivityID": "123", "ActivitySelector": "gps-only"})
        invalid = [{"results": [{"statement_id": 0}]}, {"error": "private-error"}, [],
                   {"results": [{"statement_id": 0, "error": "private-error"}]}]
        for mutation in ("source", "id", "selector", "missing-selector", "many", "partial", "row", "time"):
            extra = copy.deepcopy(good)
            entry = extra["results"][0]["series"][0]
            if mutation == "source":
                entry["tags"]["User_ID"] = "private-other"
            elif mutation == "id":
                entry["tags"]["ActivityID"] = "456"
            elif mutation == "selector":
                entry["tags"]["ActivitySelector"] = "bad\n"
            elif mutation == "missing-selector":
                entry["tags"].pop("ActivitySelector")
            elif mutation == "many":
                extra["results"][0]["series"] *= 2
            elif mutation == "partial":
                entry["partial"] = True
            elif mutation == "row":
                entry["values"] *= 2
            else:
                entry["values"][0][0] = b.iso(NOW + timedelta(seconds=1))
            invalid.append(extra)
        for extra in invalid:
            with self.subTest(extra=extra):
                type(self).gps_response = good
                self.assertEqual(b.run("fetch", self.config, NOW)["latestActivity"]["gpsSelector"], "gps-only")
                type(self).gps_response = extra
                result = b.run("fetch", self.config, NOW)
                self.assertEqual(result["latestActivity"]["selector"], "synthetic")
                self.assertNotIn("gpsSelector", result["latestActivity"])
                self.assertIsNone(result["activityError"])
                self.assertEqual(result["activityFetchedAt"], b.iso(NOW))
                self.assertNotIn("private-", json.dumps(result))
                self.assertNotIn("gpsSelector", b.run("cache", self.config, NOW)["latestActivity"])

    def test_activity_gps_cache_validation_and_old_cache(self):
        type(self).activity_response = activity_payload()
        type(self).gps_response = supplemental_payload("ActivityGPS", ("position_lat",), [[b.iso(NOW), 1]],
            {**TAGS, "ActivityID": "123", "ActivitySelector": "gps-only"})
        initial = b.run("fetch", self.config, NOW)
        path, key = b.cache_location(self.config)
        original = json.loads(path.read_text())
        type(self).http_status = 401
        self.assertEqual(b.run("fetch", self.config, NOW)["latestActivity"], initial["latestActivity"])
        for value in (None, 123, True, {}, "", " ", "x" * 257, "gps\n", "gps\ud800"):
            envelope = copy.deepcopy(original)
            envelope["data"]["latestActivity"]["gpsSelector"] = value
            path.write_text(json.dumps(envelope))
            self.assertIsNone(b.read_cache(path, key, self.config, NOW))
        original["data"]["latestActivity"].pop("gpsSelector")
        path.write_text(json.dumps(original))
        self.assertEqual(b.run("cache", self.config, NOW)["latestActivity"], original["data"]["latestActivity"])

    def test_activity_gps_id_metadata_deadline_and_failure_isolation(self):
        type(self).activity_response = activity_payload(ActivityID=None)
        b.run("fetch", self.config, NOW)
        self.assertEqual(self.gps_requests, [])
        self.activity_response["results"][0]["series"][0]["tags"] = {"ActivityID": "123"}
        b.run("fetch", self.config, NOW)
        self.assertEqual(len(self.gps_requests), 1)
        for activity_id in (None, "", " ", "x" * 257, "bad\n"):
            with patch.object(b, "request", side_effect=AssertionError):
                self.assertIsNone(b.gps_selector(self.config, TAGS, activity_id, NOW, NOW, 100))
        with patch.object(b, "monotonic", return_value=100), patch.object(b, "request") as request:
            self.assertIsNone(b.gps_selector(self.config, TAGS, "123", NOW, NOW, 100))
            request.assert_not_called()
        for failure in (b.Failure("timeout"), b.Failure("network_error"), b.Failure("auth_error")):
            with patch.object(b, "monotonic", return_value=100), patch.object(b, "request", side_effect=failure) as request:
                self.assertIsNone(b.gps_selector(self.config, TAGS, "123'\\", NOW, NOW, 102))
                self.assertEqual(request.call_args.kwargs["timeout"], 2)
                self.assertIn('"ActivityID" = \'123\\\'\\\\\'', request.call_args.args[1])

    def test_activity_gps_does_not_cross_activities_or_sources(self):
        type(self).activity_response = activity_payload()
        type(self).gps_response = supplemental_payload("ActivityGPS", ("position_lat",), [[b.iso(NOW), 1]],
            {**TAGS, "ActivityID": "123", "ActivitySelector": "gps-only"})
        original = b.run("fetch", self.config, NOW)
        self.assertIn("gpsSelector", original["latestActivity"])
        # A successful new summary must never borrow the previous activity's GPS selector.
        type(self).activity_response = activity_payload(ActivityID="456", ActivitySelector="new-summary")
        result = b.run("fetch", self.config, NOW)
        self.assertEqual(result["latestActivity"]["selector"], "new-summary")
        self.assertNotIn("gpsSelector", result["latestActivity"])
        # Nor may a matching activity ID bypass full source equality.
        tags = {**TAGS, "User_ID": "other"}
        type(self).response = payload(tags=tags)
        type(self).activity_response = activity_payload(tags)
        result = b.run("fetch", self.config, NOW)
        self.assertIsNotNone(result["latestActivity"])
        self.assertNotIn("gpsSelector", result["latestActivity"])
        count = len(self.gps_requests)
        b.run("doctor", self.config, NOW)
        b.demo(NOW, True)
        self.assertEqual(len(self.gps_requests), count)

    def test_activity_selector_absent_and_old_v1_cache(self):
        for projected_null in (False, True):
            type(self).activity_response = activity_payload(ActivitySelector=None)
            entry = self.activity_response["results"][0]["series"][0]
            if not projected_null:
                index = entry["columns"].index("ActivitySelector")
                entry["columns"].pop(index)
                entry["values"][0].pop(index)
            result, _ = b.fetch(self.config, NOW)
            self.assertIsNone(result["activityError"])
            self.assertNotIn("selector", result["latestActivity"])
        type(self).activity_response = activity_payload()
        b.run("fetch", self.config, NOW)
        path, key = b.cache_location(self.config)
        envelope = json.loads(path.read_text())
        envelope["data"]["latestActivity"].pop("selector")
        path.write_text(json.dumps(envelope))
        cached = b.read_cache(path, key, self.config, NOW)["data"]
        self.assertEqual(cached["schemaVersion"], 1)
        self.assertEqual(cached["latestActivity"], envelope["data"]["latestActivity"])

    def test_activity_selector_invalid_live_and_cache(self):
        type(self).activity_response = activity_payload()
        b.run("fetch", self.config, NOW)
        path, key = b.cache_location(self.config)
        original = json.loads(path.read_text())
        invalid = ["", "   ", "x" * 257, "x" * 256 + "\U0001f41f", 123, True, {}, [],
                   "run\u00a0", "run\u200b", "run\u202e", "run\ud800", "run\ue000", "run\u2028"]
        invalid.extend("run" + chr(code) for code in (*range(32), *range(127, 160)))
        for value in invalid:
            for metadata in (False, True):
                with self.subTest(value=value, metadata=metadata):
                    extra = activity_payload(ActivitySelector=value)
                    if metadata:
                        extra["results"][0]["series"][0] = {
                            "name": "ActivitySummary", "tags": {**TAGS, "ActivitySelector": value},
                            "columns": ["time", "activityType"], "values": [[b.iso(NOW), "running"]]}
                    with patch.object(b, "request", side_effect=[payload(), extra]
                                      + [{"results": [{"statement_id": 0}]}] * 4):
                        result, _ = b.fetch(self.config, NOW)
                    self.assertIsNone(result["latestActivity"])
                    self.assertEqual(result["activityError"], "invalid_response")
                    self.assertEqual((result["status"], result["error"]), ("ok", None))
        for value in [None, *invalid]:
            with self.subTest(cached=value):
                envelope = copy.deepcopy(original)
                envelope["data"]["latestActivity"]["selector"] = value
                path.write_text(json.dumps(envelope))
                self.assertIsNone(b.read_cache(path, key, self.config, NOW))

    def test_activity_identifiers_conflicting_tag_representations(self):
        for key in ("ActivityID", "ActivitySelector"):
            type(self).activity_response = activity_payload()
            self.activity_response["results"][0]["series"][0]["tags"] = {key: "conflicting"}
            result, _ = b.fetch(self.config, NOW)
            self.assertIsNone(result["latestActivity"])
            self.assertEqual(result["activityError"], "invalid_response")

    def test_activity_nullable_numeric_fields_and_bounded_type(self):
        for value in (None, -1, True, "123", {}, float("inf"), float("nan")):
            with self.subTest(value=value), patch.object(b, "request", side_effect=[
                    payload(), activity_payload(elapsedDuration=value, distance=value,
                                                calories=value, bmrCalories=value)]
                    + [{"results": [{"statement_id": 0}]}] * 5):
                result, _ = b.fetch(self.config, NOW)
                self.assertEqual(result["latestActivity"]["type"], "running")
                self.assertTrue(all(result["latestActivity"][key] is None for key in
                                    ("durationSeconds", "distanceMeters", "calories", "bmrCalories")))
                self.assertIsNone(result["error"])
        for kind in ("x" * 80, "trail_running"):
            type(self).activity_response = activity_payload(activityType=kind, elapsedDuration=0,
                                                            distance=0, calories=0, bmrCalories=0)
            result, _ = b.fetch(self.config, NOW)
            self.assertEqual(result["latestActivity"]["type"], kind)
            self.assertEqual(result["latestActivity"]["durationSeconds"], 0)
        for kind in (None, "", "  ", "No Activity", "x" * 81, "run\n", "run\x7f", "run\u202e", 5):
            with self.subTest(kind=kind):
                type(self).activity_response = activity_payload(activityType=kind)
                result, _ = b.fetch(self.config, NOW)
                self.assertIsNone(result["latestActivity"])
                self.assertEqual(result["activityError"], "invalid_response")
                self.assertEqual((result["status"], result["error"]), ("ok", None))

    def test_activity_requires_exact_full_source(self):
        for tags in ({}, {**TAGS, "Device": "Other"}, {**TAGS, "Database_Name": "Other"},
                     {**TAGS, "User_ID": "other"}, {**TAGS, "Account": "other"}):
            with self.subTest(tags=tags):
                type(self).activity_response = activity_payload(tags)
                result, _ = b.fetch(self.config, NOW)
                self.assertIsNone(result["latestActivity"])
                self.assertEqual(result["activityError"], "ambiguous_source")
                self.assertEqual(result["status"], "ok")
        type(self).response = payload(tags={**TAGS, "User_ID": "selected"})
        type(self).activity_response = activity_payload()
        self.assertEqual(b.fetch(self.config, NOW)[0]["activityError"], "ambiguous_source")
        # A null tag column means this row has no such optional tag, not an account wildcard.
        type(self).response = payload()
        type(self).activity_response = activity_payload(User_ID=None)
        self.assertIsNotNone(b.fetch(self.config, NOW)[0]["latestActivity"])
        entry = self.activity_response["results"][0]["series"][0]
        entry["tags"] = {"Device": "Other"}
        self.assertEqual(b.fetch(self.config, NOW)[0]["activityError"], "invalid_response")

    def test_activity_missing_fields_and_grouped_tag_shape(self):
        type(self).activity_response = activity_payload()
        entry = self.activity_response["results"][0]["series"][0]
        entry["tags"] = {**TAGS, "ActivityID": "123", "ActivitySelector": "synthetic"}
        entry["columns"] = ["time", "activityType"]
        entry["values"] = [[b.iso(NOW), "walking"]]
        result, _ = b.fetch(self.config, NOW)
        self.assertEqual(result["latestActivity"], {"id": "123", "time": b.iso(NOW), "type": "walking",
                         "durationSeconds": None, "distanceMeters": None, "calories": None, "bmrCalories": None,
                         "selector": "synthetic",
                         **{key: None for key in b.ACTIVITY_DETAILS}})
        entry["columns"] = ["time", "calories"]
        entry["values"] = [[b.iso(NOW), 200]]
        result, _ = b.fetch(self.config, NOW)
        self.assertIsNone(result["latestActivity"])
        self.assertEqual(result["activityError"], "invalid_response")

    def test_unknown_source_skips_extras_even_with_config_filters(self):
        for response in (payload(charts=True, tags={}),
                         {"results": [{"statement_id": n} for n in range(7)]}):
            type(self).response = response
            result, _ = b.fetch(self.config, NOW, True)
            self.assertEqual(result["activityError"], "source_unavailable")
            self.assertEqual(result["historyError"], "source_unavailable")
        self.config["tags"] = TAGS
        result, _ = b.fetch(self.config, NOW, True)
        self.assertIsNone(result["latestActivity"])
        self.assertEqual(self.optional_requests, [])
        result = b.run("fetch", self.config, NOW, True)
        cached = b.run("cache", self.config, NOW, True)
        self.assertEqual(cached["activityError"], result["activityError"])
        self.assertEqual(cached["historyError"], result["historyError"])
        # Tagged chart records alone also do not establish live health metrics.
        type(self).response = payload(charts=True)
        for item in self.response["results"][:4]:
            item.pop("series")
        self.assertEqual(b.fetch(self.config, NOW, True)[0]["activityError"], "source_unavailable")
        self.assertEqual(self.optional_requests, [])

    def test_history_completed_days_latest_not_sum_or_average(self):
        type(self).response = payload(charts=True)
        type(self).history_response = history_payload(
            daily=[["2026-09-04T08:00:00Z", 60, 100], ["2026-09-04T21:00:00Z", 90, 800],
                   ["2026-09-03T12:00:00Z", 0, 0]],
            sleep=[["2026-09-04T08:00:00Z", 80, 40], ["2026-09-04T10:00:00Z", None, 50],
                   ["2026-09-04T12:00:00Z", 0, None], ["2026-09-03T12:00:00Z", None, 0]])
        result, _ = b.fetch(self.config, NOW, True)
        self.assertIsNone(result["historyError"])
        self.assertEqual(result["historyFetchedAt"], b.iso(NOW))
        for key, expected in (("bodyBattery", [0, 90]), ("steps", [0, 800]),
                              ("sleep", [None, 0]), ("hrv", [0, 50])):
            self.assertEqual([p["value"] for p in result["history"][key]], [None] * 5 + expected)
            self.assertEqual([p["date"] for p in result["history"][key]],
                             [(NOW.date() - timedelta(days=n)).isoformat() for n in range(7, 0, -1)])
        query = parse_qs(urlsplit(self.optional_requests[-1][1]).query)["q"][0]
        self.assertIn('"bodyBatteryHighestValue"', query)
        self.assertIn("time < '2026-09-04T23:00:00Z'", query)
        self.assertIn("LIMIT 1000 SLIMIT 2", query)
        self.assertNotIn("SUM(", query)
        self.assertNotIn("MEAN(", query)
        self.assertNotIn("BodyBatteryIntraday", query)

    def test_history_sparse_columns_and_last_daily_null(self):
        type(self).response = payload(charts=True)
        type(self).history_response = history_payload(
            daily=[["2026-09-04T08:00:00Z", 90, 800], ["2026-09-04T21:00:00Z", None, None]])
        entry = self.history_response["results"][1]["series"][0]
        entry["columns"] = ["time", "avgOvernightHrv"]
        entry["values"] = [["2026-09-04T12:00:00Z", None], ["2026-09-04T08:00:00Z", 0]]
        result, _ = b.fetch(self.config, NOW, True)
        for key in ("steps", "bodyBattery", "sleep"):
            self.assertIsNone(result["history"][key][-1]["value"])
        self.assertEqual(result["history"]["hrv"][-1]["value"], 0)

    def test_history_dst_calendar_window_and_no_today(self):
        for now, start, end, hours in (("2026-03-30T12:00:00Z", "2026-03-23T00:00:00Z", "2026-03-29T23:00:00Z", 167),
                                       ("2026-10-26T12:00:00Z", "2026-10-18T23:00:00Z", "2026-10-26T00:00:00Z", 169)):
            with self.subTest(now=now):
                instant = b.timestamp(now)
                type(self).response = payload(instant, True)
                type(self).history_response = history_payload(daily=[
                    [start, 80, 1], [b.iso(b.timestamp(end) - timedelta(seconds=1)), 90, 2]])
                result, _ = b.fetch(self.config, instant, True)
                points = result["history"]["steps"]
                self.assertEqual([p["value"] for p in points], [1] + [None] * 5 + [2])
                self.assertEqual(b.timestamp(end) - b.timestamp(start), timedelta(hours=hours))
                query = parse_qs(urlsplit(self.optional_requests[-1][1]).query)["q"][0]
                self.assertIn("time >= '" + start + "'", query)
                self.assertIn("time < '" + end + "'", query)
                self.history_response["results"][0]["series"][0]["values"].append([end, 100, 999])
                result, _ = b.fetch(self.config, instant, True)
                self.assertEqual(result["historyError"], "invalid_response")
                self.assertTrue(all(not points for points in result["history"].values()))

    def test_optional_failure_isolation_and_sanitized_errors(self):
        for kind in ("activity", "history"):
            for failure in ({"error": "private body"}, {"results": [{"statement_id": 0, "error": "private body"}]},
                            [], {"results": None}, {"results": [{"statement_id": False}]},
                            b.Failure("timeout"), b.Failure("auth_error")):
                with self.subTest(kind=kind, failure=failure):
                    good_history = history_payload(daily=[["2026-09-04T12:00:00Z", 90, 800]])
                    with patch.object(b, "request", side_effect=[payload(charts=True),
                            failure if kind == "activity" else activity_payload(),
                            failure if kind == "history" else good_history]
                            + [{"results": [{"statement_id": 0}]}] * 11):
                        result, _ = b.fetch(self.config, NOW, True)
                    self.assertEqual((result["status"], result["error"]), ("ok", None))
                    self.assertIn(result[kind + "Error"], b.OPTIONAL_ERRORS)
                    other = "history" if kind == "activity" else "activity"
                    self.assertIsNone(result[other + "Error"])
                    self.assertEqual(result[other + "FetchedAt"], b.iso(NOW))
                    self.assertNotIn("private", json.dumps(result))

    def test_optional_malformed_rows_ranges_and_truncation(self):
        for kind in ("activity", "history"):
            for mutation, error in (("partial", "truncated_response"), ("many", "truncated_response"),
                                    ("series", "ambiguous_source"), ("columns", "invalid_response"),
                                    ("row", "invalid_response"), ("future", "invalid_response"),
                                    ("old", "invalid_response"), ("name", "invalid_response")):
                with self.subTest(kind=kind, mutation=mutation):
                    extra = (activity_payload() if kind == "activity" else
                             history_payload(daily=[["2026-09-04T12:00:00Z", 90, 800]]))
                    entry = extra["results"][0]["series"][0]
                    if mutation == "partial":
                        entry["partial"] = True
                    elif mutation == "many":
                        entry["values"] *= 2 if kind == "activity" else 1000
                    elif mutation == "series":
                        extra["results"][0]["series"] *= 2
                    elif mutation == "columns":
                        entry["columns"].append("time")
                    elif mutation == "row":
                        entry["values"][0].pop()
                    elif mutation in ("future", "old"):
                        entry["values"][0][0] = b.iso(NOW + timedelta(days=1 if mutation == "future" else -366))
                    else:
                        entry["name"] = "Wrong"
                    with patch.object(b, "request", side_effect=[payload(charts=True),
                            extra if kind == "activity" else activity_payload(),
                            extra if kind == "history" else history_payload()]
                            + [{"results": [{"statement_id": 0}]}] * 11):
                        result, _ = b.fetch(self.config, NOW, True)
                    self.assertEqual(result[kind + "Error"], error)
                    self.assertEqual(result["status"], "ok")

    def test_history_source_and_value_validation(self):
        type(self).response = payload(charts=True)
        for tags in ({}, {**TAGS, "User_ID": "other"}, {**TAGS, "Device": "Other"}):
            type(self).history_response = history_payload(tags=tags)
            self.assertEqual(b.fetch(self.config, NOW, True)[0]["historyError"], "ambiguous_source")
        for daily in ([101, 800], [-1, 800], [90, -1], [True, 800]):
            type(self).history_response = history_payload(daily=[["2026-09-04T12:00:00Z", *daily]])
            self.assertEqual(b.fetch(self.config, NOW, True)[0]["historyError"], "invalid_response")

    def test_optional_deadlines_share_base_budget_and_do_not_request_after_expiry(self):
        for ticks, calls, timeout in (([100, 101, 102, 103, 104, 108, 110], 2, 2),
                                       ([100, 101, 102, 103, 104, 110, 111], 1, None)):
            with self.subTest(ticks=ticks), patch.object(b, "monotonic", side_effect=ticks + [111] * 4), patch.object(
                    b, "request", side_effect=[payload(), b.Failure("timeout")]) as request:
                result, _ = b.fetch(self.config, NOW)
                self.assertEqual(request.call_count, calls)
                if timeout is not None:
                    self.assertEqual(request.call_args.kwargs["timeout"], timeout)
                self.assertEqual(result["activityError"], "timeout")
        # Seven base statement checks, then activity consumes the remaining budget.
        with patch.object(b, "monotonic", side_effect=[100] + [101] * 7 + [109, 110] + [110] * 10), patch.object(
                b, "request", side_effect=[payload(charts=True), b.Failure("timeout")]) as request:
            result, _ = b.fetch(self.config, NOW, True)
            self.assertEqual(request.call_count, 2)
            self.assertEqual(request.call_args.kwargs["timeout"], 1)
            self.assertEqual(result["historyError"], "timeout")

    def test_optional_cache_preservation_timestamps_and_runtime_stripping(self):
        type(self).response = payload(charts=True)
        type(self).activity_response = activity_payload()
        type(self).history_response = history_payload(daily=[["2026-09-04T12:00:00Z", 90, 800]])
        initial = b.run("fetch", self.config, NOW, True)
        later = NOW + timedelta(hours=1)
        type(self).response = payload(later, True)
        type(self).activity_response = {"error": "private"}
        self.assertEqual(initial["latestActivity"]["selector"], "synthetic")
        type(self).history_response = {"error": "private"}
        failed = b.run("fetch", self.config, later, True)
        for field in ("latestActivity", "history", "activityFetchedAt", "historyFetchedAt"):
            self.assertEqual(failed[field], initial[field])
        for kind in ("activity", "history"):
            self.assertEqual(failed[kind + "Error"], "query_error")
        self.assertEqual((failed["status"], failed["error"]), ("ok", None))
        type(self).response = payload(later)
        summary = b.run("fetch", self.config, later)
        self.assertEqual(summary["history"], {key: [] for key in b.HISTORY_FIELDS})
        self.assertIsNone(summary["historyFetchedAt"])
        self.assertEqual(summary["latestActivity"], initial["latestActivity"])
        cached = b.run("cache", self.config, later, True)
        self.assertEqual(cached["history"], initial["history"])
        self.assertEqual(cached["historyFetchedAt"], b.iso(NOW))
        self.assertEqual(cached["historyError"], "query_error")
        self.assertEqual(cached["activityFetchedAt"], b.iso(NOW))
        type(self).http_status = 401
        offline = b.run("fetch", self.config, later, True)
        self.assertEqual((offline["status"], offline["error"]), ("cached", "auth_error"))
        self.assertEqual(offline["latestActivity"], initial["latestActivity"])
        self.assertEqual(offline["historyFetchedAt"], b.iso(NOW))

    def test_optional_successful_empty_clears_cache(self):
        type(self).response = payload(charts=True)
        type(self).activity_response = activity_payload()
        type(self).history_response = history_payload(daily=[["2026-09-04T12:00:00Z", 90, 800]])
        b.run("fetch", self.config, NOW, True)
        type(self).activity_response = {"results": [{"statement_id": 0}]}
        type(self).history_response = history_payload()
        result = b.run("fetch", self.config, NOW, True)
        self.assertIsNone(result["latestActivity"])
        self.assertIsNone(result["activityError"])
        self.assertTrue(all(p["value"] is None for points in result["history"].values() for p in points))
        self.assertTrue(all(len(points) == 7 for points in result["history"].values()))

    def test_optional_cache_never_merges_changed_or_unestablished_source(self):
        for tags in ({**TAGS, "Device": "Other"}, {**TAGS, "User_ID": "Other"}, {}, None):
            with self.subTest(tags=tags):
                type(self).response = payload(charts=True)
                type(self).activity_response = activity_payload()
                type(self).history_response = history_payload(daily=[["2026-09-04T12:00:00Z", 90, 800]])
                b.run("fetch", self.config, NOW, True)
                type(self).response = (payload(tags=tags) if tags is not None else
                                       {"results": [{"statement_id": n} for n in range(4)]})
                type(self).activity_response = {"error": "private"}
                result = b.run("fetch", self.config, NOW)
                self.assertIsNone(result["latestActivity"])
                cached = b.run("cache", self.config, NOW, True)
                self.assertEqual(cached["history"], {key: [] for key in b.HISTORY_FIELDS})
                self.assertIsNone(cached["activityFetchedAt"])

    def test_optional_cache_reconstruction_rejects_untrusted_data(self):
        type(self).response = payload(charts=True)
        type(self).activity_response = activity_payload()
        type(self).history_response = history_payload(daily=[["2026-09-04T12:00:00Z", 90, 800]])
        b.run("fetch", self.config, NOW, True)
        path, identity = b.cache_location(self.config)
        original = json.loads(path.read_text())
        original["data"]["private"] = "private"
        original["data"]["latestActivity"]["activityName"] = "private"
        original["data"]["history"]["steps"][0]["account"] = "private"
        path.write_text(json.dumps(original))
        clean = b.read_cache(path, identity, self.config, NOW)["data"]
        self.assertNotIn("private", json.dumps(clean))
        envelope = copy.deepcopy(original)
        envelope["data"]["latestActivity"]["durationSeconds"] = "private"
        path.write_text(json.dumps(envelope))
        clean = b.read_cache(path, identity, self.config, NOW)["data"]
        self.assertIsNone(clean["latestActivity"]["durationSeconds"])
        for key, value in (("activityError", "private"), ("historyError", []),
                           ("activityFetchedAt", b.iso(NOW + timedelta(seconds=1))),
                           ("historyFetchedAt", None), ("latestActivity", {"type": "running"}),
                           ("history", {"steps": []})):
            with self.subTest(key=key):
                envelope = copy.deepcopy(original)
                envelope["data"][key] = value
                path.write_text(json.dumps(envelope))
                self.assertIsNone(b.read_cache(path, identity, self.config, NOW))
        for key, value in (("value", 101), ("date", NOW.date().isoformat())):
            envelope = copy.deepcopy(original)
            envelope["data"]["history"]["bodyBattery"][-1][key] = value
            path.write_text(json.dumps(envelope))
            self.assertIsNone(b.read_cache(path, identity, self.config, NOW))
        for source in (None, "{}", "not json", '{"Device":42}'):
            envelope = copy.deepcopy(original)
            envelope["source"] = source
            path.write_text(json.dumps(envelope))
            clean = b.read_cache(path, identity, self.config, NOW)["data"]
            self.assertIsNone(clean["latestActivity"])
            self.assertTrue(all(not points for points in clean["history"].values()))

    def test_demo_optional_data_and_doctor_skips_extras(self):
        for charts in (False, True):
            result = b.demo(NOW, charts)
            self.assertEqual(result["activityFetchedAt"], b.iso(NOW))
            for key in ("durationSeconds", "distanceMeters", "calories", "bmrCalories"):
                self.assertGreater(result["latestActivity"][key], 0)
            self.assertTrue(all(len(points) == (7 if charts else 0) for points in result["history"].values()))
            self.assertEqual(result["historyFetchedAt"], b.iso(NOW) if charts else None)
        result = b.run("doctor", self.config, NOW)
        self.assertEqual(self.optional_requests, [])
        self.assertIsNone(result["latestActivity"])
        self.assertIsNone(result["activityFetchedAt"])
        self.assertTrue(all(not points for points in result["history"].values()))


    def wellness_fixture(self, now=NOW, readiness_error=False):
        def response(query):
            if query.startswith('SELECT MEAN('):
                return stress_history_payload(query)
            if readiness_error and 'FROM "TrainingReadiness"' in query:
                return {"results": [{"statement_id": 0, "error": "private missing measurement"}]}
            if 'time < ' in query:
                for name, fields in (("SleepSummary", ("sleepTimeSeconds",)),
                                      ("DailyStats", ("restingHeartRate",)),
                                      ("TrainingReadiness", ("score",))):
                    if 'FROM "' + name + '"' in query:
                        return supplemental_payload(name, fields, [
                            [b.iso(now - timedelta(days=1)), *([40] * len(fields))]])
            for key, (name, field, _) in b.WELLNESS.items():
                if query.startswith('SELECT "' + field + '"'):
                    if readiness_error and key == "trainingReadiness":
                        return {"results": [{"statement_id": 0, "error": "private missing measurement"}]}
                    when = now - timedelta(hours=8) if key == "sleepDuration" else now
                    return supplemental_payload(name, (field,), [[b.iso(when), {
                        "sleepDuration": 28800, "restingHeartRate": 52,
                        "trainingReadiness": 78, "stress": 0}[key]]])
            raise AssertionError(query)
        type(self).supplemental_response = staticmethod(response)

    def test_wellness_contract_queries_and_missing_readiness_isolation(self):
        for missing in (False, True):
            self.wellness_fixture(readiness_error=missing)
            result, _ = b.fetch(self.config, NOW)
            self.assertEqual((result["status"], result["error"]), ("ok", None))
            self.assertEqual(result["wellnessFetchedAt"], b.iso(NOW))
            self.assertEqual(result["wellnessError"], "query_error" if missing else None)
            self.assertEqual(set(result["metrics"]), set(b.METRICS))
            for key, (name, field, unit) in b.WELLNESS.items():
                metric = result["wellness"][key]
                self.assertEqual(set(metric), {"value", "time", "date", "state", "unit", "expiresAt"})
                self.assertEqual(metric["unit"], unit)
                self.assertEqual(metric["state"], "missing" if missing and key == "trainingReadiness" else "fresh")
                query = next(parse_qs(urlsplit(path).query)["q"][0]
                             for _, path, _ in self.supplemental_requests
                             if parse_qs(urlsplit(path).query)["q"][0].startswith('SELECT "' + field + '"'))
                self.assertIn('FROM "' + name + '"', query)
                self.assertIn('"' + field + '" >= 0', query)
                if unit == "score":
                    self.assertIn('"' + field + '" <= 100', query)
                self.assertIn("time >= '2026-08-06T10:00:00Z'", query)
                self.assertIn("GROUP BY * ORDER BY time DESC LIMIT 1 SLIMIT 2", query)
                for tag, value in TAGS.items():
                    self.assertIn('"' + tag + '" = \'' + value + "'", query)
            self.assertEqual(result["wellness"]["stress"]["value"], 0)
            self.assertNotIn("private", json.dumps(result))
        self.assertEqual(len(self.supplemental_requests), 8)  # No batch skips or retries.

    def test_new_optional_old_cache_defaults_and_demo_doctor(self):
        defaults = b.empty(NOW, self.config["timezone"])
        fields = ("wellness", "wellnessFetchedAt", "wellnessError", "supplementalHistory",
                  "supplementalHistoryFetchedAt", "supplementalHistoryError", "stressSeries",
                  "stressFetchedAt", "stressError")
        self.wellness_fixture()
        b.run("fetch", self.config, NOW)
        path, identity = b.cache_location(self.config)
        envelope = json.loads(path.read_text())
        for key in fields:
            envelope["data"].pop(key)
        path.write_text(json.dumps(envelope))
        result = b.read_cache(path, identity, self.config, NOW)["data"]
        self.assertEqual({k: result[k] for k in fields}, {k: defaults[k] for k in fields})
        for charts in (True, False):
            result = b.demo(NOW, charts)
            self.assertTrue(all(m["value"] is not None for m in result["wellness"].values()))
            self.assertEqual(len(result["stressSeries"]), 289 if charts else 0)
            self.assertTrue(all(len(p) == (7 if charts else 0) for p in result["supplementalHistory"].values()))
            self.assertTrue(all(result["latestActivity"][key] > 0 for key in b.ACTIVITY_DETAILS))
        before = len(self.supplemental_requests)
        result = b.run("doctor", self.config, NOW)
        self.assertEqual(len(self.supplemental_requests), before)
        self.assertEqual({k: result[k] for k in fields}, {k: defaults[k] for k in fields})

    def test_wellness_freshness_and_dst_midnight(self):
        self.wellness_fixture()
        initial = b.run("fetch", self.config, NOW)
        for elapsed, stress, sleep in ((2, "fresh", "fresh"), (2.001, "stale", "fresh"),
                                       (28, "stale", "fresh"), (28.001, "stale", "stale")):
            cached = b.run("cache", self.config, NOW + timedelta(hours=elapsed))
            self.assertEqual(cached["wellness"]["stress"]["state"], stress)
            self.assertEqual(cached["wellness"]["sleepDuration"]["state"], sleep)
            self.assertEqual(cached["wellnessFetchedAt"], initial["wellnessFetchedAt"])
        for sample, expiry in (("2026-03-29T00:00:00Z", "2026-03-29T23:00:00Z"),
                                ("2026-10-24T23:00:00Z", "2026-10-26T00:00:00Z")):
            now = b.timestamp(sample)
            type(self).response = payload(now)
            self.wellness_fixture(now)
            result, _ = b.fetch(self.config, now)
            for key in ("restingHeartRate", "trainingReadiness"):
                self.assertEqual(result["wellness"][key]["expiresAt"], expiry)
                self.assertEqual(result["wellness"][key]["state"], "fresh")
            b.refresh_states(result, b.timestamp(expiry))
            self.assertEqual(result["sourceDate"], b.timestamp(expiry).astimezone(b.ZoneInfo(self.config["timezone"])).date().isoformat())
            for key in ("restingHeartRate", "trainingReadiness"):
                self.assertEqual(result["wellness"][key]["state"], "stale")

    def test_stress_raw_gaps_zero_order_and_independent_timestamp(self):
        type(self).response = payload(charts=True)
        def response(query):
            if query.startswith('SELECT "stressLevel"') and "LIMIT 2001" in query:
                self.assertNotIn('"stressLevel" >=', query)
                self.assertIn("time >= '2026-09-04T10:00:00Z'", query)
                return supplemental_payload("StressIntraday", ("stressLevel",), [
                    [b.iso(NOW - timedelta(minutes=n)), value]
                    for n, value in enumerate((100, 0, -1, 101, None, True, "20"))])
            return {"results": [{"statement_id": 0}]}
        type(self).supplemental_response = staticmethod(response)
        result = b.run("fetch", self.config, NOW, True)
        self.assertEqual([p["value"] for p in result["stressSeries"]], [None] * 5 + [0, 100])
        self.assertEqual(result["stressSeries"], sorted(result["stressSeries"], key=lambda p: p["time"]))
        self.assertEqual(result["stressFetchedAt"], b.iso(NOW))
        self.assertIsNone(result["stressError"])
        self.assertEqual(b.run("cache", self.config, NOW, True)["stressSeries"], result["stressSeries"])

    def test_supplemental_history_last_valid_per_field_and_dst(self):
        for now, start, end in (("2026-03-30T12:00:00Z", "2026-03-23T00:00:00Z", "2026-03-29T23:00:00Z"),
                                ("2026-10-26T12:00:00Z", "2026-10-18T23:00:00Z", "2026-10-26T00:00:00Z")):
            instant = b.timestamp(now)
            type(self).response = payload(instant, True)
            def response(query):
                if query.startswith('SELECT MEAN('):
                    return stress_history_payload(query, (0, None, None, None, None, None, 40))
                if "time < " not in query:
                    return {"results": [{"statement_id": 0}]}
                self.assertIn("time >= '" + start + "'", query)
                self.assertIn("time < '" + end + "'", query)
                self.assertNotIn("GROUP BY time", query)
                self.assertNotIn("MEAN(", query)
                latest = b.iso(b.timestamp(end) - timedelta(seconds=1))
                earlier = b.iso(b.timestamp(end) - timedelta(hours=1))
                if 'FROM "DailyStats"' in query:
                    return supplemental_payload("DailyStats", ("restingHeartRate",),
                                                [[start, 0], [earlier, 55], [latest, None]])
                if 'FROM "SleepSummary"' in query:
                    return supplemental_payload("SleepSummary", ("sleepTimeSeconds",),
                                                [[earlier, 28800], [latest, None]])
                return supplemental_payload("TrainingReadiness", ("score",),
                                            [[earlier, 0], [latest, -1]])
            type(self).supplemental_response = staticmethod(response)
            result = b.run("fetch", self.config, instant, True)
            self.assertIsNone(result["supplementalHistoryError"])
            for key, value in (("sleepDuration", 28800), ("restingHeartRate", 55),
                               ("trainingReadiness", 0), ("stress", 40)):
                self.assertEqual(len(result["supplementalHistory"][key]), 7)
                self.assertEqual(result["supplementalHistory"][key][-1]["value"], value)
            self.assertEqual(result["supplementalHistory"]["stress"][0]["value"], 0)
            self.assertEqual(b.run("cache", self.config, instant, True)["supplementalHistory"], result["supplementalHistory"])

    def test_new_optional_partial_cache_retention_and_stripping(self):
        type(self).response = payload(charts=True)
        self.wellness_fixture()
        initial = b.run("fetch", self.config, NOW, True)
        later = NOW + timedelta(days=1)
        type(self).response = payload(later, True)
        self.wellness_fixture(later)
        healthy = type(self).supplemental_response
        def response(query):
            if 'FROM "TrainingReadiness"' in query or 'FROM "StressIntraday"' in query:
                return {"error": "private"}
            return healthy(query)
        type(self).supplemental_response = staticmethod(response)
        result = b.run("fetch", self.config, later, True)
        for kind in ("wellness", "supplementalHistory"):
            self.assertEqual(result[kind]["trainingReadiness"], initial[kind]["trainingReadiness"]
                             if kind == "supplementalHistory" else {**initial[kind]["trainingReadiness"], "state": "stale"})
            self.assertNotEqual(result[kind]["sleepDuration"], initial[kind]["sleepDuration"])
            self.assertEqual(result[kind + "FetchedAt"], b.iso(NOW))
            self.assertEqual(result[kind + "Error"], "query_error")
        self.assertEqual(result["stressSeries"], initial["stressSeries"])
        self.assertEqual(result["supplementalHistory"]["stress"], initial["supplementalHistory"]["stress"])
        self.assertEqual(result["stressFetchedAt"], b.iso(NOW))
        cached = b.run("cache", self.config, later, True)
        self.assertEqual(cached["wellness"], result["wellness"])
        self.assertEqual(cached["supplementalHistory"], result["supplementalHistory"])
        type(self).response = payload(later)
        summary = b.run("fetch", self.config, later)
        for kind in ("supplementalHistory", "stress"):
            self.assertIsNone(summary[kind + "FetchedAt"])
            self.assertIsNone(summary[kind + "Error"])
        self.assertEqual(summary["stressSeries"], [])
        self.assertTrue(all(not p for p in summary["supplementalHistory"].values()))
        cached = b.run("cache", self.config, later, True)
        self.assertEqual(cached["supplementalHistory"], result["supplementalHistory"])
        self.assertEqual(cached["stressSeries"], initial["stressSeries"])

    def test_new_optional_source_safety_and_failed_values(self):
        for tags in ({**TAGS, "Device": "Other"}, {**TAGS, "User_ID": "Other"}, {}, None):
            type(self).response = payload(charts=True)
            self.wellness_fixture()
            b.run("fetch", self.config, NOW, True)
            type(self).response = (payload(charts=True, tags=tags) if tags is not None else
                                   {"results": [{"statement_id": n} for n in range(7)]})
            result = b.run("fetch", self.config, NOW, True)
            self.assertTrue(all(m["value"] is None for m in result["wellness"].values()))
            self.assertIsNone(result["wellnessFetchedAt"])
            self.assertIsNone(result["supplementalHistoryFetchedAt"])
            self.assertEqual(result["stressSeries"], [])
        type(self).response = payload()
        for value in (-1, 101, True, "52", None):
            self.wellness_fixture()
            healthy = type(self).supplemental_response
            type(self).supplemental_response = staticmethod(lambda query: (
                supplemental_payload("TrainingReadiness", ("score",), [[b.iso(NOW), value]])
                if 'FROM "TrainingReadiness"' in query else healthy(query)))
            result, _ = b.fetch(self.config, NOW)
            self.assertEqual(result["wellnessError"], "invalid_response")
            self.assertIsNone(result["wellness"]["trainingReadiness"]["value"])
            self.assertEqual(result["wellness"]["stress"]["value"], 0)

    def test_new_optional_cache_reconstructs_units_and_rejects_bad_values_times(self):
        type(self).response = payload(charts=True)
        self.wellness_fixture()
        b.run("fetch", self.config, NOW, True)
        path, identity = b.cache_location(self.config)
        original = json.loads(path.read_text())
        original["data"]["wellness"]["stress"].update(unit="private", expiresAt="private", date="private", secret="private")
        path.write_text(json.dumps(original))
        clean = b.read_cache(path, identity, self.config, NOW)["data"]
        self.assertNotIn("private", json.dumps(clean))
        self.assertEqual(clean["wellness"]["stress"]["unit"], "score")
        for bundle, key, field, bad in (("wellness", "stress", "value", 101),
                                        ("wellness", "stress", "time", b.iso(NOW + timedelta(seconds=1))),
                                        ("wellness", "restingHeartRate", "value", -1),
                                        ("stressSeries", None, "value", -1),
                                        ("stressSeries", None, "time", b.iso(NOW - timedelta(hours=25))),
                                        ("supplementalHistory", "stress", "value", 101),
                                        ("supplementalHistory", "stress", "date", "2026-09-05")):
            envelope = copy.deepcopy(original)
            target = envelope["data"][bundle]
            if key is not None:
                target = target[key]
            if isinstance(target, list):
                target = target[-1]
            target[field] = bad
            path.write_text(json.dumps(envelope))
            self.assertIsNone(b.read_cache(path, identity, self.config, NOW), (bundle, key, field))

    def test_wellness_requests_share_remaining_deadline(self):
        self.wellness_fixture()
        # Core, activity, then one wellness request; all later work is expired.
        with patch.object(b, "monotonic", side_effect=[100] + [101] * 4 + [102, 109] + [110] * 4), patch.object(
                b, "request", side_effect=[payload(), activity_payload(),
                    supplemental_payload("SleepSummary", ("sleepTimeSeconds",), [[b.iso(NOW), 28800]])]) as request:
            result, _ = b.fetch(self.config, NOW)
        self.assertEqual(request.call_count, 3)
        self.assertEqual(request.call_args.kwargs["timeout"], 1)
        self.assertEqual(result["wellness"]["sleepDuration"]["value"], 28800)
        self.assertEqual(result["wellnessError"], "timeout")
        self.assertEqual(result["status"], "ok")

    def test_new_optional_empty_success_clears_and_failed_empty_keeps_timestamp(self):
        type(self).response = payload(charts=True)
        self.wellness_fixture()
        b.run("fetch", self.config, NOW, True)
        type(self).supplemental_response = staticmethod(lambda query: {
            "results": [{"statement_id": n} for n in range(query.count('SELECT MEAN(') or 1)]})
        cleared = b.run("fetch", self.config, NOW, True)
        self.assertTrue(all(m["value"] is None for m in cleared["wellness"].values()))
        self.assertTrue(all(len(p) == 7 and all(v["value"] is None for v in p)
                            for p in cleared["supplementalHistory"].values()))
        self.assertEqual(cleared["stressSeries"], [])
        later = NOW + timedelta(hours=1)
        type(self).response = payload(later, True)
        self.wellness_fixture(later, readiness_error=True)
        failed = b.run("fetch", self.config, later, True)
        self.assertEqual(failed["wellnessFetchedAt"], b.iso(NOW))
        self.assertEqual(failed["wellness"]["sleepDuration"]["value"], 28800)
        self.assertIsNone(failed["wellness"]["trainingReadiness"]["value"])
        self.assertEqual(b.run("cache", self.config, later, True)["wellness"], failed["wellness"])

    def test_new_optional_structural_failures_do_not_discard_other_bundles(self):
        type(self).response = payload(charts=True)
        for target in ("wellness", "supplementalHistory", "stress"):
            for mutation, error in (("source", "ambiguous_source"), ("series", "ambiguous_source"),
                                     ("partial", "truncated_response"), ("cap", "truncated_response"),
                                     ("future", "invalid_response"), ("columns", "invalid_response"),
                                     ("statement", "invalid_response"), ("error", "query_error")):
                with self.subTest(target=target, mutation=mutation):
                    self.wellness_fixture()
                    healthy = type(self).supplemental_response
                    def response(query):
                        kind = ("supplementalHistory" if "time < " in query else
                                "stress" if "LIMIT 2001" in query else "wellness")
                        extra = healthy(query)
                        if kind != target:
                            return extra
                        entry = extra["results"][0]["series"][0]
                        if mutation == "source":
                            entry["tags"] = {**TAGS, "Account": "private"}
                        elif mutation == "series":
                            extra["results"][0]["series"] *= 2
                        elif mutation == "partial":
                            entry["partial"] = True
                        elif mutation == "cap":
                            entry["values"] *= {"wellness": 2, "supplementalHistory": 1000, "stress": 2001}[kind]
                        elif mutation == "future":
                            entry["values"][0][0] = b.iso(NOW + timedelta(seconds=1))
                        elif mutation == "columns":
                            entry["columns"].append("time")
                        elif mutation == "statement":
                            extra["results"][0]["statement_id"] = False
                        else:
                            extra["results"][0]["error"] = "private"
                        return extra
                    type(self).supplemental_response = staticmethod(response)
                    result, _ = b.fetch(self.config, NOW, True)
                    self.assertEqual(result[target + "Error"], error)
                    self.assertIsNone(result[target + "FetchedAt"])
                    self.assertEqual(result["status"], "ok")
                    self.assertNotIn("private", json.dumps(result))
                    for other in {"wellness", "supplementalHistory", "stress"} - {target}:
                        self.assertIsNone(result[other + "Error"])
                        self.assertEqual(result[other + "FetchedAt"], b.iso(NOW))

    def test_stress_history_aggregates_seven_complete_local_days(self):
        for now, hours in ((NOW, 24), (b.timestamp("2026-03-30T12:00:00Z"), 23),
                           (b.timestamp("2026-10-26T12:00:00Z"), 25)):
            with self.subTest(now=now):
                b.cache_location(self.config)[0].unlink(missing_ok=True)
                type(self).response = payload(now, True)
                self.wellness_fixture(now, readiness_error=True)
                type(self).supplemental_requests = []
                result = b.run("fetch", self.config, now, True)
                self.assertEqual([p["value"] for p in result["supplementalHistory"]["stress"]],
                                 [0, None, 25.5, 100, None, 40, 50])
                today = now.astimezone(b.ZoneInfo(self.config["timezone"])).date()
                self.assertEqual([p["date"] for p in result["supplementalHistory"]["stress"]],
                                 [(today - timedelta(days=n)).isoformat() for n in range(7, 0, -1)])
                self.assertEqual(result["supplementalHistoryError"], "query_error")
                self.assertEqual(result["supplementalHistoryFetchedAt"], b.iso(now))
                self.assertEqual(result["wellness"]["stress"]["value"], 0)
                self.assertEqual(result["supplementalHistory"]["sleepDuration"][-1]["value"], 40)
                self.assertTrue(result["stressSeries"])
                queries = [parse_qs(urlsplit(path).query)["q"][0]
                           for _, path, _ in self.supplemental_requests]
                self.assertTrue(all("averageStressLevel" not in q for q in queries))
                batches = [q for q in queries if q.startswith('SELECT MEAN(')]
                self.assertEqual(len(batches), 1)
                statements = batches[0].split(";")
                self.assertEqual(len(statements), 7)
                for index, statement in enumerate(statements):
                    self.assertTrue(statement.startswith(
                        'SELECT MEAN("stressLevel") AS "stressLevel" FROM "StressIntraday" WHERE '))
                    self.assertTrue(statement.endswith(" GROUP BY * SLIMIT 2"))
                    self.assertIn('"stressLevel" >= 0 AND "stressLevel" <= 100', statement)
                    for tag, value in TAGS.items():
                        self.assertIn('"' + tag + '" = \'' + value + "'", statement)
                    start = b.timestamp(statement.split("time >= '")[1].split("'")[0])
                    end = b.timestamp(statement.split("time < '")[1].split("'")[0])
                    self.assertEqual(end - start, timedelta(hours=hours if index == 6 else 24))
                    self.assertEqual(start.astimezone(b.ZoneInfo(self.config["timezone"])).hour, 0)
                    self.assertEqual(end.astimezone(b.ZoneInfo(self.config["timezone"])).hour, 0)
                self.assertEqual(b.run("cache", self.config, now, True)["supplementalHistory"],
                                 result["supplementalHistory"])

    def test_stress_history_invalid_batch_is_atomic_and_retains_cached_stress(self):
        type(self).response = payload(charts=True)
        self.wellness_fixture()
        initial = b.run("fetch", self.config, NOW, True)
        later = NOW + timedelta(days=1)
        type(self).response = payload(later, True)
        for mutation, error in (("source", "ambiguous_source"), ("series", "ambiguous_source"),
                                ("partial", "truncated_response"), ("cap", "truncated_response"),
                                ("time", "invalid_response"), ("columns", "invalid_response"),
                                ("statement", "invalid_response"), ("count", "invalid_response"),
                                ("name", "invalid_response"), ("row", "invalid_response"),
                                ("error", "query_error"),
                                *[(value, "invalid_response") for value in (-1, 101, True, "20")]):
            with self.subTest(mutation=mutation):
                self.wellness_fixture(later)
                healthy = type(self).supplemental_response
                def response(query):
                    extra = healthy(query)
                    if not query.startswith('SELECT MEAN('):
                        return extra
                    item = extra["results"][-1]
                    entry = item["series"][0]
                    if mutation == "source":
                        entry["tags"] = {**TAGS, "User_ID": "private"}
                    elif mutation == "series":
                        item["series"] *= 2
                    elif mutation == "partial":
                        item["partial"] = True
                    elif mutation == "cap":
                        entry["values"] *= 2
                    elif mutation == "time":
                        entry["values"][0][0] = query.split("time < '")[1].split("'")[0]
                    elif mutation == "columns":
                        entry["columns"].append("private")
                    elif mutation == "statement":
                        item["statement_id"] = False
                    elif mutation == "count":
                        extra["results"].pop()
                    elif mutation == "name":
                        entry["name"] = "DailyStats"
                    elif mutation == "row":
                        entry["values"][0].pop()
                    elif mutation == "error":
                        item["error"] = "private"
                    else:
                        entry["values"][0][1] = mutation
                    return extra
                type(self).supplemental_response = staticmethod(response)
                fresh, _ = b.fetch(self.config, later, True)
                self.assertEqual(fresh["supplementalHistory"]["stress"], [])
                self.assertEqual(fresh["supplementalHistoryError"], error)
                result = b.run("fetch", self.config, later, True)
                self.assertEqual(result["supplementalHistory"]["stress"], initial["supplementalHistory"]["stress"])
                self.assertEqual(result["supplementalHistoryFetchedAt"], b.iso(NOW))
                self.assertEqual(result["supplementalHistoryError"], error)
                self.assertEqual(result["supplementalHistory"]["sleepDuration"][-1]["date"], "2026-09-05")
                self.assertEqual((result["status"], result["error"]), ("ok", None))
                self.assertEqual(result["stressFetchedAt"], b.iso(later))
                self.assertEqual(result["wellnessFetchedAt"], b.iso(later))
                self.assertNotIn("private", json.dumps(result))
                self.assertEqual(b.run("cache", self.config, later, True)["supplementalHistory"],
                                 result["supplementalHistory"])

    def test_stress_history_epoch_timestamp_null_and_empty_days(self):
        type(self).response = payload(charts=True)
        self.wellness_fixture()
        healthy = type(self).supplemental_response
        def response(query):
            extra = healthy(query)
            if query.startswith('SELECT MEAN('):
                for item in extra["results"]:
                    item["series"][0]["values"][0][0] = "1970-01-01T00:00:00Z"
                extra["results"][1].pop("series")
                extra["results"][4]["series"][0]["values"] = []
            return extra
        type(self).supplemental_response = staticmethod(response)
        result, _ = b.fetch(self.config, NOW, True)
        self.assertIsNone(result["supplementalHistoryError"])
        self.assertEqual([p["value"] for p in result["supplementalHistory"]["stress"]],
                         [0, None, 25.5, 100, None, 40, 50])

    def test_stress_history_timeout_preserves_cache_and_later_stress_series(self):
        type(self).response = payload(charts=True)
        self.wellness_fixture()
        initial = b.run("fetch", self.config, NOW, True)
        later = NOW + timedelta(hours=1)
        type(self).response = payload(later, True)
        self.wellness_fixture(later)
        request = b.request
        def fail_history(config, query, timeout):
            if query.startswith('SELECT MEAN('):
                raise b.Failure("timeout")
            return request(config, query, timeout)
        with patch.object(b, "request", side_effect=fail_history):
            result = b.run("fetch", self.config, later, True)
        self.assertEqual(result["supplementalHistory"]["stress"], initial["supplementalHistory"]["stress"])
        self.assertEqual(result["supplementalHistoryFetchedAt"], b.iso(NOW))
        self.assertEqual(result["supplementalHistoryError"], "timeout")
        self.assertEqual(result["stressFetchedAt"], b.iso(later))
        self.assertIsNone(result["stressError"])

    def test_source_day_start_empty_doctor_and_old_cache(self):
        for result in (b.empty(NOW, self.config["timezone"]), b.run("doctor", self.config, NOW)):
            self.assertEqual(result["sourceDayStart"], "2026-09-04T23:00:00Z")
            self.assertTrue(all(m["value"] is None for m in result["metrics"].values()))
        b.run("fetch", self.config, NOW)
        path, identity = b.cache_location(self.config)
        envelope = json.loads(path.read_text())
        envelope["data"].pop("sourceDayStart", None)
        path.write_text(json.dumps(envelope))
        result = b.read_cache(path, identity, self.config, NOW + timedelta(days=1))["data"]
        self.assertEqual(result["sourceDayStart"], "2026-09-05T23:00:00Z")

    def test_activity_details_same_row_zero_nullable_and_exact_names(self):
        for value in (1.5, 0, -1, None, True, "12"):
            type(self).activity_response = activity_payload(**{key: value for key in b.ACTIVITY_DETAILS})
            result = b.run("fetch", self.config, NOW)
            activity = result["latestActivity"]
            self.assertEqual(set(activity), {"id", "connectId", "time", "selector", *b.ACTIVITY_FIELDS})
            for key in b.ACTIVITY_DETAILS:
                valid = value == 1.5 or (value == 0 and key not in
                                         ("averageHR", "maxHR", "averageSpeed", "maxSpeed"))
                self.assertEqual(activity[key], value if valid else None)
            self.assertEqual(activity["time"], b.iso(NOW - timedelta(hours=1)))
            self.assertNotIn("activeCalories", activity)
            query = parse_qs(urlsplit(self.optional_requests[-1][1]).query)["q"][0]
            for key in b.ACTIVITY_DETAILS:
                self.assertIn('"' + key + '"', query)
            self.assertNotIn("LAST(", query)
            self.assertEqual(b.run("cache", self.config, NOW)["latestActivity"], activity)


if __name__ == "__main__":
    unittest.main()

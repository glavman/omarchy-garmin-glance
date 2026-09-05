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


class BackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                cls.requests.append((self.command, self.path, dict(self.headers)))
                self.send_response(cls.http_status)
                if cls.http_status == 302:
                    self.send_header("Location", cls.url + "/redirect-target")
                response = cls.response
                if cls.statements is not None:
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

    def test_all_missing(self):
        type(self).response = {"results": [{"statement_id": n} for n in range(4)]}
        result = b.run("fetch", self.config, NOW)
        self.assertEqual(result["status"], "partial")
        self.assertTrue(all(m["state"] == "missing" for m in result["metrics"].values()))

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
        path.write_text(json.dumps(envelope))
        cached = b.read_cache(path, identity, self.config, NOW + timedelta(hours=3))["data"]
        self.assertEqual([m["expiresAt"] for m in cached["metrics"].values()],
                         [m["expiresAt"] for m in result["metrics"].values()])
        for metric in b.empty(NOW, self.config["timezone"])["metrics"].values():
            self.assertIsNone(metric["expiresAt"])
        result["metrics"]["steps"]["value"] = None
        b.refresh_states(result, NOW)
        self.assertIsNone(result["metrics"]["steps"]["expiresAt"])
        self.assertTrue(all(m["expiresAt"] is not None for m in b.demo(NOW, True)["metrics"].values()))

    def test_steps_expiry_uses_source_midnight_across_dst(self):
        for sample, expiry, hours in (("2026-03-29T00:00:00Z", "2026-03-29T23:00:00Z", 23),
                                       ("2026-10-24T23:00:00Z", "2026-10-26T00:00:00Z", 25)):
            with self.subTest(sample=sample):
                now = b.timestamp(sample)
                type(self).response = payload(now)
                result, _ = b.fetch(self.config, now)
                self.assertEqual(result["metrics"]["steps"]["expiresAt"], expiry)
                self.assertEqual(b.timestamp(expiry) - now, timedelta(hours=hours))
                b.refresh_states(result, b.timestamp(expiry) - timedelta(microseconds=1))
                self.assertEqual(result["metrics"]["steps"]["state"], "fresh")
                b.refresh_states(result, b.timestamp(expiry))
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
        self.response["results"][0]["series"] *= 2
        with self.assertRaisesRegex(b.Failure, "^ambiguous_source$"):
            b.fetch(self.config, NOW)
        type(self).response = payload()
        self.response["results"][1]["series"][0]["tags"] = {**TAGS, "User_ID": "other"}
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
                self.assertNotIn("fixture-secret", json.dumps(result))
        self.assertEqual(len(self.requests), 4)
        type(self).http_status = 200
        type(self).raw = None
        type(self).response = {"error": "fixture-secret"}
        self.assertEqual(self.cli("doctor", "--config", str(path))[1]["error"], "query_error")

    def test_doctor_no_health_values_or_cache(self):
        path = self.config_file({"url": self.url})
        code, result = self.cli("doctor", "--config", str(path))
        self.assertEqual(code, 0)
        self.assertTrue(all(m["value"] is None for m in result["metrics"].values()))
        self.assertFalse((Path(self.temp.name) / "omarchy-garmin-glance").exists())

    def test_demo_bypasses_config_network_and_cache(self):
        with patch.object(b, "load_config", side_effect=AssertionError), patch.object(b, "request", side_effect=AssertionError):
            code, result = self.cli("fetch", "--demo", "--charts", "--config", "/does/not/exist")
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "demo")
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

    def test_missing_refresh_and_changed_source_cache_safety(self):
        b.run("fetch", self.config, NOW)
        type(self).response = {"results": [{"statement_id": n} for n in range(4)]}
        result = b.run("fetch", self.config, NOW + timedelta(days=31))
        self.assertTrue(all(m["value"] == 0 and m["state"] == "stale" for m in result["metrics"].values()))
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
            result, _ = b.fetch(self.config, NOW)
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
                result, _ = b.fetch(self.config, NOW)
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
            result, _ = b.fetch(self.config, NOW)
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


if __name__ == "__main__":
    unittest.main()

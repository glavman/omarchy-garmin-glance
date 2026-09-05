"""Synthetic coach sessions only: temporary home/config, mocked fetch and agent."""

import contextlib
from datetime import datetime, timedelta
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, call, patch


ROOT = Path(__file__).resolve().parents[1]
with patch.object(sys, "path", [str(ROOT), *sys.path]):
    SPEC = importlib.util.spec_from_file_location("coach", ROOT / "coach.py")
    c = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(c)
b = c.b
NOW = datetime(2026, 9, 5, 10, tzinfo=b.UTC)
SOURCE = "a" * 64
VALUES = {"bodyBattery": 73.125, "steps": 43217, "sleep": 86.375, "hrv": 54.625}
VALUES.update(sleepDuration=27000.125, restingHeartRate=53.125, trainingReadiness=71.375, stress=22.625)


class CoachTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="coach tests ")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.cache = self.home / "cache"
        self.root = self.cache / "omarchy-garmin-glance" / "coach"
        self.patch(patch.dict(os.environ, {
            "HOME": str(self.home), "XDG_CACHE_HOME": str(self.cache),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_DATA_HOME": str(self.home / "data"),
            "XDG_STATE_HOME": str(self.home / "state"), "PATH": "",
        }, clear=True))
        self.config = {"url": "https://synthetic.invalid:8443", "database": "fixture-database",
                       "timezone": "UTC", "username": "fixture-user",
                       "password": "fixture-password-DO-NOT-LEAK",
                       "tags": {"Device": "fixture-watch", "User_ID": "fixture-person"}}
        self.config_path = self.home / ".config/omarchy-garmin-glance/connection.json"
        self.config_path.parent.mkdir(parents=True, mode=0o700)
        self.write_json(self.config_path, self.config)
        self.request = {"intent": "day", "days": 7,
                        "stepGoal": 98765, "agent": "opencode"}
        self.which = self.patch(patch.object(c.shutil, "which", side_effect=lambda name: "/mock/" + name))
        self.run = self.patch(patch.object(c.subprocess, "run", side_effect=self.agent_process))
        self.process = Mock(spec=subprocess.Popen)
        self.process.wait.return_value = 0
        self.popen = self.patch(patch.object(c.subprocess, "Popen", return_value=self.process))
        self.real_fetch = c.fetch_context
        self.fetch = self.patch(patch.object(c, "fetch_context", side_effect=self.synthetic_fetch))
        self.network = self.patch(patch.object(b.urllib.request.OpenerDirector, "open",
                                              side_effect=AssertionError("real network forbidden")))
        self.real_cache_location = b.cache_location
        self.display_cache = self.patch(patch.object(b, "cache_location",
                                                    side_effect=AssertionError("display cache forbidden")))

    def patch(self, patcher):
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def write_json(self, path, value):
        path.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")
        path.chmod(0o600)

    def agent_process(self, argv, **kwargs):
        if argv == ["omarchy", "default", "agent"]:
            return subprocess.CompletedProcess(argv, 0, stdout="opencode\n")
        raise AssertionError("unexpected subprocess")

    def synthetic_fetch(self, config, end, days, metrics=None, history=False, activities=True):
        metrics = list(c.CONTEXT_METRICS) if metrics is None else metrics
        start = end.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
        result = {"schemaVersion": 2, "status": "ok", "fetchedAt": b.iso(end),
                  "timezone": "UTC", "window": {"start": b.iso(start), "end": b.iso(end), "days": days},
                  "sourceFingerprint": SOURCE, "metrics": {}, "warnings": []}
        if activities:
            result["activities"] = {"status": "empty", "error": None, "items": [],
                                    "coverage": {"count": 0, "firstAvailableDate": None,
                                                 "lastAvailableDate": None, "complete": True}}
        for key in metrics:
            if history:
                samples = [{"date": (start + timedelta(days=n)).date().isoformat(),
                            "time": b.iso(start + timedelta(days=n)), "value": VALUES[key],
                            "complete": n < days - 1} for n in range(days)]
                result["metrics"][key] = {"unit": c.CONTEXT_METRICS[key][2], "samples": samples,
                    "coverage": {"completedDays": days - 1, "validCompletedDays": days - 1,
                                 "missingCompletedDays": 0, "completedFraction": 1 if days > 1 else None,
                                 "firstAvailableDate": samples[0]["date"],
                                 "lastAvailableDate": samples[-1]["date"]},
                    "summary": {"mean": VALUES[key] if days > 1 else None}}
            else:
                result["metrics"][key] = {"value": VALUES[key], "time": b.iso(end), "date": None,
                                         "unit": c.CONTEXT_METRICS[key][2], "state": "fresh", "expiresAt": None,
                                         "status": "ok", "error": None}
        if not history:
            c.refresh_context(result, end)
        return result

    def session_paths(self):
        return sorted(p for p in self.root.iterdir() if c.SESSION_PATTERN.fullmatch(p.name)) if self.root.exists() else []

    def launch_session(self, **changes):
        before = set(self.session_paths())
        c.launch({**self.request, **changes}, NOW)
        created = set(self.session_paths()) - before
        self.assertEqual(len(created), 1)
        directory = created.pop()
        os.utime(directory, (NOW.timestamp(), NOW.timestamp()))
        return directory

    def metadata(self, directory, **changes):
        path = directory / "session.json"
        value = json.loads(path.read_text())
        value.update(changes)
        self.write_json(path, value)
        return value

    def cli(self, *args, raw="", now=NOW):
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(c, "datetime", wraps=datetime) as clock, patch.object(sys, "stdin", io.StringIO(raw)), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            clock.now.return_value = now
            code = c.main(list(args))
        self.assertEqual(errors.getvalue(), "")
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        result = json.loads(output.getvalue())
        self.assertEqual(code, int(result["status"] == "error"))
        for secret in self.secrets():
            self.assertNotIn(secret, output.getvalue())
        return code, result

    def secrets(self):
        return [self.config[k] for k in ("url", "database", "username", "password")] + list(self.config["tags"].values())

    def assert_error(self, error, *args, **kwargs):
        code, result = self.cli(*args, **kwargs)
        self.assertEqual(code, 1)
        self.assertEqual(result, {"schemaVersion": 1, "status": "error", "error": error, "agent": ""})

    def prompts(self):
        return self.popen.call_args_list

    def test_check_supported_agents_without_config_or_data(self):
        self.config_path.unlink()
        for agent in ("opencode", "claude", "codex", "grok"):
            with self.subTest(agent=agent):
                self.run.return_value = subprocess.CompletedProcess([], 0, stdout=" \n" + agent + "\n")
                self.run.side_effect = None
                code, result = self.cli("check")
                self.assertEqual(code, 0)
                self.assertEqual(result, {"schemaVersion": 1, "status": "ok", "error": None, "agent": agent})
                self.run.assert_called_with(["omarchy", "default", "agent"], capture_output=True,
                                            text=True, timeout=2, check=True)
        self.fetch.assert_not_called()
        self.assertFalse(self.root.exists())

    def test_check_missing_executables(self):
        for missing in ("omarchy", "opencode", "omarchy-agent-prompt"):
            with self.subTest(missing=missing):
                self.which.side_effect = lambda name: None if name == missing else "/mock/" + name
                self.run.reset_mock()
                self.assert_error("agent_unavailable", "check")
                if missing == "omarchy":
                    self.run.assert_not_called()
        self.fetch.assert_not_called()

    def test_check_unconfigured_and_unsupported_agents(self):
        for agent, error in ((" \n", "agent_not_configured"), ("other", "agent_unsupported"),
                             ("opencode --unsafe", "agent_unsupported"),
                             ("claude\ncodex", "agent_unsupported"),
                             (self.config["password"], "agent_unsupported")):
            with self.subTest(error=error, agent=agent):
                self.run.side_effect = None
                self.run.return_value = subprocess.CompletedProcess([], 0, stdout=agent)
                self.assert_error(error, "check")

    def test_check_process_errors_are_stable_and_private(self):
        secret = self.config["password"]
        for error in (OSError(secret), subprocess.CalledProcessError(1, secret, output=secret, stderr=secret),
                      subprocess.TimeoutExpired(secret, 2, output=secret, stderr=secret), UnicodeError(secret)):
            with self.subTest(error=type(error).__name__):
                self.run.side_effect = error
                self.assert_error("agent_unavailable", "check")

    def test_scope_rejects_invalid_days_and_metrics(self):
        for days in (True, False, 0, -1, 91, 1.5, "7", None, [], {}):
            with self.subTest(days=days), self.assertRaisesRegex(b.Failure, "^invalid_arguments$"):
                c.validate_scope(days, ["steps"])
        for metrics in (None, [], (), ("steps",), "steps", {}, ["unknown"], ["steps", "steps"],
                        [None], [True], [[]], [{}], list(b.METRICS) + ["steps"], ["steps; DROP DATABASE x"]):
            with self.subTest(metrics=metrics), self.assertRaisesRegex(b.Failure, "^invalid_arguments$"):
                c.validate_scope(7, metrics)
        self.fetch.assert_not_called()
        self.run.assert_not_called()

    def test_scope_accepts_inclusive_bounds_and_all_metric_subsets(self):
        names = list(b.METRICS)
        for days in (1, 90):
            for mask in range(1, 1 << len(names)):
                metrics = [key for n, key in enumerate(names) if mask & (1 << n)]
                with self.subTest(days=days, metrics=metrics):
                    c.validate_scope(days, metrics)

    def test_launch_requires_exact_consent_shape_and_valid_values(self):
        requests = [None, [], "yes", True, {}, {**self.request, "consent": True}]
        requests.extend({k: v for k, v in self.request.items() if k != missing} for missing in self.request)
        for field, values in (("intent", ("", "other", None, [], {})),
                              ("agent", ("", "other", None, [], {})),
                              ("stepGoal", (0, -1, 100001, True, False, "10000", None, [], {})),
                              ("days", (0, 91, True, "7")),
                              ("metrics", ([], ["unknown"], ["steps", "steps"], "steps"))):
            requests.extend({**self.request, field: value} for value in values)
        for request in requests:
            with self.subTest(request=request):
                self.assert_error("invalid_arguments", "launch", raw=json.dumps(request))
        self.run.assert_not_called()
        self.fetch.assert_not_called()
        self.assertFalse(self.root.exists())

    def test_launch_rejects_nonfinite_goal_before_agent_or_fetch(self):
        for value in (float("nan"), float("inf"), -float("inf")):
            with self.subTest(value=value), self.assertRaisesRegex(b.Failure, "^invalid_arguments$"):
                c.launch({**self.request, "stepGoal": value}, NOW)
        self.run.assert_not_called()
        self.fetch.assert_not_called()

    def test_launch_accepts_goal_and_days_boundaries_and_each_intent(self):
        for intent, days, goal in (("day", 1, 1), ("week", 90, 100000), ("question", 7, 12345.5)):
            with self.subTest(intent=intent):
                directory = self.launch_session(intent=intent, days=days, stepGoal=goal)
                self.fetch.assert_called_with(self.config, NOW, days)
                self.assertIn(c.INTENTS[intent], self.prompts()[-1].args[0][3])
                snapshot = json.loads((directory / "snapshot.json").read_text())
                self.assertEqual(snapshot["stepGoal"]["value"], goal)

    def test_launch_agent_changed_before_fetch(self):
        with self.assertRaisesRegex(b.Failure, "^agent_changed$"):
            c.launch({**self.request, "agent": "claude"}, NOW)
        self.fetch.assert_not_called()
        self.assertFalse(self.root.exists())

    def test_launch_missing_agent_or_launcher_never_fetches_or_creates_session(self):
        for missing in ("omarchy", "opencode", "omarchy-agent-prompt"):
            with self.subTest(missing=missing):
                self.which.side_effect = lambda name: None if name == missing else "/mock/" + name
                self.assert_error("agent_unavailable", "launch", raw=json.dumps(self.request))
                self.assertFalse(self.root.exists())
        self.fetch.assert_not_called()
        self.assertEqual(self.prompts(), [])

    def test_each_supported_agent_uses_the_same_handoff_protocol(self):
        for agent in ("opencode", "claude", "codex", "grok"):
            def agent_process(argv, **kwargs):
                if argv == ["omarchy", "default", "agent"]:
                    return subprocess.CompletedProcess(argv, 0, stdout=agent)
                return self.agent_process(argv, **kwargs)

            with self.subTest(agent=agent):
                self.run.side_effect = agent_process
                directory = self.launch_session(agent=agent)
                self.assertEqual(self.prompts()[-1].kwargs["cwd"], directory)
                self.assertEqual(self.prompts()[-1].args[0][:3], ["omarchy", "agent", "prompt"])
        self.assertTrue(all(args.args[0] == ["omarchy", "default", "agent"]
                            for args in self.run.call_args_list))

    def test_launch_agent_changed_during_fetch_cleans_session(self):
        self.run.side_effect = [subprocess.CompletedProcess([], 0, stdout="opencode"),
                                subprocess.CompletedProcess([], 0, stdout="claude")]
        self.assert_error("agent_changed", "launch", raw=json.dumps(self.request))
        self.assertEqual(self.session_paths(), [])
        self.assertEqual(self.prompts(), [])
        self.fetch.assert_called_once()

    def test_launch_agent_disappears_before_handoff_cleans_session(self):
        for stdout, error in (("", "agent_not_configured"), ("other", "agent_unsupported")):
            with self.subTest(error=error):
                self.run.side_effect = [subprocess.CompletedProcess([], 0, stdout="opencode"),
                                        subprocess.CompletedProcess([], 0, stdout=stdout)]
                self.assert_error(error, "launch", raw=json.dumps(self.request))
                self.assertEqual(self.session_paths(), [])
        self.assertEqual(self.prompts(), [])

    def test_launch_uses_private_dedicated_cwd_and_bounded_no_shell_argv(self):
        directory = self.launch_session()
        self.assertEqual(directory.parent, self.root)
        self.assertNotEqual(directory, Path.cwd())
        for path in (self.root.parent, self.root, directory):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
            self.assertEqual(path.stat().st_uid, os.getuid())
        self.assertEqual({p.name for p in directory.iterdir()}, {"snapshot.json", "session.json"})
        for path in (*directory.iterdir(), self.root / ".lock"):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        calls = self.prompts()
        self.assertEqual(len(calls), 1)
        argv = calls[0].args[0]
        self.assertEqual(argv[:3], ["omarchy", "agent", "prompt"])
        self.assertEqual(len(argv), 4)
        self.assertEqual(calls[0].kwargs, {"cwd": directory, "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "start_new_session": True})
        self.assertEqual(self.process.mock_calls, [call.wait(timeout=1)])
        for secret in self.secrets() + [SOURCE, c.fingerprint(self.config), str(self.request["stepGoal"])]:
            self.assertNotIn(secret, json.dumps(self.run.call_args_list + self.popen.call_args_list, default=str))
        for value in VALUES.values():
            self.assertNotIn(str(value), argv[3])
        self.assertIn(str(directory / "snapshot.json"), argv[3])
        self.assertIn(str(ROOT / "COACH.md"), argv[3])
        commands = [shlex.split(line) for line in argv[3].splitlines() if line.startswith("/usr/bin/python3")]
        self.assertEqual([line[2] for line in commands], ["capabilities", "summary", "history", "activities"])
        for line in commands:
            self.assertEqual(line[:2], ["/usr/bin/python3", str(ROOT / "coach.py")])
            self.assertEqual(line[3:5], ["--session", directory.name])
        self.assertIn("fixed at approval", argv[3])
        self.assertIn("Never read connection.json or session.json", argv[3])

    def test_snapshot_exact_public_schema_no_fingerprints_or_secrets(self):
        directory = self.launch_session()
        snapshot = json.loads((directory / "snapshot.json").read_text())
        self.assertEqual(set(snapshot), {"schemaVersion", "status", "fetchedAt", "timezone", "window",
                                         "metrics", "activities", "warnings", "stepGoal", "demo", "cached"})
        self.assertEqual(set(snapshot["metrics"]), set(c.CONTEXT_METRICS))
        self.assertEqual(snapshot["metrics"]["steps"]["value"], VALUES["steps"])
        self.assertEqual(snapshot["stepGoal"], {"value": 98765, "origin": "user configuration"})
        self.assertIs(snapshot["demo"], False)
        self.assertIs(snapshot["cached"], False)
        for secret in self.secrets() + [SOURCE, c.fingerprint(self.config), "sourceFingerprint", "configFingerprint"]:
            self.assertNotIn(secret, json.dumps(snapshot))
        metadata = json.loads((directory / "session.json").read_text())
        self.assertEqual(metadata, {"schemaVersion": 2, "createdAt": b.iso(NOW),
            "expiresAt": b.iso(NOW + timedelta(hours=24)), "days": 7,
            "configFingerprint": c.fingerprint(self.config), "sourceFingerprint": SOURCE})
        for secret in self.secrets():
            self.assertNotIn(secret, json.dumps(metadata))
        self.network.assert_not_called()
        self.display_cache.assert_not_called()

    def test_no_data_or_unidentified_source_never_launches(self):
        for mode in ("no_source", "all_missing"):
            snapshot = self.synthetic_fetch(self.config, NOW, 7, list(b.METRICS))
            if mode == "no_source":
                snapshot["sourceFingerprint"] = None
            else:
                for metric in snapshot["metrics"].values():
                    metric.update(value=None, time=None, date=None, state="missing", expiresAt=None)
            with self.subTest(mode=mode):
                self.fetch.side_effect = None
                self.fetch.return_value = snapshot
                self.assert_error("no_data", "launch", raw=json.dumps(self.request))
                self.assertEqual(self.session_paths(), [])
        self.assertEqual(self.prompts(), [])

    def test_zero_and_partial_data_can_launch_without_fabricating_missing_values(self):
        snapshot = self.synthetic_fetch(self.config, NOW, 7, ["steps", "sleep"])
        snapshot["metrics"]["steps"]["value"] = 0
        snapshot["metrics"]["sleep"].update(value=None, time=None, date=None, state="missing", expiresAt=None)
        snapshot["status"] = "partial"
        self.fetch.side_effect = None
        self.fetch.return_value = snapshot
        directory = self.launch_session()
        saved = json.loads((directory / "snapshot.json").read_text())
        self.assertEqual(saved["status"], "partial")
        self.assertEqual(saved["metrics"]["steps"]["value"], 0)
        self.assertIsNone(saved["metrics"]["sleep"]["value"])

    def test_empty_launch_preserves_representative_errors_without_leaking_text(self):
        for error in ("auth_error", "network_error", "timeout", "query_error", "http_error",
                      "invalid_values", "private server error"):
            for location in ("warning", "metric", "activities"):
                snapshot = self.synthetic_fetch(self.config, NOW, 7)
                snapshot["sourceFingerprint"] = None
                for metric in snapshot["metrics"].values():
                    metric.update(value=None, time=None, state="missing")
                if location == "warning":
                    snapshot["warnings"] = [{"section": "activities", "code": error}]
                else:
                    section = snapshot["activities"] if location == "activities" else snapshot["metrics"]["steps"]
                    section.update(status="unavailable", error=error)
                self.fetch.side_effect = None
                self.fetch.return_value = snapshot
                expected = error if error in {"auth_error", "network_error", "timeout", "query_error", "http_error"} else "data_unavailable"
                with self.subTest(error=error, location=location):
                    self.assert_error(expected, "launch", raw=json.dumps(self.request))
                    self.assertEqual(self.session_paths(), [])
        self.popen.assert_not_called()

    def test_empty_real_reader_launch_distinguishes_failure_from_no_data(self):
        self.fetch.side_effect = self.real_fetch
        for error in ("auth_error", "network_error", "timeout", "query_error", None):
            def transport(*_):
                if error == "query_error":
                    return {"results": [{"statement_id": 0, "error": "private database failure"}]}
                if error:
                    raise b.Failure(error)
                return {"results": [{"statement_id": 0}]}
            with self.subTest(error=error), patch.object(sys.modules["coach_data"], "_request", side_effect=transport) as request:
                self.assert_error(error or "no_data", "launch", raw=json.dumps(self.request))
                self.assertEqual(request.call_count, 9)
                self.assertEqual(self.session_paths(), [])
        self.popen.assert_not_called()

    def test_empty_launch_uses_first_representative_warning(self):
        snapshot = self.synthetic_fetch(self.config, NOW, 7)
        for metric in snapshot["metrics"].values():
            metric["value"] = None
        snapshot["warnings"] = [{"section": "activities", "code": "invalid_values"},
                                {"section": "steps", "code": "auth_error"},
                                {"section": "stress", "code": "timeout"}]
        self.fetch.side_effect = None
        self.fetch.return_value = snapshot
        self.assert_error("auth_error", "launch", raw=json.dumps(self.request))

    def test_activity_only_real_reader_launch_and_session_scoped_queries(self):
        def transport(config, query, params):
            if 'FROM "ActivitySummary"' not in query:
                return {"results": [{"statement_id": i} for i, _ in enumerate(query.split(";"))]}
            columns = ["time", *b.ACTIVITY_FIELDS.values(), *self.config["tags"], "ActivityID", "ActivitySelector"]
            values = [params["end0"], "running", *[10 for _ in list(b.ACTIVITY_FIELDS)[1:]],
                      *self.config["tags"].values(), "123456", "private-selector"]
            return {"results": [{"statement_id": 0, "series": [{"name": "ActivitySummary",
                "columns": columns, "values": [values]}]}]}
        self.fetch.side_effect = self.real_fetch
        with patch.object(sys.modules["coach_data"], "_request", side_effect=transport) as request:
            directory = self.launch_session(intent="question", days=30)
            snapshot = json.loads((directory / "snapshot.json").read_text())
            self.assertEqual(snapshot["schemaVersion"], 2)
            self.assertEqual(set(snapshot["metrics"]), set(c.CONTEXT_METRICS))
            self.assertTrue(all(m["value"] is None for m in snapshot["metrics"].values()))
            self.assertEqual(set(snapshot["activities"]["items"][0]), {"time", "date", *b.ACTIVITY_FIELDS})
            self.assertEqual(request.call_count, 9)
            self.assertIn("ActivitySummary", request.call_args_list[0].args[1])
            prompt = self.prompts()[-1].args[0][3]
            self.assertNotIn("supersedes", prompt)
            self.assertNotIn("old four-metric", prompt)
            for instruction in ("Do not output a report first", "2-3 sentence summary", "at most 2 recommendations", "120 words"):
                self.assertIn(instruction, prompt)
            for command in ("summary", "history", "activities"):
                with self.subTest(command=command):
                    result = self.cli(command, "--session", directory.name, "--days", "7", now=NOW + timedelta(hours=1))[1]
                    self.assertEqual(result["schemaVersion"], 2)
                    self.assertEqual(result["window"]["end"], b.iso(NOW))
                    self.assertEqual(result["window"]["days"], 7)
                    self.assertNotIn("sourceFingerprint", result)
                    self.assertNotIn("private-selector", json.dumps(result))
                    if command == "activities":
                        self.assertEqual(result["metrics"], {})
                        self.assertEqual(len(result["activities"]["items"]), 1)
            self.assert_error("scope_exceeded", "activities", "--session", directory.name, "--days", "31")
            self.assert_error("invalid_arguments", "activities", "--session", directory.name, "--metrics", "steps")
        self.network.assert_not_called()
        self.display_cache.assert_not_called()

    def test_launch_spawn_errors_clean_only_new_session(self):
        existing = self.launch_session()
        original = (existing / "snapshot.json").read_bytes()
        secret = self.config["password"]
        self.process.reset_mock()
        for error in (OSError(secret), FileNotFoundError(secret), PermissionError(secret)):
            with self.subTest(error=type(error).__name__):
                self.popen.side_effect = error
                self.assert_error("launch_failed", "launch", raw=json.dumps(self.request))
                self.assertEqual(self.session_paths(), [existing])
                self.assertEqual((existing / "snapshot.json").read_bytes(), original)
        self.process.wait.assert_not_called()

    def test_launch_immediate_nonzero_exit_cleans_only_new_session(self):
        existing = self.launch_session()
        original = {p: p.read_bytes() for p in existing.iterdir()}
        for returncode in (1, 127, -15):
            with self.subTest(returncode=returncode):
                self.process.reset_mock()
                self.process.wait.return_value = returncode
                self.assert_error("launch_failed", "launch", raw=json.dumps(self.request))
                self.assertEqual(self.process.mock_calls, [call.wait(timeout=1)])
                self.assertEqual(self.session_paths(), [existing])
                for path, content in original.items():
                    self.assertEqual(path.read_bytes(), content)

    def test_launch_wait_timeout_retains_usable_session_without_killing_process(self):
        secret = self.config["password"]
        self.process.wait.side_effect = subprocess.TimeoutExpired(secret, 1, output=secret, stderr=secret)
        self.assertEqual(self.cli("launch", raw=json.dumps(self.request)),
                         (0, {"schemaVersion": 1, "status": "ok", "error": None}))
        self.popen.assert_called_once()
        self.assertEqual(self.process.mock_calls, [call.wait(timeout=1)])
        self.assertEqual(len(self.session_paths()), 1)
        directory = self.session_paths()[0]
        self.assertEqual(self.popen.call_args.kwargs["cwd"], directory)
        self.assertIs(self.popen.call_args.kwargs["start_new_session"], True)
        originals = {p: p.read_bytes() for p in directory.iterdir()}
        self.assertEqual({p.name for p in originals}, c.SESSION_FILES)
        self.assertEqual(json.loads(originals[directory / "snapshot.json"])["metrics"]["steps"]["value"],
                         VALUES["steps"])
        for command in ("capabilities", "summary"):
            self.assertEqual(self.cli(command, "--session", directory.name)[0], 0)
        for path, content in originals.items():
            self.assertEqual(path.read_bytes(), content)
        for secret in self.secrets() + [SOURCE, c.fingerprint(self.config), str(self.request["stepGoal"])] + \
                [str(value) for value in VALUES.values()]:
            self.assertNotIn(secret, json.dumps(self.popen.call_args_list, default=str))

    def test_launch_write_failure_cleans_partial_session(self):
        original_write = c.write_private

        def fail_snapshot(path, data):
            if path.name == "snapshot.json":
                raise OSError(self.config["password"])
            original_write(path, data)

        with patch.object(c, "write_private", side_effect=fail_snapshot):
            self.assert_error("session_error", "launch", raw=json.dumps(self.request))
        self.assertEqual(self.session_paths(), [])
        self.assertEqual(self.prompts(), [])

    def test_launch_oversized_snapshot_cleans_written_metadata(self):
        snapshot = self.synthetic_fetch(self.config, NOW, 7, list(b.METRICS))
        snapshot["timezone"] = "x" * (b.MAX_BYTES + 1)
        self.fetch.side_effect = None
        self.fetch.return_value = snapshot
        self.assert_error("response_too_large", "launch", raw=json.dumps(self.request))
        self.assertEqual(self.session_paths(), [])
        self.assertEqual(self.prompts(), [])

    def test_launch_fetch_failures_are_private_and_leave_no_session(self):
        for error, code in ((b.Failure("timeout"), "timeout"), (b.Failure("ambiguous_source"), "ambiguous_source"),
                            (RuntimeError(self.config["password"]), "session_error")):
            with self.subTest(code=code):
                self.fetch.side_effect = error
                self.assert_error(code, "launch", raw=json.dumps(self.request))
                self.assertEqual(self.session_paths(), [])
        self.assertEqual(self.prompts(), [])

    def test_launch_config_identity_changed_before_handoff_fails_closed(self):
        def change_config(*args, **kwargs):
            self.write_json(self.config_path, {**self.config, "database": "different-fixture"})
            return self.synthetic_fetch(*args, **kwargs)

        self.fetch.side_effect = change_config
        self.assert_error("source_changed", "launch", raw=json.dumps(self.request))
        self.assertEqual(self.session_paths(), [])
        self.assertEqual(self.prompts(), [])

    def test_capabilities_exact_approved_scope_without_fetch_or_agent(self):
        directory = self.launch_session(days=90)
        self.fetch.reset_mock()
        self.run.reset_mock()
        self.popen.reset_mock()
        code, result = self.cli("capabilities", "--session", directory.name)
        self.assertEqual(code, 0)
        self.assertEqual(result, {"schemaVersion": 2, "status": "ok",
            "expiresAt": b.iso(NOW + timedelta(hours=24)), "windowEnd": b.iso(NOW), "maxDays": 90,
            "summaryMetrics": list(c.CONTEXT_METRICS), "historyMetrics": list(c.CONTEXT_METRICS),
            "historyAggregation": {k: "mean" if k == "stress" else "daily_highest" if k == "bodyBattery"
                                   else "latest_valid" for k in c.CONTEXT_METRICS},
            "activities": {"command": "activities", "fields": ["time", "date", *b.ACTIVITY_FIELDS],
                           "maxRows": 500, "window": "same fixed approved window"},
            "limits": {"maxResponseBytes": b.MAX_BYTES, "maxSnapshotBytes": b.MAX_BYTES},
            "coverage": "Unknown until history is queried; requested days do not imply available data."})
        self.fetch.assert_not_called()
        self.run.assert_not_called()
        self.popen.assert_not_called()

    def test_query_expiry_exact_24h_boundary_and_clock_before_approval(self):
        directory = self.launch_session()
        for delta in (timedelta(0), timedelta(hours=24, microseconds=-1)):
            with self.subTest(delta=delta):
                self.assertEqual(self.cli("capabilities", "--session", directory.name, now=NOW + delta)[0], 0)
        self.fetch.reset_mock()
        for command in ("capabilities", "summary", "history"):
            for delta in (timedelta(microseconds=-1), timedelta(hours=24), timedelta(days=2)):
                with self.subTest(command=command, delta=delta):
                    self.assert_error("session_expired", command, "--session", directory.name, now=NOW + delta)
        self.fetch.assert_not_called()

    def test_metadata_cannot_extend_absolute_lifetime_and_can_shorten_it(self):
        directory = self.launch_session()
        self.metadata(directory, expiresAt=b.iso(NOW + timedelta(days=30)))
        self.assert_error("session_expired", "summary", "--session", directory.name, now=NOW + timedelta(hours=24))
        self.metadata(directory, expiresAt=b.iso(NOW + timedelta(hours=1)))
        self.assert_error("session_expired", "summary", "--session", directory.name, now=NOW + timedelta(hours=1))

    def test_summary_window_is_pinned_but_freshness_uses_query_time(self):
        directory = self.launch_session()
        saved = (directory / "snapshot.json").read_bytes()
        later = NOW + timedelta(hours=15)
        self.fetch.reset_mock()
        code, result = self.cli("summary", "--session", directory.name, now=later)
        self.assertEqual(code, 0)
        self.fetch.assert_called_once_with(self.config, NOW, 7, list(c.CONTEXT_METRICS), history=False, activities=True)
        self.assertEqual(result["window"], {"start": "2026-08-30T00:00:00Z", "end": b.iso(NOW), "days": 7})
        self.assertEqual(result["fetchedAt"], b.iso(later))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(set(result), {"schemaVersion", "status", "fetchedAt", "timezone", "window", "metrics", "activities", "warnings"})
        for key, state in (("bodyBattery", "stale"), ("steps", "stale"), ("sleep", "fresh"), ("hrv", "fresh")):
            self.assertEqual(result["metrics"][key]["state"], state)
            self.assertEqual(result["metrics"][key]["time"], b.iso(NOW))
        self.assertNotIn("sourceFingerprint", result)
        self.assertNotIn("configFingerprint", result)
        self.assertEqual((directory / "snapshot.json").read_bytes(), saved)

    def test_summary_freshness_inclusive_boundary_then_stale(self):
        directory = self.launch_session()
        for extra, state, status in ((0, "fresh", "ok"), (1, "stale", "partial")):
            with self.subTest(extra=extra):
                result = c.query("summary", directory.name, None, None,
                                 NOW + timedelta(hours=2, microseconds=extra))
                self.assertEqual(result["metrics"]["bodyBattery"]["state"], state)
                self.assertEqual(result["status"], status)
                self.assertEqual(result["metrics"]["bodyBattery"]["expiresAt"], b.iso(NOW + timedelta(hours=2)))

    def test_history_defaults_all_metrics_and_keep_pinned_window(self):
        directory = self.launch_session()
        later = NOW + timedelta(hours=15)
        self.fetch.reset_mock()
        code, result = self.cli("history", "--session", directory.name, now=later)
        self.assertEqual(code, 0)
        self.fetch.assert_called_once_with(self.config, NOW, 7, list(c.CONTEXT_METRICS), history=True, activities=False)
        self.assertEqual(result["window"]["end"], b.iso(NOW))
        self.assertEqual(result["fetchedAt"], b.iso(later))
        self.assertEqual(set(result["metrics"]), set(c.CONTEXT_METRICS))
        self.assertNotIn("sourceFingerprint", result)
        self.assertNotIn("configFingerprint", result)
        self.assertFalse(result["metrics"]["steps"]["samples"][-1]["complete"])
        self.assertEqual(result["metrics"]["steps"]["samples"][-1]["date"], NOW.date().isoformat())

    def test_legacy_consent_never_gains_expanded_access(self):
        directory = self.launch_session()
        self.metadata(directory, schemaVersion=1, metrics=["bodyBattery"])
        self.fetch.reset_mock()
        saved = (directory / "snapshot.json").read_bytes()
        for command in ("capabilities", "summary", "history", "activities"):
            self.assert_error("session_expired", command, "--session", directory.name)
        self.assertEqual((directory / "snapshot.json").read_bytes(), saved)
        self.fetch.assert_not_called()

    def test_explicit_body_battery_history_is_supported(self):
        directory = self.launch_session()
        self.fetch.reset_mock()
        self.assertEqual(self.cli("history", "--session", directory.name, "--metrics", "bodyBattery")[0], 0)
        self.fetch.assert_called_once_with(self.config, NOW, 7, ["bodyBattery"], history=True, activities=False)

    def test_query_can_narrow_but_never_broaden_approved_scope(self):
        directory = self.launch_session(days=7)
        for command in ("summary", "history"):
            with self.subTest(command=command):
                result = c.query(command, directory.name, 1, ["sleep"], NOW)
                self.fetch.assert_called_with(self.config, NOW, 1, ["sleep"], history=command == "history", activities=command != "history")
                self.assertEqual(set(result["metrics"]), {"sleep"})
                self.assertEqual(result["window"]["days"], 1)
        self.fetch.reset_mock()
        for command in ("capabilities", "summary", "history"):
            for options in (("--days", "8"), ("--days", "90")):
                with self.subTest(command=command, options=options):
                    self.assert_error("scope_exceeded", command, "--session", directory.name, *options)
        self.fetch.assert_not_called()

    def test_query_rejects_invalid_days_and_metrics_before_fetch(self):
        directory = self.launch_session()
        self.fetch.reset_mock()
        for command in ("capabilities", "summary", "history"):
            for options in (("--days", "0"), ("--days", "-1"), ("--days", "91"),
                            ("--days", "1.0"), ("--days", "true"), ("--metrics", ""),
                            ("--metrics", "steps,steps"), ("--metrics", "unknown"),
                            ("--metrics", "steps,"), ("--metrics", "steps, sleep")):
                with self.subTest(command=command, options=options):
                    self.assert_error("invalid_arguments", command, "--session", directory.name, *options)
        self.fetch.assert_not_called()

    def test_source_changed_fails_closed_for_summary_and_history(self):
        directory = self.launch_session()
        for command in ("summary", "history"):
            result = self.synthetic_fetch(self.config, NOW, 7, ["steps"], history=command == "history")
            result["sourceFingerprint"] = "b" * 64
            self.fetch.side_effect = None
            self.fetch.return_value = result
            with self.subTest(command=command):
                self.assert_error("source_changed", command, "--session", directory.name, "--metrics", "steps")

    def test_query_fetch_errors_do_not_fall_back_to_saved_snapshot(self):
        directory = self.launch_session()
        for error in ("timeout", "auth_error", "network_error", "ambiguous_source", "truncated_response"):
            for command in ("summary", "history"):
                with self.subTest(error=error, command=command):
                    self.fetch.side_effect = b.Failure(error)
                    self.assert_error(error, command, "--session", directory.name)
        self.assertTrue((directory / "snapshot.json").exists())

    def test_query_no_series_preserves_missing_data_without_identity_or_cached_fallback(self):
        directory = self.launch_session()
        result = self.synthetic_fetch(self.config, NOW, 7, ["steps"])
        result["sourceFingerprint"] = None
        result["status"] = "partial"
        result["metrics"]["steps"].update(value=None, time=None, date=None, state="missing", expiresAt=None)
        self.fetch.side_effect = None
        self.fetch.return_value = result
        code, output = self.cli("summary", "--session", directory.name)
        self.assertEqual(code, 0)
        self.assertEqual(output["status"], "partial")
        self.assertIsNone(output["metrics"]["steps"]["value"])
        self.assertNotIn("sourceFingerprint", output)
        self.assertNotIn("configFingerprint", output)

    def test_config_identity_changes_fail_closed_before_fetch(self):
        directory = self.launch_session()
        self.fetch.reset_mock()
        for change in ({"url": "https://other.invalid"}, {"database": "other-db"},
                       {"username": "other-user"}, {"timezone": "Europe/Dublin"},
                       {"tags": {"Device": "other-watch"}}):
            self.write_json(self.config_path, {**self.config, **change})
            for command in ("capabilities", "summary", "history"):
                with self.subTest(change=change, command=command):
                    self.assert_error("source_changed", command, "--session", directory.name)
        self.fetch.assert_not_called()

    def test_password_rotation_for_same_source_does_not_require_new_approval(self):
        directory = self.launch_session()
        rotated = {**self.config, "password": "rotated-fixture-password"}
        self.write_json(self.config_path, rotated)
        self.assertEqual(c.fingerprint(rotated), c.fingerprint(self.config))
        for command in ("capabilities", "summary", "history"):
            with self.subTest(command=command):
                self.fetch.reset_mock()
                code, result = self.cli(command, "--session", directory.name)
                self.assertEqual(code, 0)
                self.assertEqual(result["status"], "ok")
                self.assertNotIn(rotated["password"], json.dumps(result))
                if command == "capabilities":
                    self.fetch.assert_not_called()
                else:
                    self.fetch.assert_called_once_with(rotated, NOW, 7, list(c.CONTEXT_METRICS),
                                                       history=command == "history", activities=command != "history")

    def test_fingerprint_is_order_independent_and_contains_no_raw_config(self):
        reordered = dict(reversed(list(self.config.items())))
        reordered["tags"] = dict(reversed(list(self.config["tags"].items())))
        digest = c.fingerprint(self.config)
        self.assertRegex(digest, r"\A[a-f0-9]{64}\Z")
        self.assertEqual(digest, c.fingerprint(reordered))
        for secret in self.secrets():
            self.assertNotIn(secret, digest)

    def test_query_refetches_instead_of_reusing_snapshot_or_display_cache(self):
        directory = self.launch_session()
        (directory / "snapshot.json").write_text("not a snapshot", encoding="utf-8")
        self.fetch.reset_mock()
        for _ in range(2):
            result = c.query("summary", directory.name, None, None, NOW)
            self.assertEqual(result["metrics"]["steps"]["value"], VALUES["steps"])
        self.assertEqual(self.fetch.call_count, 2)
        self.display_cache.assert_not_called()

    def test_missing_or_insecure_config_blocks_launch_and_existing_queries(self):
        directory = self.launch_session()
        self.fetch.reset_mock()
        self.run.reset_mock()
        self.popen.reset_mock()
        for mode in ("missing", "public", "invalid", "symlink"):
            with self.subTest(mode=mode):
                if self.config_path.exists() or self.config_path.is_symlink():
                    self.config_path.unlink()
                if mode == "public":
                    self.write_json(self.config_path, self.config)
                    self.config_path.chmod(0o644)
                elif mode == "invalid":
                    self.write_json(self.config_path, {"password": self.config["password"], "unknown": True})
                elif mode == "symlink":
                    target = self.home / "config-target"
                    self.write_json(target, self.config)
                    self.config_path.symlink_to(target)
                self.assert_error("invalid_config", "launch", raw=json.dumps(self.request))
                for command in ("capabilities", "summary", "history"):
                    self.assert_error("invalid_config", command, "--session", directory.name)
        self.fetch.assert_not_called()
        self.assertEqual(self.prompts(), [])

    def test_invalid_session_ids_never_touch_config_or_fetch(self):
        for session_id in (None, "", "../session-abcdefgh", "/tmp/session-abcdefgh", "session-abcdefg",
                           "session-abcdefghi", "session-ABCDefgh", "session-abcdefgh/..",
                           "session-abcdefgh\n", "session-abc.defg", "session-abcdefgh/child"):
            with self.subTest(session_id=session_id), self.assertRaisesRegex(b.Failure, "^invalid_arguments$"):
                c.query("summary", session_id, None, None, NOW)
        self.fetch.assert_not_called()
        self.assertFalse(self.root.exists())

    def test_missing_session_is_stable_error_not_fallback_data(self):
        self.assert_error("session_error", "summary", "--session", "session-abcdefgh")
        self.fetch.assert_not_called()

    def test_invalid_metadata_fails_closed(self):
        directory = self.launch_session()
        original = json.loads((directory / "session.json").read_text())
        self.fetch.reset_mock()
        for changes, error in (({"schemaVersion": 3}, "session_error"), ({"days": 91}, "invalid_arguments"),
                               ({"days": True}, "invalid_arguments"),
                               ({"createdAt": "not a timestamp"}, "invalid_arguments"),
                               ({"createdAt": "2026-09-05T10:00:00"}, "invalid_arguments"),
                               ({"expiresAt": None}, "invalid_arguments")):
            with self.subTest(changes=changes):
                self.write_json(directory / "session.json", {**original, **changes})
                self.assert_error(error, "summary", "--session", directory.name)
        for raw in ("{", "[]", "{}", "null", "x" * 16385):
            with self.subTest(raw=raw[:20]):
                (directory / "session.json").write_text(raw, encoding="utf-8")
                self.assert_error("invalid_arguments", "summary", "--session", directory.name)
        self.fetch.assert_not_called()

    def test_public_session_directory_and_metadata_rejected(self):
        directory = self.launch_session()
        self.fetch.reset_mock()
        for path, error in ((directory, "session_error"), (directory / "session.json", "invalid_arguments")):
            original = stat.S_IMODE(path.stat().st_mode)
            for mode in (original | 0o040, original | 0o004):
                with self.subTest(path=path.name, mode=mode):
                    path.chmod(mode)
                    self.assert_error(error, "summary", "--session", directory.name)
            path.chmod(original)
        self.fetch.assert_not_called()

    def test_query_refuses_symlinked_directory_and_metadata(self):
        directory = self.launch_session()
        self.fetch.reset_mock()
        target = self.home / "external-session"
        directory.rename(target)
        directory.symlink_to(target, target_is_directory=True)
        self.assert_error("session_error", "summary", "--session", directory.name)
        directory.unlink()
        target.rename(directory)
        metadata = directory / "session.json"
        target = self.home / "external-metadata"
        metadata.rename(target)
        metadata.symlink_to(target)
        self.assert_error("session_error", "summary", "--session", directory.name)
        self.assertTrue(target.is_file())
        self.fetch.assert_not_called()

    def test_session_root_and_lock_permission_and_symlink_rejection(self):
        with c.sessions() as root:
            self.assertEqual(root, self.root)
        for path in (self.root.parent, self.root, self.root / ".lock"):
            original = stat.S_IMODE(path.stat().st_mode)
            with self.subTest(path=path.name):
                path.chmod(original | 0o044)
                self.assert_error("session_error", "clear")
                path.chmod(original)
        lock = self.root / ".lock"
        target = self.home / "unrelated-lock"
        target.write_text("keep", encoding="utf-8")
        lock.unlink()
        lock.symlink_to(target)
        self.assert_error("session_error", "clear")
        self.assertEqual(target.read_text(), "keep")
        lock.unlink()
        external_root = self.home / "external-root"
        self.root.rename(external_root)
        self.root.symlink_to(external_root, target_is_directory=True)
        self.assert_error("session_error", "clear")
        self.assertTrue(external_root.is_dir())

    def test_sessions_without_xdg_cache_use_only_temporary_home(self):
        with patch.dict(os.environ):
            del os.environ["XDG_CACHE_HOME"]
            with c.sessions() as root:
                self.assertEqual(root, self.home / ".cache/omarchy-garmin-glance/coach")
                self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)

    def test_new_coach_root_under_umask_022_keeps_dashboard_cache_usable(self):
        self.assertFalse(self.root.parent.exists())
        previous_umask = os.umask(0o022)
        try:
            directory = self.launch_session()
            for path in (self.root.parent, self.root, directory):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
            self.display_cache.assert_not_called()
            path, key = self.real_cache_location(self.config)
            self.assertEqual(path.parent, self.root.parent)
            self.assertEqual(path.name, key + ".json")
            self.assertEqual(key, c.fingerprint(self.config))
        finally:
            os.umask(previous_umask)

    def test_fifo_lock_and_metadata_rejected_without_blocking(self):
        directory = self.launch_session()
        self.fetch.reset_mock()
        metadata = directory / "session.json"
        metadata.unlink()
        os.mkfifo(metadata, 0o600)
        self.assert_error("invalid_arguments", "summary", "--session", directory.name)
        lock = self.root / ".lock"
        lock.unlink()
        os.mkfifo(lock, 0o600)
        self.assert_error("session_error", "clear")
        self.fetch.assert_not_called()

    def test_foreign_owned_root_directory_metadata_and_lock_rejected(self):
        directory = self.launch_session()
        foreign = os.getuid() + 1
        original_lstat = Path.lstat
        original_fstat = os.fstat

        def foreign_info(info):
            fields = list(info)
            fields[4] = foreign
            return os.stat_result(fields)

        for target in (self.root.parent, self.root, directory):
            def lstat(path, *args, **kwargs):
                info = original_lstat(path, *args, **kwargs)
                return foreign_info(info) if path == target else info
            with self.subTest(target=target.name), patch.object(Path, "lstat", lstat):
                self.assert_error("session_error", "summary", "--session", directory.name)
        for target, expected in ((self.root / ".lock", "session_error"),
                                  (directory / "session.json", "invalid_arguments")):
            inode = target.stat().st_ino

            def fstat(fd):
                info = original_fstat(fd)
                return foreign_info(info) if info.st_ino == inode else info

            with self.subTest(target=target.name), patch.object(os, "fstat", side_effect=fstat):
                self.assert_error(expected, "summary", "--session", directory.name)

    def test_lock_contention_is_bounded_and_lock_released_after_failure(self):
        with c.sessions():
            self.assert_error("session_busy", "clear")
        with self.assertRaisesRegex(RuntimeError, "fixture"):
            with c.sessions():
                raise RuntimeError("fixture")
        self.assertEqual(self.cli("clear")[0], 0)
        with (self.root / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(lock, fcntl.LOCK_UN)

    def test_clear_removes_sessions_only_leaves_cache_chat_config_and_unknown_names(self):
        directories = [self.launch_session(), self.launch_session()]
        unrelated = [self.cache / "omarchy-garmin-glance/display.json",
                     self.home / "data/opencode/chat.json", self.home / ".claude/chat.json",
                     self.root / "session-not-owned/snapshot.json", self.root / "notes.json", self.config_path]
        for path in unrelated[:-1]:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.write_json(path, {"fixture": "keep this unrelated content"})
        originals = {path: path.read_bytes() for path in unrelated}
        self.fetch.reset_mock()
        self.run.reset_mock()
        self.popen.reset_mock()
        self.assertEqual(self.cli("clear"), (0, {"schemaVersion": 1, "status": "ok", "error": None}))
        self.assertTrue(all(not p.exists() for p in directories))
        for path, content in originals.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertTrue((self.root / ".lock").is_file())
        self.assertEqual(self.cli("clear")[0], 0)
        self.fetch.assert_not_called()
        self.run.assert_not_called()
        self.popen.assert_not_called()

    def test_clear_needs_neither_agent_nor_connection(self):
        directory = self.launch_session()
        self.config_path.unlink()
        self.which.side_effect = AssertionError("agent must not be checked")
        self.fetch.reset_mock()
        self.assertEqual(self.cli("clear")[0], 0)
        self.assertFalse(directory.exists())
        self.fetch.assert_not_called()

    def test_cleanup_exact_24h_mtime_boundary_and_ignores_unknown_names(self):
        fresh = self.launch_session()
        expired = self.launch_session()
        unknown = self.root / "session-not-owned"
        unknown.mkdir(mode=0o700)
        for path, age in ((fresh, 86400 - 0.001), (expired, 86400), (unknown, 172800)):
            os.utime(path, (NOW.timestamp() - age, NOW.timestamp() - age))
        c.cleanup(self.root, NOW)
        self.assertTrue(fresh.exists())
        self.assertFalse(expired.exists())
        self.assertTrue(unknown.exists())

    def test_launch_cleans_expired_sessions_before_enforcing_count_limit(self):
        self.root.parent.mkdir(mode=0o700, parents=True)
        self.root.mkdir(mode=0o700, parents=True)
        for index in range(20):
            directory = self.root / ("session-" + format(index, "08d"))
            directory.mkdir(mode=0o700, parents=True)
            self.write_json(directory / "snapshot.json", {"fixture": True})
            os.utime(directory, (NOW.timestamp() - 86400, NOW.timestamp() - 86400))
        directory = self.launch_session()
        self.assertEqual(self.session_paths(), [directory])

    def test_session_count_allows_twentieth_and_refuses_twenty_first_before_fetch(self):
        self.root.parent.mkdir(mode=0o700, parents=True)
        self.root.mkdir(mode=0o700, parents=True)
        for index in range(19):
            directory = self.root / ("session-" + format(index, "08d"))
            directory.mkdir(mode=0o700, parents=True)
            os.utime(directory, (NOW.timestamp(), NOW.timestamp()))
        for index in range(25):
            (self.root / ("unrelated-" + str(index))).mkdir(mode=0o700)
        self.launch_session()
        self.assertEqual(len(self.session_paths()), 20)
        self.fetch.reset_mock()
        self.run.reset_mock()
        self.popen.reset_mock()
        self.assert_error("session_limit", "launch", raw=json.dumps(self.request))
        self.fetch.assert_not_called()
        self.assertEqual(self.prompts(), [])
        self.assertEqual(len(self.session_paths()), 20)

    def test_removal_refuses_unknown_children_without_partial_deletion(self):
        directory = self.launch_session()
        original = {p: p.read_bytes() for p in directory.iterdir()}
        for name in ("chat.json", "subdirectory"):
            unknown = directory / name
            if name == "subdirectory":
                unknown.mkdir(mode=0o700)
            else:
                unknown.write_text("unrelated", encoding="utf-8")
            with self.subTest(name=name):
                self.assert_error("session_error", "clear")
                self.assertTrue(unknown.exists())
                for path, content in original.items():
                    self.assertEqual(path.read_bytes(), content)
            if unknown.is_dir():
                unknown.rmdir()
            else:
                unknown.unlink()

    def test_removal_refuses_session_symlink_and_preserves_target(self):
        directory = self.launch_session()
        target = self.home / "unrelated-directory"
        directory.rename(target)
        original = (target / "snapshot.json").read_bytes()
        directory.symlink_to(target, target_is_directory=True)
        self.assert_error("session_error", "clear")
        self.assertTrue(directory.is_symlink())
        self.assertEqual((target / "snapshot.json").read_bytes(), original)

    def test_cleanup_refuses_matching_regular_file_and_dangling_symlink(self):
        self.root.parent.mkdir(mode=0o700, parents=True)
        self.root.mkdir(mode=0o700, parents=True)
        path = self.root / "session-abcdefgh"
        self.write_json(path, {"unrelated": True})
        self.assert_error("session_error", "clear")
        self.assertEqual(json.loads(path.read_text()), {"unrelated": True})
        path.unlink()
        path.symlink_to(self.home / "missing-target")
        self.assert_error("session_error", "clear")
        self.assertTrue(path.is_symlink())

    def test_removal_refuses_symlink_fifo_and_directory_in_allowed_file_slot(self):
        directory = self.launch_session()
        snapshot = directory / "snapshot.json"
        metadata = (directory / "session.json").read_bytes()
        snapshot.unlink()
        target = self.home / "external-snapshot"
        target.write_text("unrelated", encoding="utf-8")
        for kind in ("symlink", "fifo", "directory"):
            if kind == "symlink":
                snapshot.symlink_to(target)
            elif kind == "fifo":
                os.mkfifo(snapshot, 0o600)
            else:
                snapshot.mkdir(mode=0o700)
            with self.subTest(kind=kind):
                self.assert_error("session_error", "clear")
                self.assertEqual((directory / "session.json").read_bytes(), metadata)
                self.assertEqual(target.read_text(), "unrelated")
            if kind == "directory":
                snapshot.rmdir()
            else:
                snapshot.unlink()

    def test_removal_refuses_public_or_foreign_owned_directory(self):
        directory = self.launch_session()
        directory.chmod(0o750)
        with self.assertRaisesRegex(b.Failure, "^session_error$"):
            c.remove_session(directory)
        directory.chmod(0o700)
        with patch.object(os, "getuid", return_value=os.getuid() + 1), \
                self.assertRaisesRegex(b.Failure, "^session_error$"):
            c.remove_session(directory)
        self.assertEqual({p.name for p in directory.iterdir()}, c.SESSION_FILES)

    def test_write_private_is_exclusive_bounded_and_does_not_follow_symlinks(self):
        path = self.home / "private.json"
        c.write_private(path, {"fixture": True})
        original = path.read_bytes()
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        with self.assertRaises(FileExistsError):
            c.write_private(path, {"overwrite": True})
        self.assertEqual(path.read_bytes(), original)
        link = self.home / "link.json"
        link.symlink_to(path)
        with self.assertRaises(OSError):
            c.write_private(link, {})
        self.assertEqual(path.read_bytes(), original)
        too_large = self.home / "large.json"
        with patch.object(b, "MAX_BYTES", 16), self.assertRaisesRegex(b.Failure, "^response_too_large$"):
            c.write_private(too_large, {"fixture": "x" * 16})
        self.assertFalse(too_large.exists())
        with self.assertRaises(ValueError):
            c.write_private(too_large, {"fixture": float("nan")})
        self.assertFalse(too_large.exists())

    def test_cli_rejects_unknown_commands_abbreviations_and_unexpected_options(self):
        cases = [(), ("unknown",), ("--help",), ("check", "extra"), ("check", "--unknown"),
                 ("summary", "--sess", "session-abcdefgh"), ("summary", "--days"), ("summary",)]
        for command in ("check", "launch", "clear"):
            cases.extend((command, *options) for options in (("--session", "session-abcdefgh"),
                         ("--days", "7"), ("--metrics", "steps")))
        for args in cases:
            with self.subTest(args=args):
                self.assert_error("invalid_arguments", *args)
        self.fetch.assert_not_called()
        self.run.assert_not_called()

    def test_cli_launch_reads_bounded_stdin_and_rejects_malformed_json(self):
        for raw in ("", "{", "{} {}", "null", "[]", '{"stepGoal":NaN}', '{"stepGoal":Infinity}',
                    " " * 16385, json.dumps(self.request) + " " * 16384):
            with self.subTest(raw=raw[:60]):
                self.assert_error("invalid_arguments", "launch", raw=raw)
        self.fetch.assert_not_called()
        self.run.assert_not_called()
        raw = json.dumps(self.request)
        self.assertEqual(self.cli("launch", raw=raw.ljust(16384)),
                         (0, {"schemaVersion": 1, "status": "ok", "error": None}))
        self.assertEqual(len(self.session_paths()), 1)

    def test_cli_generic_exceptions_never_include_exception_text_or_traceback(self):
        for error, expected in ((ValueError(self.config["password"]), "invalid_arguments"),
                                (TypeError(self.config["password"]), "invalid_arguments"),
                                (KeyError(self.config["password"]), "invalid_arguments"),
                                (OverflowError(self.config["password"]), "invalid_arguments"),
                                (RecursionError(self.config["password"]), "invalid_arguments"),
                                (RuntimeError(self.config["password"]), "session_error"),
                                (PermissionError(self.config["password"]), "session_error")):
            with self.subTest(error=type(error).__name__), patch.object(c, "agent_check", side_effect=error):
                self.assert_error(expected, "check")


if __name__ == "__main__":
    unittest.main()

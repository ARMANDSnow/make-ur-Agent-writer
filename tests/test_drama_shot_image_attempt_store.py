"""iter114: strict C3 attempt ledger, candidate bridge, and crash recovery."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from src import (
    drama_shot_image_attempts,
    drama_shot_image_attempt_store as store,
    drama_shot_image_candidate_store,
    paths,
)
from src.drama_schemas import _canonical_sha256
from src.secure_http import RequestNotSentError
from tests._drama_shot_image_attempt_base import DramaShotImageAttemptFixture


class _CountingAdapter:
    def __init__(self, payload: bytes, *, error: BaseException | None = None) -> None:
        self.payload = payload
        self.error = error
        self.calls = 0

    def generate(self, spec, *, prompt, reference_bytes):
        self.calls += 1
        if self.error is not None:
            raise self.error
        if not prompt or len(reference_bytes) != len(spec.references):
            raise AssertionError("adapter did not receive the exact C1 inputs")
        return self.payload


class DramaShotImageAttemptStoreTests(DramaShotImageAttemptFixture):
    def _run(self, name: str, sources, adapter):
        return store.run_shot_image_attempt_with_adapter(
            name,
            shot_id=sources["shot_id"],
            capability=sources["capability"],
            provider_fingerprint=sources["provider_fingerprint"],
            adapter=adapter,
            expected_manifest_fingerprint=sources["candidate_manifest"].manifest_fingerprint,
        )

    @staticmethod
    def _rehash_record(payload: dict) -> dict:
        current = json.loads(json.dumps(payload))
        current.pop("record_fingerprint", None)
        current["record_fingerprint"] = _canonical_sha256(current)
        return current

    @classmethod
    def _write_ledger_payload(cls, path: Path, ledger: dict) -> None:
        current = json.loads(json.dumps(ledger))
        current.pop("ledger_fingerprint", None)
        current["ledger_fingerprint"] = _canonical_sha256(current)
        envelope = {
            "schema_version": 1,
            "artifact_type": "drama_episode_shot_image_attempts",
            "ledger_fingerprint": current["ledger_fingerprint"],
            "ledger": current,
        }
        path.write_text(
            json.dumps(envelope, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_success_calls_adapter_once_bridges_exact_candidate_and_never_selects(self) -> None:
        sources = self._seed_attempt_sources("attempt-store-success")
        adapter = _CountingAdapter(self._png())
        with patch.object(socket, "socket", side_effect=AssertionError("network")):
            record = self._run("attempt-store-success", sources, adapter)
            replay = self._run("attempt-store-success", sources, adapter)
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(record, replay)
        self.assertEqual(record.status, "succeeded")
        manifest = drama_shot_image_candidate_store.load_fresh_episode_shot_image_candidates(
            "attempt-store-success"
        )
        pool = next(item for item in manifest.shots if item.shot_id == sources["shot_id"])
        self.assertEqual([item.candidate_id for item in pool.candidates], [record.candidate_id])
        self.assertIsNone(pool.first_binding)
        self.assertEqual(pool.tail_binding.kind, "none")
        self.assertTrue((paths.workspace_root("attempt-store-success") / record.staging_path).is_file())
        self.assertEqual(store.inspect_episode_shot_image_attempts("attempt-store-success").state, "fresh")

    def test_capability_block_occurs_before_marker_or_adapter_call(self) -> None:
        sources = self._seed_attempt_sources("attempt-store-capability")
        sources["capability"] = self._capability(0)
        adapter = _CountingAdapter(self._png())
        with self.assertRaisesRegex(ValueError, "rejected"):
            self._run("attempt-store-capability", sources, adapter)
        self.assertEqual(adapter.calls, 0)
        self.assertFalse(store.shot_image_attempt_ledger_path("attempt-store-capability").exists())

    def test_not_sent_is_the_only_path_that_releases_started_marker(self) -> None:
        sources = self._seed_attempt_sources("attempt-store-not-sent")
        adapter = _CountingAdapter(self._png(), error=RequestNotSentError("not sent"))
        with self.assertRaisesRegex(ValueError, "proven not sent"):
            self._run("attempt-store-not-sent", sources, adapter)
        ledger = store.load_episode_shot_image_attempts("attempt-store-not-sent")
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(ledger.attempts, [])

    def test_timeout_is_durable_and_never_auto_retried(self) -> None:
        sources = self._seed_attempt_sources("attempt-store-timeout")
        adapter = _CountingAdapter(self._png(), error=store.ShotImageProviderTimeout())
        with self.assertRaisesRegex(ValueError, "timed out"):
            self._run("attempt-store-timeout", sources, adapter)
        with self.assertRaises(store.ShotImageAttemptReconciliationRequired):
            self._run("attempt-store-timeout", sources, adapter)
        ledger = store.load_episode_shot_image_attempts("attempt-store-timeout")
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(ledger.attempts[-1].status, "timeout")

    def test_unknown_started_marker_never_calls_adapter_again(self) -> None:
        sources = self._seed_attempt_sources("attempt-store-unknown")
        adapter = _CountingAdapter(self._png(), error=SystemExit(87))
        with self.assertRaises(SystemExit):
            self._run("attempt-store-unknown", sources, adapter)
        safe = _CountingAdapter(self._png())
        with self.assertRaises(store.ShotImageAttemptReconciliationRequired):
            self._run("attempt-store-unknown", sources, safe)
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(safe.calls, 0)
        ledger = store.load_episode_shot_image_attempts("attempt-store-unknown")
        self.assertEqual(ledger.attempts[-1].status, "started")

    def test_unresolved_attempt_blocks_provider_and_capability_drift(self) -> None:
        sources = self._seed_attempt_sources("attempt-store-unresolved-drift")
        crashed = _CountingAdapter(self._png(), error=SystemExit(88))
        with self.assertRaises(SystemExit):
            self._run("attempt-store-unresolved-drift", sources, crashed)
        safe = _CountingAdapter(self._png(rgba=b"\xaa\xbb\xcc\xff"))
        for capability, provider in (
            (sources["capability"], "b" * 64),
            (self._capability(9), sources["provider_fingerprint"]),
        ):
            with self.assertRaises(store.ShotImageAttemptReconciliationRequired):
                store.run_shot_image_attempt_with_adapter(
                    "attempt-store-unresolved-drift",
                    shot_id=sources["shot_id"],
                    capability=capability,
                    provider_fingerprint=provider,
                    adapter=safe,
                    expected_manifest_fingerprint=sources["candidate_manifest"].manifest_fingerprint,
                )
        self.assertEqual(crashed.calls, 1)
        self.assertEqual(safe.calls, 0)

    def test_invalid_ledger_and_symlink_fail_closed(self) -> None:
        sources = self._seed_attempt_sources("attempt-store-invalid")
        path = store.shot_image_attempt_ledger_path("attempt-store-invalid")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{\"schema_version\":1,\"schema_version\":1}", encoding="utf-8")
        self.assertEqual(store.inspect_episode_shot_image_attempts("attempt-store-invalid").state, "invalid")
        path.unlink()
        target = path.parent / "target.json"
        target.write_text("{}", encoding="utf-8")
        path.symlink_to(target)
        with self.assertRaises(ValueError):
            self._run("attempt-store-invalid", sources, _CountingAdapter(self._png()))
        path.unlink()
        os.mkfifo(path)
        self.assertEqual(store.inspect_episode_shot_image_attempts("attempt-store-invalid").state, "invalid")

    def test_ledger_is_redacted_and_provider_drift_never_reuses_attempt(self) -> None:
        sources = self._seed_attempt_sources("attempt-store-redacted")
        adapter = _CountingAdapter(self._png())
        record = self._run("attempt-store-redacted", sources, adapter)
        raw = store.shot_image_attempt_ledger_path("attempt-store-redacted").read_text(
            encoding="utf-8"
        )
        prompt = sources["shot_image_plan"].shot_specs[0].image_prompt
        self.assertTrue(prompt)
        self.assertNotIn(prompt, raw)
        self.assertNotIn("api_key", raw.lower())
        changed = _CountingAdapter(self._png(rgba=b"\xaa\xbb\xcc\xff"))
        with self.assertRaisesRegex(ValueError, "manifest changed"):
            store.run_shot_image_attempt_with_adapter(
                "attempt-store-redacted",
                shot_id=sources["shot_id"],
                capability=sources["capability"],
                provider_fingerprint="b" * 64,
                adapter=changed,
                expected_manifest_fingerprint=sources["candidate_manifest"].manifest_fingerprint,
            )
        self.assertEqual(record.status, "succeeded")
        self.assertEqual(changed.calls, 0)

    def test_succeeded_resume_cross_checks_ledger_candidate_identity(self) -> None:
        sources = self._seed_attempt_sources("attempt-store-candidate-tamper")
        self._run("attempt-store-candidate-tamper", sources, _CountingAdapter(self._png()))
        path = store.shot_image_attempt_ledger_path("attempt-store-candidate-tamper")
        envelope = json.loads(path.read_text(encoding="utf-8"))
        record = envelope["ledger"]["attempts"][-1]
        record["candidate_id"] = "sic_" + "0" * 24
        record["candidate_fingerprint"] = "0" * 64
        envelope["ledger"]["attempts"][-1] = self._rehash_record(record)
        self._write_ledger_payload(path, envelope["ledger"])
        with self.assertRaisesRegex(ValueError, "exact candidate"):
            store.resume_shot_image_attempt(
                "attempt-store-candidate-tamper",
                shot_id=sources["shot_id"],
                capability=sources["capability"],
                provider_fingerprint=sources["provider_fingerprint"],
            )

    def test_succeeded_resume_rejects_receipt_identity_tamper(self) -> None:
        sources = self._seed_attempt_sources("attempt-store-receipt-tamper")
        self._run("attempt-store-receipt-tamper", sources, _CountingAdapter(self._png()))
        path = store.shot_image_attempt_ledger_path("attempt-store-receipt-tamper")
        envelope = json.loads(path.read_text(encoding="utf-8"))
        record = envelope["ledger"]["attempts"][-1]
        receipt = record["artifact_receipt"]
        receipt["sha256"] = "f" * 64
        receipt.pop("receipt_fingerprint", None)
        receipt["receipt_fingerprint"] = _canonical_sha256(receipt)
        envelope["ledger"]["attempts"][-1] = self._rehash_record(record)
        self._write_ledger_payload(path, envelope["ledger"])
        with self.assertRaisesRegex(ValueError, "candidate is missing"):
            store.resume_shot_image_attempt(
                "attempt-store-receipt-tamper",
                shot_id=sources["shot_id"],
                capability=sources["capability"],
                provider_fingerprint=sources["provider_fingerprint"],
            )

    def test_historical_stale_attempt_does_not_poison_current_inspection(self) -> None:
        sources = self._seed_attempt_sources("attempt-store-history")
        self._run("attempt-store-history", sources, _CountingAdapter(self._png()))
        path = store.shot_image_attempt_ledger_path("attempt-store-history")
        envelope = json.loads(path.read_text(encoding="utf-8"))
        current = envelope["ledger"]["attempts"][-1]

        def renumber(record: dict, attempt_no: int) -> dict:
            value = json.loads(json.dumps(record))
            value["attempt_no"] = attempt_no
            value["attempt_id"] = "sia_" + _canonical_sha256(
                {
                    "input_fingerprint": value["spec"]["input_fingerprint"],
                    "attempt_no": attempt_no,
                }
            )[:24]
            value["staging_path"] = (
                f"logs/drama_shot_images/episode_{value['spec']['episode_no']:02d}/"
                f"{value['spec']['shot_id']}/{value['attempt_id']}.png"
            )
            if value.get("artifact_receipt") is not None:
                receipt = value["artifact_receipt"]
                receipt["staging_path"] = value["staging_path"]
                receipt.pop("receipt_fingerprint", None)
                receipt["receipt_fingerprint"] = _canonical_sha256(receipt)
            return self._rehash_record(value)

        old_spec = json.loads(json.dumps(current["spec"]))
        old_spec["source_plan_fingerprint"] = "b" * 64
        old_spec["request_fingerprint"] = "c" * 64
        old_spec.pop("input_fingerprint")
        old_spec["input_fingerprint"] = _canonical_sha256(old_spec)
        old = json.loads(json.dumps(current))
        old["spec"] = old_spec
        old = renumber(old, 1)
        latest = renumber(current, 2)
        envelope["ledger"]["attempts"] = [old, latest]
        envelope["ledger"]["revision"] += 1
        self._write_ledger_payload(path, envelope["ledger"])
        inspection = store.inspect_episode_shot_image_attempts("attempt-store-history")
        self.assertEqual(inspection.state, "fresh")
        self.assertEqual(inspection.outstanding_attempt_ids, [])

        current_first = renumber(current, 1)
        stale_latest = json.loads(json.dumps(current))
        stale_latest["spec"] = old_spec
        stale_latest = renumber(stale_latest, 2)
        envelope["ledger"]["attempts"] = [current_first, stale_latest]
        envelope["ledger"]["revision"] += 1
        self._write_ledger_payload(path, envelope["ledger"])
        aba_inspection = store.inspect_episode_shot_image_attempts("attempt-store-history")
        self.assertEqual(aba_inspection.state, "fresh")
        self.assertEqual(aba_inspection.outstanding_attempt_ids, [])

    def test_completion_rechecks_latest_candidate_manifest_under_final_lock(self) -> None:
        name = "attempt-store-final-lock-race"
        sources = self._seed_attempt_sources(name)
        original_lock = store.acquire_write_lock
        store_lock_calls = 0
        raced_manifest = None

        @contextmanager
        def racing_lock(*, source: str):
            nonlocal store_lock_calls, raced_manifest
            store_lock_calls += 1
            if store_lock_calls == 2:
                current = drama_shot_image_candidate_store.load_fresh_episode_shot_image_candidates(
                    name
                )
                pool = next(item for item in current.shots if item.shot_id == sources["shot_id"])
                candidate = pool.candidates[0]
                raced_manifest = drama_shot_image_candidate_store.select_episode_shot_image_frame(
                    name,
                    shot_id=sources["shot_id"],
                    frame="first",
                    binding={
                        "kind": "direct",
                        "candidate_id": candidate.candidate_id,
                        "candidate_fingerprint": candidate.candidate_fingerprint,
                    },
                    expected_selection_revision=pool.selection_revision,
                    expected_current_binding=pool.first_binding,
                    expected_manifest_fingerprint=current.manifest_fingerprint,
                )
            with original_lock(source=source):
                yield

        with patch.object(store, "acquire_write_lock", side_effect=racing_lock):
            record = self._run(name, sources, _CountingAdapter(self._png()))
        self.assertEqual(store_lock_calls, 2)
        self.assertIsNotNone(raced_manifest)
        self.assertEqual(record.status, "succeeded")
        self.assertEqual(record.post_manifest_fingerprint, raced_manifest.manifest_fingerprint)

    def test_invalid_provider_png_is_terminal_and_not_retried(self) -> None:
        sources = self._seed_attempt_sources("attempt-store-bad-provider")
        adapter = _CountingAdapter(b"not-a-png")
        with self.assertRaisesRegex(ValueError, "adapter failed"):
            self._run("attempt-store-bad-provider", sources, adapter)
        with self.assertRaises(store.ShotImageAttemptReconciliationRequired):
            self._run("attempt-store-bad-provider", sources, adapter)
        ledger = store.load_episode_shot_image_attempts("attempt-store-bad-provider")
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(ledger.attempts[-1].status, "provider_error")

    def test_provider_png_dimensions_are_rejected_before_staging(self) -> None:
        sources = self._seed_attempt_sources("attempt-store-wide-provider")
        adapter = _CountingAdapter(self._png(width=9000))
        with self.assertRaisesRegex(ValueError, "adapter failed"):
            self._run("attempt-store-wide-provider", sources, adapter)
        ledger = store.load_episode_shot_image_attempts("attempt-store-wide-provider")
        record = ledger.attempts[-1]
        self.assertEqual(record.status, "provider_error")
        self.assertFalse((paths.workspace_root("attempt-store-wide-provider") / record.staging_path).exists())

    def test_adapter_exception_is_bounded_and_does_not_persist_raw_text(self) -> None:
        sources = self._seed_attempt_sources("attempt-store-error-redaction")
        secret = "https://signed.example/result?token=SECRET API_KEY=SECRET"
        adapter = _CountingAdapter(self._png(), error=RuntimeError(secret))
        with self.assertRaisesRegex(ValueError, "adapter failed") as raised:
            self._run("attempt-store-error-redaction", sources, adapter)
        self.assertNotIn("SECRET", str(raised.exception))
        cursor = raised.exception
        while cursor is not None:
            self.assertNotIn("SECRET", str(cursor))
            self.assertIsNone(cursor.__cause__)
            cursor = cursor.__context__
        raw = store.shot_image_attempt_ledger_path("attempt-store-error-redaction").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("SECRET", raw)

    def test_oversize_deep_and_directory_ledgers_fail_closed(self) -> None:
        for suffix, payload in (
            ("oversize", b" " * (store.MAX_SHOT_IMAGE_ATTEMPT_LEDGER_BYTES + 1)),
            ("deep", ("[" * 300 + "]" * 300).encode("utf-8")),
        ):
            with self.subTest(suffix=suffix):
                name = f"attempt-store-{suffix}"
                self._seed_attempt_sources(name)
                path = store.shot_image_attempt_ledger_path(name)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
                self.assertEqual(store.inspect_episode_shot_image_attempts(name).state, "invalid")
        name = "attempt-store-ledger-directory"
        self._seed_attempt_sources(name)
        path = store.shot_image_attempt_ledger_path(name)
        path.mkdir(parents=True)
        self.assertEqual(store.inspect_episode_shot_image_attempts(name).state, "invalid")

    def test_staging_symlink_fifo_and_directory_block_before_adapter_call(self) -> None:
        for kind in ("symlink", "fifo", "directory"):
            with self.subTest(kind=kind):
                name = f"attempt-store-staging-{kind}"
                sources = self._seed_attempt_sources(name)
                spec = drama_shot_image_attempts.build_shot_image_attempt_spec(
                    sources["shot_image_plan"],
                    sources["candidate_manifest"],
                    shot_id=sources["shot_id"],
                    capability=sources["capability"],
                    provider_fingerprint=sources["provider_fingerprint"],
                )
                ledger = drama_shot_image_attempts.build_empty_shot_image_attempt_ledger(
                    sources["shot_image_plan"]
                )
                _, record = drama_shot_image_attempts.start_shot_image_attempt(
                    ledger,
                    spec,
                    expected_ledger_fingerprint=ledger.ledger_fingerprint,
                )
                staging = paths.workspace_root(name) / record.staging_path
                staging.parent.mkdir(parents=True, exist_ok=True)
                if kind == "symlink":
                    target = staging.parent / "target.png"
                    target.write_bytes(self._png())
                    staging.symlink_to(target)
                elif kind == "fifo":
                    os.mkfifo(staging)
                else:
                    staging.mkdir()
                adapter = _CountingAdapter(self._png())
                with self.assertRaises(ValueError):
                    self._run(name, sources, adapter)
                self.assertEqual(adapter.calls, 0)
                self.assertFalse(store.shot_image_attempt_ledger_path(name).exists())

    def test_partial_ledger_write_cleans_owned_temp_and_never_calls_adapter(self) -> None:
        name = "attempt-store-partial-ledger"
        sources = self._seed_attempt_sources(name)
        adapter = _CountingAdapter(self._png())
        with patch.object(store.os, "write", return_value=0):
            with self.assertRaisesRegex(ValueError, "could not be written safely"):
                self._run(name, sources, adapter)
        self.assertEqual(adapter.calls, 0)
        ledger_path = store.shot_image_attempt_ledger_path(name)
        self.assertFalse(ledger_path.exists())
        self.assertEqual(list(ledger_path.parent.glob(f".{ledger_path.name}.tmp.*")), [])

    def test_partial_staging_write_is_never_adopted_or_resubmitted(self) -> None:
        name = "attempt-store-partial-staging"
        sources = self._seed_attempt_sources(name)
        adapter = _CountingAdapter(self._png())
        original_write = store.os.write
        staging_writes = 0

        def fail_mid_staging(file_fd: int, data) -> int:
            nonlocal staging_writes
            if staging_writes == 0 and bytes(data[:8]) == b"\x89PNG\r\n\x1a\n":
                staging_writes = 1
                return original_write(file_fd, data[: max(1, len(data) // 2)])
            if staging_writes == 1:
                staging_writes = 2
                raise OSError("injected staging short write")
            return original_write(file_fd, data)

        with patch.object(store.os, "write", side_effect=fail_mid_staging):
            with self.assertRaisesRegex(ValueError, "zero-provider reconciliation"):
                self._run(name, sources, adapter)
        self.assertEqual(adapter.calls, 1)
        ledger = store.load_episode_shot_image_attempts(name)
        self.assertEqual(ledger.attempts[-1].status, "started")
        staging = paths.workspace_root(name) / ledger.attempts[-1].staging_path
        self.assertTrue(staging.is_file())
        self.assertLess(staging.stat().st_size, len(self._png()))
        replay = _CountingAdapter(self._png())
        with self.assertRaises(ValueError):
            self._run(name, sources, replay)
        self.assertEqual(replay.calls, 0)

    def test_missing_nofollow_blocks_before_adapter_call(self) -> None:
        name = "attempt-store-no-nofollow"
        sources = self._seed_attempt_sources(name)
        adapter = _CountingAdapter(self._png())
        with patch.object(store.os, "O_NOFOLLOW", None):
            with self.assertRaisesRegex(ValueError, "operation was rejected"):
                self._run(name, sources, adapter)
        self.assertEqual(adapter.calls, 0)
        self.assertFalse(store.shot_image_attempt_ledger_path(name).exists())

    def test_ledger_target_cas_rejects_concurrent_target_change(self) -> None:
        name = "attempt-store-ledger-cas"
        sources = self._seed_attempt_sources(name)
        self._run(name, sources, _CountingAdapter(self._png()))
        ledger = store.load_episode_shot_image_attempts(name)
        root = paths.workspace_root(name)
        path = store.shot_image_attempt_ledger_path(name)
        expected = store._ledger_target_token(root, path)
        original_target_token_at = store._ledger_target_token_at
        checks = 0

        def change_before_precommit(directory_fd: int, filename: str):
            nonlocal checks
            checks += 1
            if checks == 2:
                target_fd = os.open(filename, os.O_WRONLY | os.O_TRUNC, dir_fd=directory_fd)
                try:
                    os.write(target_fd, b"tampered")
                    os.fsync(target_fd)
                finally:
                    os.close(target_fd)
            return original_target_token_at(directory_fd, filename)

        with patch.object(store, "_ledger_target_token_at", side_effect=change_before_precommit):
            with self.assertRaisesRegex(ValueError, "changed concurrently"):
                store._write_ledger(name, ledger, expected_target_token=expected)
        self.assertEqual(checks, 2)
        self.assertEqual(list(path.parent.glob(f".{path.name}.tmp.*")), [])

    def test_ledger_temp_inode_replacement_never_overwrites_target_or_deletes_replacement(self) -> None:
        name = "attempt-store-ledger-temp-race"
        sources = self._seed_attempt_sources(name)
        self._run(name, sources, _CountingAdapter(self._png()))
        ledger = store.load_episode_shot_image_attempts(name)
        root = paths.workspace_root(name)
        path = store.shot_image_attempt_ledger_path(name)
        expected = store._ledger_target_token(root, path)
        before = path.read_bytes()
        original_stat = store.os.stat
        replaced_name = None

        def replace_temp_before_identity_check(filename, *args, **kwargs):
            nonlocal replaced_name
            if (
                replaced_name is None
                and isinstance(filename, str)
                and filename.startswith(f".{path.name}.tmp.")
                and kwargs.get("follow_symlinks") is False
            ):
                directory_fd = kwargs["dir_fd"]
                store.os.unlink(filename, dir_fd=directory_fd)
                replacement_fd = store.os.open(
                    filename,
                    store.os.O_WRONLY | store.os.O_CREAT | store.os.O_EXCL,
                    0o600,
                    dir_fd=directory_fd,
                )
                try:
                    original_write = store.os.write
                    original_write(replacement_fd, b"replacement-owned-elsewhere")
                finally:
                    store.os.close(replacement_fd)
                replaced_name = filename
            return original_stat(filename, *args, **kwargs)

        with patch.object(store.os, "stat", side_effect=replace_temp_before_identity_check):
            with self.assertRaisesRegex(ValueError, "temporary ledger changed"):
                store._write_ledger(name, ledger, expected_target_token=expected)
        self.assertEqual(path.read_bytes(), before)
        self.assertIsNotNone(replaced_name)
        replacement = path.parent / replaced_name
        self.assertEqual(replacement.read_bytes(), b"replacement-owned-elsewhere")
        replacement.unlink()

    def test_real_process_crash_windows_resume_without_second_adapter_call(self) -> None:
        driver = Path(__file__).parent / "support" / "drama_shot_image_attempt_driver.py"
        for mode, resumable, expected_calls in (
            ("after_started", False, 0),
            ("after_call", False, 1),
            ("after_adapter_return", False, 1),
            ("after_staging", True, 1),
            ("after_receipt", True, 1),
            ("after_candidate", True, 1),
            ("after_candidate_corrupt", True, 1),
            ("after_succeeded", True, 1),
        ):
            with self.subTest(mode=mode):
                name = f"attempt-crash-{mode.replace('_', '-')}"
                sources = self._seed_attempt_sources(name)
                counter = Path(self._tmp.name) / f"{mode}.counter"
                env = dict(os.environ)
                env["OPENAI_MODEL"] = "mock"
                env["SHOT_IMAGE_ATTEMPT_PNG_HEX"] = self._png().hex()
                result = subprocess.run(
                    [
                        sys.executable,
                        str(driver),
                        str(paths.WORKSPACE_DIR),
                        name,
                        mode,
                        str(counter),
                    ],
                    cwd=Path(__file__).parents[1],
                    env=env,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                self.assertNotEqual(result.returncode, 0, result.stderr)
                actual_calls = int(counter.read_text(encoding="utf-8")) if counter.exists() else 0
                self.assertEqual(actual_calls, expected_calls)
                if mode in {"after_candidate", "after_candidate_corrupt"}:
                    ledger = store.load_episode_shot_image_attempts(name)
                    staging = paths.workspace_root(name) / ledger.attempts[-1].staging_path
                    if mode == "after_candidate":
                        staging.unlink()
                    else:
                        staging.write_bytes(b"corrupt-staging")
                if resumable:
                    record = store.resume_shot_image_attempt(
                        name,
                        shot_id=sources["shot_id"],
                        capability=sources["capability"],
                        provider_fingerprint=sources["provider_fingerprint"],
                    )
                    self.assertEqual(record.status, "succeeded")
                else:
                    with self.assertRaises(store.ShotImageAttemptReconciliationRequired):
                        store.resume_shot_image_attempt(
                            name,
                            shot_id=sources["shot_id"],
                            capability=sources["capability"],
                            provider_fingerprint=sources["provider_fingerprint"],
                        )
                actual_calls = int(counter.read_text(encoding="utf-8")) if counter.exists() else 0
                self.assertEqual(actual_calls, expected_calls)

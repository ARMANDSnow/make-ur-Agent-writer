"""iter138 G6 strict media pricing facts and Insights projection."""

from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path
from unittest.mock import patch

from src import (
    drama_media_pricing,
    drama_media_queue_client,
    drama_media_tasks,
)
from src.drama_schemas import _canonical_sha256
from src.web.drama_insights import collect_drama_insights
from tests._drama_base import DramaTestBase
from tests._drama_media_backend_fixture import (
    MODEL_ID,
    PROVIDER_ID,
    build_registry,
)


class DramaMediaPricingTests(DramaTestBase):
    _IDENTITY = {
        "backend_id": "local-fixture",
        "provider_fingerprint": "1" * 64,
        "model_fingerprint": "2" * 64,
        "account_fingerprint": "3" * 64,
        "endpoint_fingerprint": "4" * 64,
    }

    def setUp(self) -> None:
        super().setUp()
        self.name = "media-pricing"
        self._make_drama_workspace(self.name, episode_count=2)
        self.now = 1_700_000_000_000
        self._sequence = 0
        self.registry = build_registry(
            media_kind="image",
            backend_id=self._IDENTITY["backend_id"],
            provider_fingerprint=self._IDENTITY[
                "provider_fingerprint"
            ],
            model_fingerprint=self._IDENTITY["model_fingerprint"],
        )
        self.task_id = self._enqueue("shot_001")

    def _enqueue(self, subject_id: str, *, episode_no: int = 1) -> str:
        with patch.object(
            drama_media_queue_client,
            "_wall_clock_ms",
            return_value=self.now,
        ):
            result = drama_media_queue_client.enqueue_media_task(
                self.name,
                episode_no=episode_no,
                media_kind="image",
                stage="image-generate",
                subject_id=subject_id,
                input_fingerprint=hashlib.sha256(
                    subject_id.encode()
                ).hexdigest(),
                provider_id=PROVIDER_ID,
                model_id=MODEL_ID,
                registry=self.registry,
                **self._IDENTITY,
            )
        return result["task_id"]

    def _evidence(self, label: str) -> str:
        return hashlib.sha256(label.encode()).hexdigest()

    def _pricing(self):
        return drama_media_pricing.load_media_pricing_ledger(
            self.name, episode_no=1
        )

    def _record(
        self,
        kind: str,
        amount: str | None,
        *,
        task_id: str | None = None,
        currency: str = "CNY",
        evidence: str | None = None,
        expected: str | None | object = ...,
        recorded_at_ms: int | None = None,
    ):
        self._sequence += 1
        try:
            ledger = self._pricing()
            current = ledger.ledger_fingerprint
        except FileNotFoundError:
            current = None
        if expected is ...:
            expected = current
        return drama_media_pricing.record_media_pricing_fact(
            self.name,
            episode_no=1,
            task_id=task_id or self.task_id,
            fact_kind=kind,
            currency=currency,
            amount=amount,
            source_evidence_fingerprint=(
                evidence
                or self._evidence(
                    f"{task_id or self.task_id}:{kind}:{self._sequence}"
                )
            ),
            recorded_at_ms=(
                self.now + self._sequence
                if recorded_at_ms is None
                else recorded_at_ms
            ),
            expected_ledger_fingerprint=expected,
        )

    def _authorize(self, *, task_id: str | None = None, currency="CNY"):
        self._record(
            "estimate", "10.250001", task_id=task_id, currency=currency
        )
        self._record(
            "authorized", "12.000000", task_id=task_id, currency=currency
        )
        self._record(
            "reserved", "11.000000", task_id=task_id, currency=currency
        )

    def test_amount_parser_is_exact_and_rejects_ambiguous_numbers(self) -> None:
        self.assertEqual(
            drama_media_pricing.parse_amount_microunits("12.3456"),
            12_345_600,
        )
        self.assertEqual(
            drama_media_pricing.format_amount_microunits(12_345_600),
            "12.345600",
        )
        for value in (
            True,
            1,
            1.0,
            "-1",
            "+1",
            "01",
            "1.",
            ".1",
            "1e2",
            "1.0000001",
            "10000000000",
            "",
        ):
            with self.subTest(value=value):
                with self.assertRaises(
                    drama_media_pricing.DramaMediaPricingError
                ):
                    drama_media_pricing.parse_amount_microunits(value)

    def test_schema_rejects_bool_float_extra_and_evidence_kind_forgery(
        self,
    ) -> None:
        fact = self._record("estimate", "1")
        original = fact.model_dump(mode="json")

        def rebuilt(**changes):
            payload = {**original, **changes}
            content = {
                key: value
                for key, value in payload.items()
                if key not in {"fact_id", "fact_fingerprint"}
            }
            fingerprint = _canonical_sha256(content)
            payload["fact_id"] = f"dmpf_{fingerprint[:24]}"
            payload["fact_fingerprint"] = fingerprint
            return payload

        for changes in (
            {"amount_microunits": True},
            {"amount_microunits": 1.0},
            {"source_evidence_kind": "paid_actual"},
            {"unexpected": "private"},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    drama_media_pricing.DramaMediaPricingFact(
                        **rebuilt(**changes)
                    )

    def test_full_chain_refunds_and_over_authorization_are_auditable(self) -> None:
        self._authorize()
        self._record("actual", "13.500001")
        self._record("refunded", "1.250000")
        self._record("refunded", "0.250001")

        ledger = self._pricing()
        projected = drama_media_pricing.aggregate_media_pricing_ledger(
            ledger
        )
        self.assertEqual(projected["fact_count"], 6)
        row = projected["rows"][0]
        self.assertEqual(row["estimate"], "10.250001")
        self.assertEqual(row["authorized"], "12.000000")
        self.assertEqual(row["actual_known"], "13.500001")
        self.assertEqual(row["refunded"], "1.500001")
        self.assertEqual(row["net_actual_known"], "12.000000")
        self.assertEqual(row["estimate_actual_delta"], "3.250000")
        self.assertFalse(row["unknown_submission"])
        currency = projected["currencies"][0]
        self.assertEqual(currency["actual_known"], "13.500001")
        self.assertEqual(currency["net_actual_known"], "12.000000")
        self.assertTrue(currency["actual_complete"])

    def test_unknown_is_not_zero_and_later_actual_resolves_it(self) -> None:
        self._authorize()
        self._record("unknown", None)
        first = drama_media_pricing.aggregate_media_pricing_ledger(
            self._pricing()
        )
        row = first["rows"][0]
        self.assertIsNone(row["actual_known"])
        self.assertIsNone(row["net_actual_known"])
        self.assertTrue(row["unknown_submission"])
        self.assertEqual(
            first["currencies"][0]["unknown_submission_tasks"], 1
        )
        self.assertFalse(first["currencies"][0]["actual_complete"])

        self._record("actual", "8.000000")
        second = drama_media_pricing.aggregate_media_pricing_ledger(
            self._pricing()
        )
        self.assertEqual(
            second["rows"][0]["actual_known"], "8.000000"
        )
        self.assertFalse(second["rows"][0]["unknown_submission"])
        self.assertEqual(
            second["currencies"][0]["unknown_submission_tasks"], 0
        )
        self.assertTrue(second["currencies"][0]["actual_complete"])

    def test_transition_currency_and_refund_guards_fail_closed(self) -> None:
        with self.assertRaises(
            drama_media_pricing.DramaMediaPricingError
        ):
            self._record("actual", "1")
        self._record("estimate", "10")
        with self.assertRaises(
            drama_media_pricing.DramaMediaPricingError
        ):
            self._record("reserved", "1")
        self._record("authorized", "10")
        with self.assertRaises(
            drama_media_pricing.DramaMediaPricingError
        ):
            self._record("reserved", "11")
        self._record("reserved", "9")
        with self.assertRaises(
            drama_media_pricing.DramaMediaPricingError
        ):
            self._record("actual", "1", currency="USD")
        self._record("actual", "5")
        with self.assertRaises(
            drama_media_pricing.DramaMediaPricingError
        ):
            self._record("refunded", "5.000001")
        self.assertEqual(len(self._pricing().facts), 4)

    def test_reservation_cannot_be_backfilled_after_paid_outcome(self) -> None:
        self._record("estimate", "10")
        self._record("authorized", "10")
        self._record("actual", "8")
        with self.assertRaises(
            drama_media_pricing.DramaMediaPricingError
        ):
            self._record("reserved", "8")
        self.assertEqual(
            [item.fact_kind for item in self._pricing().facts],
            ["estimate", "authorized", "actual"],
        )

    def test_exact_replay_is_idempotent_but_conflict_is_rejected(self) -> None:
        evidence = self._evidence("estimate")
        first = self._record(
            "estimate", "1.250000", evidence=evidence
        )
        before = self._pricing()
        replay = self._record(
            "estimate",
            "1.250000",
            evidence=evidence,
            expected="f" * 64,
            recorded_at_ms=first.recorded_at_ms,
        )
        self.assertEqual(replay, first)
        self.assertEqual(self._pricing(), before)
        with self.assertRaises(
            drama_media_pricing.DramaMediaPricingError
        ):
            self._record(
                "estimate",
                "1.250000",
                evidence=evidence,
                expected=before.ledger_fingerprint,
                recorded_at_ms=first.recorded_at_ms + 1,
            )
        with self.assertRaises(
            drama_media_pricing.DramaMediaPricingError
        ):
            self._record(
                "estimate",
                "1.250001",
                evidence=evidence,
                expected=before.ledger_fingerprint,
            )
        self.assertEqual(self._pricing(), before)

    def test_stale_ledger_cas_rejects_new_fact(self) -> None:
        self._record("estimate", "1")
        with self.assertRaises(
            drama_media_pricing.DramaMediaPricingError
        ):
            self._record(
                "authorized", "1", expected="f" * 64
            )
        self.assertEqual(len(self._pricing().facts), 1)

    def test_evidence_cannot_be_spliced_across_tasks(self) -> None:
        other = self._enqueue("shot_002")
        evidence = self._evidence("shared")
        self._record("estimate", "1", evidence=evidence)
        with self.assertRaises(
            drama_media_pricing.DramaMediaPricingError
        ):
            self._record(
                "estimate",
                "2",
                task_id=other,
                evidence=evidence,
            )
        self.assertEqual(len(self._pricing().facts), 1)

    def test_evidence_cannot_be_spliced_across_episode_ledgers(self) -> None:
        other = self._enqueue("shot_002", episode_no=2)
        evidence = self._evidence("workspace-shared")
        self._record("estimate", "1", evidence=evidence)
        with self.assertRaises(
            drama_media_pricing.DramaMediaPricingError
        ):
            drama_media_pricing.record_media_pricing_fact(
                self.name,
                episode_no=2,
                task_id=other,
                fact_kind="estimate",
                currency="CNY",
                amount="2",
                source_evidence_fingerprint=evidence,
                recorded_at_ms=self.now + 20,
                expected_ledger_fingerprint=None,
            )
        with self.assertRaises(FileNotFoundError):
            drama_media_pricing.load_media_pricing_ledger(
                self.name, episode_no=2
            )

    def test_insights_rejects_fully_rehashed_cross_episode_evidence_reuse(
        self,
    ) -> None:
        evidence = self._evidence("read-side-workspace-shared")
        self._record("estimate", "1", evidence=evidence)
        other = self._enqueue("shot_002", episode_no=2)
        drama_media_pricing.record_media_pricing_fact(
            self.name,
            episode_no=2,
            task_id=other,
            fact_kind="estimate",
            currency="CNY",
            amount="2",
            source_evidence_fingerprint=self._evidence("episode-2-original"),
            recorded_at_ms=self.now + 20,
            expected_ledger_fingerprint=None,
        )
        ledger = drama_media_pricing.load_media_pricing_ledger(
            self.name, episode_no=2
        )
        payload = ledger.model_dump(mode="json")
        fact = payload["facts"][0]
        fact["source_evidence_fingerprint"] = evidence
        fact_payload = {
            key: value
            for key, value in fact.items()
            if key not in {"fact_id", "fact_fingerprint"}
        }
        fact_fingerprint = _canonical_sha256(fact_payload)
        fact["fact_id"] = f"dmpf_{fact_fingerprint[:24]}"
        fact["fact_fingerprint"] = fact_fingerprint
        ledger_payload = {
            key: value
            for key, value in payload.items()
            if key != "ledger_fingerprint"
        }
        payload["ledger_fingerprint"] = _canonical_sha256(ledger_payload)
        forged = drama_media_pricing.DramaMediaPricingLedger(**payload)
        drama_media_pricing.media_pricing_ledger_path(
            self.name, episode_no=2
        ).write_bytes(drama_media_pricing._ledger_bytes(forged))

        data = collect_drama_insights(self.name)["media_pricing"]
        self.assertEqual(data["status"], "degraded")
        self.assertEqual(data["ledger_count"], 0)
        self.assertEqual(data["fact_count"], 0)
        self.assertEqual(data["task_count"], 0)
        self.assertEqual(data["currencies"], [])
        self.assertEqual(data["rows"], [])

    def test_multi_currency_is_never_summed_or_converted(self) -> None:
        usd_task = self._enqueue("shot_002")
        self._authorize(currency="CNY")
        self._record("actual", "8", currency="CNY")
        self._authorize(task_id=usd_task, currency="USD")
        self._record(
            "unknown", None, task_id=usd_task, currency="USD"
        )

        projected = drama_media_pricing.aggregate_media_pricing_ledger(
            self._pricing()
        )
        self.assertEqual(
            [item["currency"] for item in projected["currencies"]],
            ["CNY", "USD"],
        )
        cny, usd = projected["currencies"]
        self.assertEqual(cny["actual_known"], "8.000000")
        self.assertTrue(cny["actual_complete"])
        self.assertEqual(usd["actual_known"], "0.000000")
        self.assertEqual(usd["unknown_submission_tasks"], 1)
        self.assertFalse(usd["actual_complete"])
        self.assertNotIn("total", projected)
        self.assertNotIn("converted", json.dumps(projected))

    def test_fully_rehashed_task_identity_splice_is_rejected(self) -> None:
        self._record("estimate", "1")
        ledger = self._pricing()
        payload = ledger.model_dump(mode="json")
        fact = payload["facts"][0]
        fact["provider_id"] = "other-provider"
        fact_payload = {
            key: value
            for key, value in fact.items()
            if key not in {"fact_id", "fact_fingerprint"}
        }
        fact_fingerprint = _canonical_sha256(fact_payload)
        fact["fact_id"] = f"dmpf_{fact_fingerprint[:24]}"
        fact["fact_fingerprint"] = fact_fingerprint
        ledger_payload = {
            key: value
            for key, value in payload.items()
            if key != "ledger_fingerprint"
        }
        payload["ledger_fingerprint"] = _canonical_sha256(ledger_payload)
        forged = drama_media_pricing.DramaMediaPricingLedger(**payload)
        drama_media_pricing.media_pricing_ledger_path(
            self.name, episode_no=1
        ).write_bytes(drama_media_pricing._ledger_bytes(forged))

        with self.assertRaises(
            drama_media_pricing.DramaMediaPricingError
        ):
            self._pricing()

    def test_invalid_target_types_and_atomic_failure_never_commit(self) -> None:
        path = drama_media_pricing.media_pricing_ledger_path(
            self.name, episode_no=1
        )
        path.parent.mkdir(parents=True)
        path.symlink_to(Path("missing.json"))
        with self.assertRaises(
            drama_media_pricing.DramaMediaPricingError
        ):
            self._record("estimate", "1")
        self.assertTrue(path.is_symlink())
        path.unlink()

        with patch.object(
            drama_media_pricing,
            "_write_ledger",
            side_effect=drama_media_pricing.DramaMediaPricingError(
                "blocked"
            ),
        ):
            with self.assertRaises(
                drama_media_pricing.DramaMediaPricingError
            ):
                self._record("estimate", "1")
        self.assertFalse(path.exists())

    def test_namespace_replacement_between_scan_and_commit_is_rejected(
        self,
    ) -> None:
        self._record("estimate", "1")
        path = drama_media_pricing.media_pricing_ledger_path(
            self.name, episode_no=1
        )
        directory = path.parent
        displaced = directory.with_name("media_pricing_displaced")
        alternate = directory.with_name("media_pricing_alternate")
        alternate.mkdir()
        original_bytes = path.read_bytes()
        (alternate / path.name).write_bytes(original_bytes)
        original_write = drama_media_pricing._write_ledger

        def swap_namespace(*args, **kwargs):
            directory.rename(displaced)
            alternate.rename(directory)
            return original_write(*args, **kwargs)

        try:
            with patch.object(
                drama_media_pricing,
                "_write_ledger",
                side_effect=swap_namespace,
            ):
                with self.assertRaises(
                    drama_media_pricing.DramaMediaPricingError
                ):
                    self._record("authorized", "1")
            self.assertEqual(
                len(
                    drama_media_pricing.load_media_pricing_ledger(
                        self.name, episode_no=1
                    ).facts
                ),
                1,
            )
            self.assertEqual(
                (displaced / path.name).read_bytes(),
                original_bytes,
            )
        finally:
            if displaced.exists():
                if directory.exists():
                    directory.rename(alternate)
                displaced.rename(directory)
            if alternate.exists():
                for child in alternate.iterdir():
                    child.unlink()
                alternate.rmdir()

    def test_oversized_and_directory_ledgers_degrade_insights(self) -> None:
        path = drama_media_pricing.media_pricing_ledger_path(
            self.name, episode_no=1
        )
        path.parent.mkdir(parents=True)
        path.write_bytes(
            b"x" * (drama_media_pricing.MAX_MEDIA_PRICING_LEDGER_BYTES + 1)
        )
        data = collect_drama_insights(self.name)["media_pricing"]
        self.assertEqual(data["status"], "degraded")
        self.assertEqual(data["invalid_ledgers"], 1)
        self.assertEqual(data["fact_count"], 0)
        path.unlink()
        path.mkdir()
        data = collect_drama_insights(self.name)["media_pricing"]
        self.assertEqual(data["status"], "degraded")
        self.assertGreaterEqual(data["invalid_ledgers"], 1)

    def test_insights_projection_is_allowlisted_and_redacted(self) -> None:
        self._authorize()
        self._record("unknown", None)
        data = collect_drama_insights(self.name)["media_pricing"]
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["ledger_count"], 1)
        self.assertEqual(data["task_count"], 1)
        row = data["rows"][0]
        self.assertEqual(
            set(row),
            {
                "task_id",
                "episode_no",
                "subject_id",
                "media_kind",
                "stage",
                "provider_id",
                "model_id",
                "currency",
                "fact_count",
                "estimate",
                "authorized",
                "reserved",
                "actual_known",
                "refunded",
                "net_actual_known",
                "estimate_actual_delta",
                "unknown_submission",
            },
        )
        rendered = json.dumps(data, ensure_ascii=False)
        for private in (
            self._IDENTITY["account_fingerprint"],
            self._IDENTITY["endpoint_fingerprint"],
            self._IDENTITY["provider_fingerprint"],
            self._IDENTITY["model_fingerprint"],
            "source_evidence_fingerprint",
            "binding_fingerprint",
            "ledger_fingerprint",
            "prompt",
            "response",
        ):
            self.assertNotIn(private, rendered)

    def test_workspace_insights_budget_degrades_without_partial_totals(
        self,
    ) -> None:
        self._record("estimate", "1")
        with patch.object(
            drama_media_pricing,
            "MAX_MEDIA_PRICING_INSIGHTS_FACTS",
            0,
        ):
            data = collect_drama_insights(self.name)["media_pricing"]
        self.assertEqual(data["status"], "degraded")
        self.assertEqual(data["fact_count"], 0)
        self.assertEqual(data["task_count"], 0)
        self.assertEqual(data["currencies"], [])
        self.assertEqual(data["rows"], [])

    def test_noncanonical_namespace_entry_is_counted_not_read(self) -> None:
        directory = (
            drama_media_pricing.media_pricing_ledger_path(
                self.name, episode_no=1
            ).parent
        )
        directory.mkdir(parents=True)
        (directory / "episode_1.pricing.json").write_text(
            "private-provider-response", encoding="utf-8"
        )
        data = collect_drama_insights(self.name)["media_pricing"]
        self.assertEqual(data["status"], "degraded")
        self.assertEqual(data["invalid_ledgers"], 1)
        self.assertNotIn(
            "private-provider-response",
            json.dumps(data, ensure_ascii=False),
        )

    def test_symlinked_pricing_namespace_is_degraded_without_following(
        self,
    ) -> None:
        directory = (
            drama_media_pricing.media_pricing_ledger_path(
                self.name, episode_no=1
            ).parent
        )
        external = Path(self._tmp.name) / "outside-pricing"
        external.mkdir()
        (external / "episode_001.pricing.json").write_text(
            "private-provider-response", encoding="utf-8"
        )
        directory.parent.mkdir(parents=True, exist_ok=True)
        directory.symlink_to(external, target_is_directory=True)

        data = collect_drama_insights(self.name)["media_pricing"]
        self.assertEqual(data["status"], "degraded")
        self.assertEqual(data["invalid_ledgers"], 1)
        self.assertEqual(data["ledger_count"], 0)
        self.assertNotIn(
            "private-provider-response",
            json.dumps(data, ensure_ascii=False),
        )

    def test_operations_are_zero_network(self) -> None:
        with patch.object(
            socket, "socket", side_effect=AssertionError("network forbidden")
        ):
            self._authorize()
            self._record("actual", "9")
            data = collect_drama_insights(self.name)["media_pricing"]
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["fact_count"], 4)


if __name__ == "__main__":
    import unittest

    unittest.main()

"""Durable E2 TTS execution with once-only synthesis and retryable download."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from . import paths
from .drama_audio import probe_mock_wav_fixture
from .drama_schemas import (
    TtsAttemptRecord,
    TtsAttemptSpec,
    TtsAudioArtifact,
    TtsAuthorization,
    TtsProviderCapability,
    UtteranceSpec,
    _canonical_sha256,
)
from .drama_store import (
    _read_strict_workspace_bytes,
    _read_strict_workspace_json,
    _validate_render_workspace_root,
)
from .drama_tts_attempts import (
    build_tts_attempt_spec,
    complete_tts_attempt,
    mark_tts_not_sent,
    mark_tts_submission_unknown,
    record_tts_artifact,
    record_tts_provider_failed,
    record_tts_submission,
    start_tts_attempt,
)
from .schemas import model_to_dict
from .secure_http import RequestNotSentError
from .web.workspace_ctx import use_workspace
from .workspace_lock import acquire_write_lock


class DramaTtsAttemptStoreError(ValueError):
    pass


class TtsAttemptReconciliationRequired(DramaTtsAttemptStoreError):
    pass


class TtsSubmissionUnknownError(ConnectionError):
    pass


class TtsProviderTerminalError(ValueError):
    def __init__(self, provider_request_id: str) -> None:
        super().__init__("TTS provider rejected the synthesis")
        self.provider_request_id = provider_request_id


@dataclass(frozen=True)
class TtsAdapterIdentity:
    backend_id: str
    provider_fingerprint: str
    model_fingerprint: str
    account_fingerprint: str
    endpoint_fingerprint: str
    auth_fingerprint: str


class TtsProviderAdapter(Protocol):
    identity: TtsAdapterIdentity

    def synthesize(self, spec: TtsAttemptSpec, *, text: str) -> str: ...

    def download(self, spec: TtsAttemptSpec, *, provider_request_id: str) -> bytes: ...


class LocalFakeTtsAdapter:
    def __init__(self, *, identity: TtsAdapterIdentity, wav_bytes: bytes) -> None:
        if type(wav_bytes) is not bytes:
            raise TypeError("fake TTS output must be bytes")
        self.identity = identity
        self._wav_bytes = wav_bytes
        self.synthesis_calls = 0
        self.download_calls = 0

    def synthesize(self, spec: TtsAttemptSpec, *, text: str) -> str:
        self.synthesis_calls += 1
        return f"fake-tts-{spec.input_fingerprint[:32]}"

    def download(self, spec: TtsAttemptSpec, *, provider_request_id: str) -> bytes:
        self.download_calls += 1
        return self._wav_bytes


def tts_identity_from_authorization(
    capability: TtsProviderCapability, authorization: TtsAuthorization
) -> TtsAdapterIdentity:
    return TtsAdapterIdentity(
        backend_id=capability.backend_id,
        provider_fingerprint=authorization.provider_fingerprint,
        model_fingerprint=authorization.model_fingerprint,
        account_fingerprint=authorization.account_fingerprint,
        endpoint_fingerprint=authorization.endpoint_fingerprint,
        auth_fingerprint=authorization.auth_fingerprint,
    )


def tts_attempt_record_path(workspace: str, spec: TtsAttemptSpec) -> Path:
    root = paths.workspace_root(workspace)
    return root / "logs" / "drama_tts" / f"episode_{spec.episode_no:03d}" / f"{spec.utterance_id}.attempt.json"


def _ensure_safe_parent(root: Path, path: Path) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError:
        raise DramaTtsAttemptStoreError("TTS path escaped workspace") from None
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        if current.exists() or current.is_symlink():
            try:
                info = current.lstat()
            except OSError:
                raise DramaTtsAttemptStoreError("TTS path is invalid") from None
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise DramaTtsAttemptStoreError("TTS path is invalid")
        else:
            current.mkdir()


def _open_parent_fd(root: Path, path: Path, *, create: bool) -> tuple[int, str]:
    try:
        relative = path.relative_to(root)
    except ValueError:
        raise DramaTtsAttemptStoreError("TTS path escaped workspace") from None
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    if not nofollow or not directory:
        raise DramaTtsAttemptStoreError("strict TTS storage is unavailable")
    current = os.open(str(root), os.O_RDONLY | directory | nofollow)
    try:
        for part in relative.parts[:-1]:
            try:
                next_fd = os.open(
                    part, os.O_RDONLY | directory | nofollow, dir_fd=current
                )
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, 0o700, dir_fd=current)
                os.fsync(current)
                next_fd = os.open(
                    part, os.O_RDONLY | directory | nofollow, dir_fd=current
                )
            os.close(current)
            current = next_fd
        return current, relative.name
    except BaseException:
        os.close(current)
        raise


def _target_token_at(parent_fd: int, name: str, *, maximum: int) -> tuple[Any, ...]:
    fd: int | None = None
    try:
        fd = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
            dir_fd=parent_fd,
        )
    except FileNotFoundError:
        return ("missing",)
    except OSError:
        return ("invalid",)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= maximum:
            return ("invalid",)
        remaining = maximum + 1
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) != info.st_size or len(data) > maximum:
            return ("invalid",)
        return ("file", len(data), hashlib.sha256(data).hexdigest())
    finally:
        os.close(fd)


def _durable_replace(
    root: Path,
    path: Path,
    data: bytes,
    *,
    maximum: int,
    expected_token: tuple[Any, ...] | None = None,
) -> None:
    parent_fd: int | None = None
    temp_name: str | None = None
    temp_fd: int | None = None
    try:
        parent_fd, name = _open_parent_fd(root, path, create=True)
        baseline = _target_token_at(parent_fd, name, maximum=maximum)
        if baseline == ("invalid",) or (
            expected_token is not None and baseline != expected_token
        ):
            raise DramaTtsAttemptStoreError("TTS storage target is invalid")
        temp_name = f".{name}.tmp.{secrets.token_hex(16)}"
        temp_fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_fd,
        )
        view = memoryview(data)
        while view:
            written = os.write(temp_fd, view)
            if written <= 0:
                raise OSError("short write")
            view = view[written:]
        os.fsync(temp_fd)
        os.close(temp_fd)
        temp_fd = None
        if _target_token_at(parent_fd, name, maximum=maximum) != baseline:
            raise DramaTtsAttemptStoreError("TTS storage target changed")
        os.replace(temp_name, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        temp_name = None
        os.fsync(parent_fd)
    except DramaTtsAttemptStoreError:
        raise
    except (OSError, ValueError):
        raise DramaTtsAttemptStoreError("TTS durable write failed") from None
    finally:
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except OSError:
                pass
        if parent_fd is not None and temp_name is not None:
            try:
                os.unlink(temp_name, dir_fd=parent_fd)
            except OSError:
                pass
        if parent_fd is not None:
            try:
                os.close(parent_fd)
            except OSError:
                pass


def _record_bytes(record: TtsAttemptRecord) -> bytes:
    envelope = {
        "schema_version": 1,
        "artifact_type": "drama_tts_attempt",
        "record_fingerprint": record.record_fingerprint,
        "record": model_to_dict(record),
    }
    return (
        json.dumps(envelope, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode()


def _write_record(
    workspace: str,
    record: TtsAttemptRecord,
    *,
    previous: TtsAttemptRecord | None,
) -> None:
    root = paths.workspace_root(workspace)
    path = tts_attempt_record_path(workspace, record.spec)
    data = _record_bytes(record)
    if len(data) > 250_000:
        raise DramaTtsAttemptStoreError("TTS attempt record exceeds its limit")
    expected = ("missing",)
    if previous is not None:
        previous_bytes = _record_bytes(previous)
        expected = (
            "file",
            len(previous_bytes),
            hashlib.sha256(previous_bytes).hexdigest(),
        )
    _durable_replace(
        root, path, data, maximum=250_000, expected_token=expected
    )


def _load_record(workspace: str, spec: TtsAttemptSpec) -> TtsAttemptRecord | None:
    root = paths.workspace_root(workspace)
    path = tts_attempt_record_path(workspace, spec)
    try:
        raw = _read_strict_workspace_json(root, path, maximum=250_000)
    except FileNotFoundError:
        return None
    except (OSError, RecursionError, TypeError, ValueError):
        raise DramaTtsAttemptStoreError("TTS attempt record is invalid") from None
    try:
        if not isinstance(raw, dict) or set(raw) != {
            "schema_version", "artifact_type", "record_fingerprint", "record"
        }:
            raise ValueError("bad envelope")
        if raw["schema_version"] != 1 or raw["artifact_type"] != "drama_tts_attempt":
            raise ValueError("bad envelope")
        record = TtsAttemptRecord(**raw["record"])
        if raw["record_fingerprint"] != record.record_fingerprint:
            raise ValueError("bad hash")
        if record.spec.input_fingerprint != spec.input_fingerprint:
            raise TtsAttemptReconciliationRequired("TTS input changed")
        return record
    except TtsAttemptReconciliationRequired:
        raise
    except (TypeError, ValueError):
        raise DramaTtsAttemptStoreError("TTS attempt record is invalid") from None


def _artifact_from_bytes(spec: TtsAttemptSpec, data: bytes) -> TtsAudioArtifact:
    try:
        probed = probe_mock_wav_fixture(data)
        if probed["sample_rate"] != spec.capability.sample_rate:
            raise ValueError("sample rate mismatch")
        payload: dict[str, Any] = {
            "schema_version": 1, "path": spec.output_path,
            "sha256": probed["sha256"], "size_bytes": probed["size_bytes"],
            "duration_milliseconds": probed["duration_milliseconds"],
            "sample_rate": probed["sample_rate"], "channels": probed["channels"],
        }
        payload["artifact_fingerprint"] = _canonical_sha256(payload)
        return TtsAudioArtifact(**payload)
    except (TypeError, ValueError):
        raise DramaTtsAttemptStoreError("TTS audio artifact was rejected") from None


def _artifact_path(workspace: str, spec: TtsAttemptSpec) -> Path:
    return paths.workspace_root(workspace) / spec.output_path


def _read_exact_artifact(workspace: str, record: TtsAttemptRecord) -> bytes | None:
    root = paths.workspace_root(workspace)
    path = _artifact_path(workspace, record.spec)
    try:
        data = _read_strict_workspace_bytes(root, path, maximum=3_000_000)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise DramaTtsAttemptStoreError("TTS audio artifact is invalid") from None
    artifact = _artifact_from_bytes(record.spec, data)
    if record.artifact is not None and artifact != record.artifact:
        raise DramaTtsAttemptStoreError("TTS audio artifact changed")
    return data


def _write_artifact(workspace: str, spec: TtsAttemptSpec, data: bytes) -> None:
    root = paths.workspace_root(workspace)
    path = _artifact_path(workspace, spec)
    _durable_replace(
        root,
        path,
        data,
        maximum=3_000_000,
        expected_token=("missing",),
    )


def _validate_adapter(adapter: TtsProviderAdapter, capability: TtsProviderCapability,
                      authorization: TtsAuthorization) -> None:
    try:
        identity = adapter.identity
    except Exception:
        raise DramaTtsAttemptStoreError("TTS adapter identity is unavailable") from None
    if identity != tts_identity_from_authorization(capability, authorization):
        raise TtsAttemptReconciliationRequired("TTS adapter identity changed")


def _validate_after_synthesis(
    workspace: str,
    record: TtsAttemptRecord,
    adapter: TtsProviderAdapter,
    capability: TtsProviderCapability,
    authorization: TtsAuthorization,
) -> None:
    try:
        _validate_adapter(adapter, capability, authorization)
    except TtsAttemptReconciliationRequired:
        unknown = mark_tts_submission_unknown(record)
        _write_record(workspace, unknown, previous=record)
        raise TtsAttemptReconciliationRequired(
            "TTS adapter identity changed during synthesis"
        ) from None


def run_tts_attempt(
    workspace: str, utterance: UtteranceSpec, *,
    capability: TtsProviderCapability, authorization: TtsAuthorization,
    adapter: TtsProviderAdapter,
    crash_hook: Callable[[str], None] | None = None,
) -> TtsAttemptRecord:
    """Run/resume one utterance. A durable provider id permits GET, never another POST."""

    hook = crash_hook or (lambda _phase: None)
    spec = build_tts_attempt_spec(utterance, capability, authorization)
    with use_workspace(workspace), acquire_write_lock(source="drama-tts-attempts"):
        root = paths.workspace_root(workspace)
        _validate_render_workspace_root(root)
        record = _load_record(workspace, spec)
        if record is not None and record.status == "succeeded":
            if _read_exact_artifact(workspace, record) is None:
                raise DramaTtsAttemptStoreError("succeeded TTS artifact is missing")
            return record
        if record is not None and record.status == "artifact_received":
            artifact_record = record
            data = _read_exact_artifact(workspace, record)
            if data is None:
                if record.submission is None or record.artifact is None:
                    raise DramaTtsAttemptStoreError("TTS artifact receipt is invalid")
                _validate_adapter(adapter, capability, authorization)
                try:
                    data = adapter.download(
                        spec,
                        provider_request_id=record.submission.provider_request_id,
                    )
                except Exception:
                    _validate_adapter(adapter, capability, authorization)
                    raise DramaTtsAttemptStoreError(
                        "TTS artifact download failed"
                    ) from None
                _validate_adapter(adapter, capability, authorization)
                if _artifact_from_bytes(spec, data) != record.artifact:
                    raise DramaTtsAttemptStoreError(
                        "TTS redownload differs from durable receipt"
                    )
                _write_artifact(workspace, spec, data)
            record = complete_tts_attempt(record)
            _write_record(workspace, record, previous=artifact_record)
            return record
        if record is not None and record.status == "provider_failed":
            return record
        _validate_adapter(adapter, capability, authorization)
        if record is not None and record.status in {"started", "submission_unknown"}:
            raise TtsAttemptReconciliationRequired(
                "TTS submission may have occurred; automatic synthesis is blocked"
            )
        if record is None or record.status == "not_sent":
            artifact_target = _artifact_path(workspace, spec)
            if artifact_target.exists() or artifact_target.is_symlink():
                raise DramaTtsAttemptStoreError(
                    "TTS audio target exists without a submitted receipt"
                )
            previous_record = record
            record = start_tts_attempt(spec)
            _write_record(workspace, record, previous=previous_record)
            hook("after_started_before_submit")
            try:
                _validate_adapter(adapter, capability, authorization)
                provider_request_id = adapter.synthesize(spec, text=utterance.text)
                _validate_adapter(adapter, capability, authorization)
                hook("after_submit_before_receipt")
            except RequestNotSentError:
                _validate_after_synthesis(
                    workspace, record, adapter, capability, authorization
                )
                started_record = record
                record = mark_tts_not_sent(record)
                _write_record(workspace, record, previous=started_record)
                return record
            except TtsSubmissionUnknownError:
                _validate_after_synthesis(
                    workspace, record, adapter, capability, authorization
                )
                started_record = record
                record = mark_tts_submission_unknown(record)
                _write_record(workspace, record, previous=started_record)
                raise TtsAttemptReconciliationRequired(
                    "TTS submission result is unknown"
                ) from None
            except TtsProviderTerminalError as exc:
                _validate_after_synthesis(
                    workspace, record, adapter, capability, authorization
                )
                started_record = record
                record = record_tts_provider_failed(
                    record, exc.provider_request_id
                )
                _write_record(workspace, record, previous=started_record)
                return record
            except Exception:
                _validate_after_synthesis(
                    workspace, record, adapter, capability, authorization
                )
                started_record = record
                record = mark_tts_submission_unknown(record)
                _write_record(workspace, record, previous=started_record)
                raise TtsAttemptReconciliationRequired(
                    "TTS submission result is unknown"
                ) from None
            started_record = record
            record = record_tts_submission(record, provider_request_id)
            _write_record(workspace, record, previous=started_record)
            hook("after_submission_receipt")
        if record.status != "submitted" or record.submission is None:
            raise TtsAttemptReconciliationRequired("TTS attempt cannot be resumed")

        if _read_exact_artifact(workspace, record) is not None:
            raise DramaTtsAttemptStoreError(
                "TTS audio target exists without a durable artifact receipt"
            )
        try:
            _validate_adapter(adapter, capability, authorization)
            data = adapter.download(
                spec,
                provider_request_id=record.submission.provider_request_id,
            )
            _validate_adapter(adapter, capability, authorization)
            hook("during_download_after_bytes")
            artifact = _artifact_from_bytes(spec, data)
        except DramaTtsAttemptStoreError:
            raise
        except Exception:
            _validate_adapter(adapter, capability, authorization)
            raise DramaTtsAttemptStoreError("TTS artifact download failed") from None
        submitted_record = record
        record = record_tts_artifact(record, artifact)
        _write_record(workspace, record, previous=submitted_record)
        hook("after_artifact_receipt_before_write")
        _write_artifact(workspace, spec, data)
        hook("after_artifact_write")
        artifact_record = record
        record = complete_tts_attempt(record)
        _write_record(workspace, record, previous=artifact_record)
        return record

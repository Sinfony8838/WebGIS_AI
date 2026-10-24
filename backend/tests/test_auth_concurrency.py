"""Deterministic authentication races against temporary SQLite databases."""
from __future__ import annotations

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Condition, Event
from types import SimpleNamespace

import pytest

from backend.app.services import auth
from backend.app.services.login_limits import LoginLimited, LoginLimits
from backend.app.services.password_work import PasswordWork, SessionReadPool, WorkBusy


PASSWORD = "Fixture-Password-2026!"
EMAIL = "teacher@example.invalid"


class FixtureHasher:
    def __init__(self, **kwargs):
        pass

    def hash(self, password):
        return "fixture:" + password

    def verify(self, password_hash, password):
        return password_hash == self.hash(password)


class PausedHasher(FixtureHasher):
    def __init__(self, operation="verify", password=None):
        self.operation = operation
        self.password = password
        self.release = Event()
        self.condition = Condition()
        self.entered = 0

    def pause(self, operation, password):
        if operation == self.operation and (self.password is None or self.password == password):
            with self.condition:
                self.entered += 1
                self.condition.notify_all()
            if not self.release.wait(10):
                raise AssertionError("Test did not release paused password work")

    def wait(self, count=1):
        with self.condition:
            assert self.condition.wait_for(lambda: self.entered >= count, timeout=5)

    def hash(self, password):
        self.pause("hash", password)
        return "fixture:" + password

    def verify(self, password_hash, password):
        self.pause("verify", password)
        return password_hash == "fixture:" + password


@pytest.fixture
def identities(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "PasswordHasher", FixtureHasher)
    service = auth.AuthService(tmp_path / "auth.db")
    admin = service.bootstrap("admin@example.invalid", "Admin", PASSWORD)
    service.register_open(EMAIL, "Teacher", PASSWORD)
    teacher = service.login(EMAIL, PASSWORD)
    peer = auth.AuthService(service.db_path)
    value = SimpleNamespace(service=service, peer=peer, admin=admin, teacher=teacher,
                            user_id=teacher["user"]["user_id"])
    try:
        yield value
    finally:
        service.close()
        peer.close()


def user_row(fixture):
    return fixture.service._user_snapshot(fixture.user_id)


def session_count(service):
    with service._connect() as connection:
        return connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]


def login_error(service, email=EMAIL, password="incorrect", **kwargs):
    try:
        service.login(email, password, **kwargs)
    except auth.AuthError as exc:
        return exc
    raise AssertionError("Login unexpectedly succeeded")


@pytest.mark.parametrize("operation,phase", [
    ("login", "verify"), ("change", "verify"), ("change", "hash"),
    ("reset", "hash"), ("create", "hash"), ("register", "hash"),
    ("request", "hash"), ("bootstrap", "hash"),
])
def test_all_password_paths_release_service_and_database_locks(identities, tmp_path, operation, phase):
    fixture = identities
    service = fixture.service if operation != "bootstrap" else auth.AuthService(tmp_path / "fresh.db")
    gate = PausedHasher(phase)
    service._password_hasher = gate
    actions = {
        "login": lambda: service.login(EMAIL, PASSWORD),
        "change": lambda: service.change_password(fixture.user_id, PASSWORD, "Changed-2026!",
                                                  current_session_id=fixture.teacher["session_id"]),
        "reset": lambda: service.reset_password(fixture.user_id, actor_user_id=fixture.admin["user"]["user_id"]),
        "create": lambda: service.create_user(email="created@example.invalid", nickname="Created",
                                               actor_user_id=fixture.admin["user"]["user_id"]),
        "register": lambda: service.register_open("opened@example.invalid", "Opened", PASSWORD),
        "request": lambda: service.submit_registration("pending@example.invalid", "Pending", PASSWORD),
        "bootstrap": lambda: service.bootstrap("first@example.invalid", "First", PASSWORD),
    }
    with ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(actions[operation])
        try:
            gate.wait()
            assert service._lock.acquire(blocking=False), "Hash holds the global authentication lock"
            service._lock.release()
            connection = sqlite3.connect(service.db_path, timeout=0.1)
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.rollback()
            finally:
                connection.close()
            if operation != "bootstrap":
                assert service.authenticate(fixture.admin["session_token"]) is not None
        finally:
            gate.release.set()
        future.result(timeout=5)
    if operation == "bootstrap":
        service.close()


@pytest.mark.parametrize("mutation", ["reset", "disable", "disable-enable", "email", "email-restore", "role", "role-restore", "revoke-all"])
def test_identity_changes_fence_inflight_login_across_service_instances(identities, mutation):
    fixture = identities
    gate = PausedHasher()
    fixture.service._password_hasher = gate
    before = session_count(fixture.service)
    actor = fixture.admin["user"]["user_id"]
    with ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(login_error, fixture.service, EMAIL, PASSWORD)
        try:
            gate.wait()
            if mutation == "reset":
                fixture.peer.reset_password(fixture.user_id, actor_user_id=actor)
            elif mutation == "revoke-all":
                fixture.peer.revoke_user_sessions(fixture.user_id, actor_user_id=actor)
            else:
                field, value, original = {
                    "disable": ("status", "disabled", "active"),
                    "email": ("email", "changed@example.invalid", EMAIL),
                    "role": ("role", "admin", "teacher"),
                }[mutation.split("-")[0]]
                fixture.peer.update_user(fixture.user_id, {field: value}, actor_user_id=actor)
                if "-" in mutation:
                    fixture.peer.update_user(fixture.user_id, {field: original}, actor_user_id=actor)
        finally:
            gate.release.set()
        error = future.result(timeout=5)
    assert error.code == "INVALID_CREDENTIALS"
    assert error.status_code == 401
    assert error.detail() == {"code": "INVALID_CREDENTIALS", "message": "邮箱或密码错误。"}
    assert session_count(fixture.service) == before
    assert user_row(fixture)["auth_version"] >= 1
    assert user_row(fixture)["failed_attempts"] == 0


def test_profile_only_edit_does_not_invalidate_password_snapshot(identities):
    fixture = identities
    gate = PausedHasher()
    fixture.service._password_hasher = gate
    with ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(fixture.service.login, EMAIL, PASSWORD)
        try:
            gate.wait()
            fixture.peer.update_user(fixture.user_id, {"nickname": "Corrected"}, actor_user_id=fixture.admin["user"]["user_id"])
        finally:
            gate.release.set()
        assert future.result(timeout=5)["user"]["nickname"] == "Corrected"
    assert user_row(fixture)["auth_version"] == 0


def test_concurrent_failures_use_latest_count_and_commit_rejection_audits(identities):
    fixture = identities
    gate = PausedHasher()
    fixture.service._password_hasher = fixture.peer._password_hasher = gate
    with ThreadPoolExecutor(max_workers=5) as workers:
        futures = [workers.submit(login_error, (fixture.service, fixture.peer)[index % 2]) for index in range(5)]
        try:
            gate.wait(2)
        finally:
            gate.release.set()
        assert [future.result(timeout=5).code for future in futures] == ["INVALID_CREDENTIALS"] * 5
    row = user_row(fixture)
    assert row["failed_attempts"] == 5
    assert auth.parse_iso(row["locked_until"]) > auth.utc_now()
    failures = [item for item in fixture.service.list_audit_logs() if item["action"] == "login" and item["outcome"] == "failed"]
    assert len(failures) == 5
    entered = gate.entered
    blocked = login_error(fixture.service, password=PASSWORD)
    assert blocked.code == "ACCOUNT_LOCKED"
    assert 1 <= blocked.retry_after <= 900
    assert gate.entered == entered, "Already-locked login must not hash again"


def test_correct_hash_cannot_override_a_concurrent_lockout(identities):
    fixture = identities
    gate = PausedHasher(password=PASSWORD)
    fixture.service._password_hasher = gate
    before = session_count(fixture.service)
    with ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(login_error, fixture.service, EMAIL, PASSWORD)
        try:
            gate.wait()
            for _ in range(5):
                assert login_error(fixture.peer).code == "INVALID_CREDENTIALS"
        finally:
            gate.release.set()
        assert future.result(timeout=5).code == "ACCOUNT_LOCKED"
    assert session_count(fixture.service) == before
    assert user_row(fixture)["failed_attempts"] == 5


def test_expired_lock_starts_a_new_failure_window(identities):
    with identities.service._connect() as connection:
        connection.execute("UPDATE users SET failed_attempts = 5, locked_until = ? WHERE user_id = ?",
                           (auth.iso(auth.utc_now() - timedelta(seconds=1)), identities.user_id))
    assert login_error(identities.service).code == "INVALID_CREDENTIALS"
    assert user_row(identities)["failed_attempts"] == 1
    assert user_row(identities)["locked_until"] == ""


@pytest.mark.parametrize("operation", ["change", "reset"])
def test_inflight_password_write_does_not_overwrite_newer_reset(identities, operation):
    fixture = identities
    gate = PausedHasher("hash")
    fixture.service._password_hasher = gate
    actor = fixture.admin["user"]["user_id"]
    action = (lambda: fixture.service.change_password(fixture.user_id, PASSWORD, "Old-Request-2026!",
                                                       current_session_id=fixture.teacher["session_id"])) if operation == "change" else (
        lambda: fixture.service.reset_password(fixture.user_id, actor_user_id=actor))
    with ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(action)
        try:
            gate.wait()
            latest = fixture.peer.reset_password(fixture.user_id, actor_user_id=actor)
        finally:
            gate.release.set()
        with pytest.raises(auth.AuthError) as caught:
            future.result(timeout=5)
    assert caught.value.code == "AUTH_STATE_CHANGED"
    assert user_row(fixture)["password_hash"] == "fixture:" + latest["temporary_password"]
    assert user_row(fixture)["auth_version"] == 1


def test_password_change_rechecks_its_session_after_verification(identities):
    fixture = identities
    gate = PausedHasher("hash")
    fixture.service._password_hasher = gate
    with ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(fixture.service.change_password, fixture.user_id, PASSWORD, "Changed-2026!",
                                current_session_id=fixture.teacher["session_id"])
        try:
            gate.wait()
            fixture.peer.logout(fixture.teacher["session_id"])
        finally:
            gate.release.set()
        with pytest.raises(auth.AuthError) as caught:
            future.result(timeout=5)
    assert caught.value.code == "AUTH_REQUIRED"
    assert user_row(fixture)["password_hash"] == "fixture:" + PASSWORD


def test_unknown_account_created_during_dummy_verification_still_fails(identities):
    fixture = identities
    gate = PausedHasher()
    fixture.service._password_hasher = gate
    with ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(login_error, fixture.service, "new@example.invalid", PASSWORD)
        try:
            gate.wait()
            fixture.peer.register_open("new@example.invalid", "New", PASSWORD)
        finally:
            gate.release.set()
        assert future.result(timeout=5).code == "INVALID_CREDENTIALS"


def test_audit_failure_rolls_back_failed_attempt(identities, monkeypatch):
    def fail_audit(*args, **kwargs):
        raise sqlite3.OperationalError("synthetic audit failure")
    monkeypatch.setattr(identities.service, "_audit", fail_audit)
    with pytest.raises(sqlite3.OperationalError, match="synthetic"):
        identities.service.login(EMAIL, "incorrect")
    assert user_row(identities)["failed_attempts"] == 0


def test_session_creation_failure_rolls_back_success_audit_and_counter_reset(identities, monkeypatch):
    fixture = identities
    assert login_error(fixture.service).code == "INVALID_CREDENTIALS"
    count = session_count(fixture.service)
    audits = fixture.service.list_audit_logs()
    def fail_session(*args, **kwargs):
        raise sqlite3.OperationalError("synthetic session failure")
    monkeypatch.setattr(fixture.service, "_create_session", fail_session)
    with pytest.raises(sqlite3.OperationalError, match="synthetic"):
        fixture.service.login(EMAIL, PASSWORD)
    assert user_row(fixture)["failed_attempts"] == 1
    assert session_count(fixture.service) == count
    assert fixture.service.list_audit_logs() == audits


def test_concurrent_successes_preserve_five_live_session_limit(identities):
    fixture = identities
    with ThreadPoolExecutor(max_workers=6) as workers:
        futures = [workers.submit((fixture.service, fixture.peer)[index % 2].login, EMAIL, PASSWORD) for index in range(6)]
        assert all(future.result(timeout=5)["user"]["user_id"] == fixture.user_id for future in futures)
    with fixture.service._connect() as connection:
        count = connection.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ? AND revoked_at = ''",
                                   (fixture.user_id,)).fetchone()[0]
    assert count == 5


def test_password_capacity_rejects_before_unbounded_queueing_and_recovers(identities):
    fixture = identities
    work = PasswordWork(2, 8)
    fixture.service._password_work = work
    gate = PausedHasher()
    fixture.service._password_hasher = gate
    with ThreadPoolExecutor(max_workers=10) as workers:
        futures = [workers.submit(login_error, fixture.service, f"unknown{index}@example.invalid") for index in range(10)]
        try:
            gate.wait(2)
            with work._condition:
                assert work._condition.wait_for(lambda: work._outstanding == 10, timeout=5)
                assert work._running == 2
            error = login_error(fixture.service, "overflow@example.invalid")
            assert error.code == "AUTH_BUSY"
            assert error.status_code == 429
            assert error.headers == {"Retry-After": "1"}
        finally:
            gate.release.set()
        assert all(future.result(timeout=5).code == "INVALID_CREDENTIALS" for future in futures)
    assert work._outstanding == work._running == 0
    assert fixture.service.login(EMAIL, PASSWORD)["user"]["user_id"] == fixture.user_id


def test_unknown_email_is_normalized_and_limited_before_hash(identities):
    service = identities.service
    service._login_limits = LoginLimits(account_limit=2)
    gate = PausedHasher()
    gate.release.set()
    service._password_hasher = gate
    assert login_error(service, " Unknown@Example.Invalid ").code == "INVALID_CREDENTIALS"
    assert login_error(service, "unknown@example.invalid").code == "INVALID_CREDENTIALS"
    rejected = login_error(service, "UNKNOWN@example.invalid")
    assert rejected.code == "RATE_LIMITED"
    assert rejected.status_code == 429 and rejected.retry_after > 0
    assert set(rejected.detail()) == {"code", "message"}
    assert gate.entered == 2


@pytest.mark.parametrize("limits,addresses", [
    ({"ip_limit": 2}, ["shared"] * 3),
    ({"global_limit": 2}, ["one", "two", "three"]),
])
def test_ip_and_global_limits_apply_to_rotating_unknown_accounts(identities, limits, addresses):
    service = identities.service
    service._login_limits = LoginLimits(**limits)
    errors = [login_error(service, f"unknown{index}@example.invalid", ip_address=ip) for index, ip in enumerate(addresses)]
    assert [error.code for error in errors] == ["INVALID_CREDENTIALS", "INVALID_CREDENTIALS", "RATE_LIMITED"]


def test_limit_storage_is_bounded_and_expires_without_evicting_live_limits():
    now = [0.0]
    limits = LoginLimits(account_limit=1, max_buckets=3, window_seconds=30, clock=lambda: now[0])
    limits.check("one@example.invalid", "shared")
    with pytest.raises(LoginLimited):
        limits.check("new@example.invalid", "shared")
    with pytest.raises(LoginLimited):
        limits.check("one@example.invalid", "shared")
    assert len(limits._buckets) == 3
    assert all("example.invalid" not in key for key in limits._buckets)
    now[0] = 31.0
    limits.check("new@example.invalid", "shared")
    assert len(limits._buckets) == 3


def test_authentication_async_uses_separate_capacity_from_paused_hashes(identities):
    fixture = identities
    gate = PausedHasher()
    fixture.service._password_hasher = gate
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(fixture.service.login, EMAIL, PASSWORD) for _ in range(2)]
        try:
            gate.wait(2)
            async def check():
                heartbeat = asyncio.create_task(asyncio.sleep(0))
                context = await asyncio.wait_for(fixture.service.authenticate_async(fixture.admin["session_token"]), timeout=1)
                await heartbeat
                assert context.user["role"] == "admin"
            asyncio.run(check())
        finally:
            gate.release.set()
        for future in futures:
            future.result(timeout=5)


def test_cancelled_async_reads_retain_capacity_until_real_work_finishes():
    pool = SessionReadPool(workers=1, max_waiting=1)
    entered, release = Event(), Event()
    def paused():
        entered.set()
        assert release.wait(5)
        return "done"
    async def check():
        first = asyncio.create_task(pool.run(paused))
        second = None
        try:
            while not entered.is_set():
                await asyncio.sleep(0)
            second = asyncio.create_task(pool.run(lambda: "queued"))
            await asyncio.sleep(0)
            second.cancel()
            with pytest.raises(asyncio.CancelledError):
                await second
            with pytest.raises(WorkBusy):
                await pool.run(lambda: "overflow")
        finally:
            release.set()
            await first
            await pool.aclose()
    asyncio.run(check())


def test_auth_version_migration_preserves_existing_password_and_session(identities):
    fixture = identities
    before = user_row(fixture)
    with fixture.service._connect() as connection:
        connection.execute("ALTER TABLE users DROP COLUMN auth_version")
    upgraded = auth.AuthService(fixture.service.db_path)
    try:
        after = upgraded._user_snapshot(fixture.user_id)
        assert after["auth_version"] == 0
        assert {key: after[key] for key in before} == before
        assert upgraded.authenticate(fixture.teacher["session_token"]) is not None
        assert "auth_version" not in upgraded.get_user(fixture.user_id)
    finally:
        upgraded.close()

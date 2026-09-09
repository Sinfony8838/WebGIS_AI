from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import string
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from argon2.low_level import Type


ALLOWED_ROLES = {"admin", "teacher"}
ALLOWED_STATUSES = {"active", "disabled"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AuthError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code

    def detail(self) -> Dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class AuthContext:
    user: Dict[str, Any]
    session_id: str
    csrf_hash: str


class AuthService:
    """Local teacher/admin identity store with revocable opaque sessions."""

    def __init__(
        self,
        db_path: Path,
        *,
        idle_minutes: int = 480,
        max_hours: int = 24,
    ) -> None:
        self.db_path = Path(db_path)
        self.idle_minutes = max(5, int(idle_minutes))
        self.max_hours = max(1, int(max_hours))
        self._lock = threading.RLock()
        self._password_hasher = PasswordHasher(
            time_cost=2,
            memory_cost=19_456,
            parallelism=1,
            hash_len=32,
            salt_len=16,
            type=Type.ID,
        )
        self._dummy_password_hash = self._password_hasher.hash(
            "GeoBot-dummy-password-2026"
        )
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    display_name TEXT NOT NULL,
                    email TEXT NOT NULL DEFAULT '',
                    role TEXT NOT NULL CHECK (role IN ('admin', 'teacher')),
                    status TEXT NOT NULL CHECK (status IN ('active', 'disabled')),
                    password_hash TEXT NOT NULL,
                    must_change_password INTEGER NOT NULL DEFAULT 0,
                    failed_attempts INTEGER NOT NULL DEFAULT 0,
                    locked_until TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    token_hash TEXT NOT NULL UNIQUE,
                    csrf_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    idle_expires_at TEXT NOT NULL,
                    absolute_expires_at TEXT NOT NULL,
                    revoked_at TEXT NOT NULL DEFAULT '',
                    ip_address TEXT NOT NULL DEFAULT '',
                    user_agent TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_user
                ON sessions(user_id);

                CREATE TABLE IF NOT EXISTS audit_logs (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor_user_id TEXT NOT NULL DEFAULT '',
                    action TEXT NOT NULL,
                    target_user_id TEXT NOT NULL DEFAULT '',
                    outcome TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    ip_address TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS auth_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_files (
                    path TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL
                );
                """
            )

    def has_users(self) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM users").fetchone()
        return bool(row and int(row["count"]) > 0)

    def bootstrap_owner_user_id(self) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM auth_settings WHERE key = 'bootstrap_owner_user_id'"
            ).fetchone()
        return str(row["value"]) if row else ""

    def bootstrap(
        self,
        email: str,
        nickname: str,
        password: str,
        *,
        ip_address: str = "",
        user_agent: str = "",
    ) -> Dict[str, Any]:
        normalized_email = self._validate_email(email)
        self._validate_password(password)
        now = iso(utc_now())
        user_id = f"user_{uuid4().hex}"
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            count = connection.execute("SELECT COUNT(*) AS count FROM users").fetchone()
            if count and int(count["count"]) > 0:
                raise AuthError("BOOTSTRAP_COMPLETE", "系统管理员已经初始化。", 409)
            connection.execute(
                """
                INSERT INTO users (
                    user_id, username, display_name, email, role, status,
                    password_hash, must_change_password, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'admin', 'active', ?, 0, ?, ?)
                """,
                (
                    user_id,
                    normalized_email,
                    self._clean_nickname(nickname, normalized_email),
                    normalized_email,
                    self._password_hasher.hash(password),
                    now,
                    now,
                ),
            )
            connection.execute(
                "INSERT OR REPLACE INTO auth_settings(key, value) VALUES('bootstrap_owner_user_id', ?)",
                (user_id,),
            )
            self._audit(
                connection,
                user_id,
                "bootstrap_admin",
                user_id,
                "success",
                ip_address=ip_address,
            )
            session = self._create_session(
                connection,
                user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            user = self._get_user_row(connection, user_id)
        return {"user": self._public_user(user), **session}

    def login(
        self,
        email: str,
        password: str,
        *,
        ip_address: str = "",
        user_agent: str = "",
    ) -> Dict[str, Any]:
        normalized = str(email or "").strip().lower()
        now_dt = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            user = connection.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
                (normalized,),
            ).fetchone()
            password_hash = str(user["password_hash"]) if user else self._dummy_password_hash
            verified = False
            try:
                verified = self._password_hasher.verify(password_hash, password or "")
            except (VerifyMismatchError, InvalidHashError):
                verified = False

            if user:
                locked_until = str(user["locked_until"] or "")
                if locked_until and parse_iso(locked_until) > now_dt:
                    self._audit(
                        connection,
                        "",
                        "login",
                        str(user["user_id"]),
                        "locked",
                        ip_address=ip_address,
                    )
                    connection.commit()
                    raise AuthError(
                        "ACCOUNT_LOCKED",
                        "登录尝试过多，请稍后再试。",
                        429,
                    )

            if not user or not verified:
                if user:
                    failures = int(user["failed_attempts"]) + 1
                    locked = iso(now_dt + timedelta(minutes=15)) if failures >= 5 else ""
                    connection.execute(
                        "UPDATE users SET failed_attempts = ?, locked_until = ?, updated_at = ? WHERE user_id = ?",
                        (failures, locked, iso(now_dt), user["user_id"]),
                    )
                self._audit(
                    connection,
                    "",
                    "login",
                    str(user["user_id"]) if user else "",
                    "failed",
                    ip_address=ip_address,
                )
                connection.commit()
                raise AuthError(
                    "INVALID_CREDENTIALS",
                    "邮箱或密码错误。",
                    401,
                )

            if str(user["status"]) != "active":
                self._audit(
                    connection,
                    str(user["user_id"]),
                    "login",
                    str(user["user_id"]),
                    "disabled",
                    ip_address=ip_address,
                )
                connection.commit()
                raise AuthError(
                    "INVALID_CREDENTIALS",
                    "邮箱或密码错误。",
                    401,
                )

            now = iso(now_dt)
            connection.execute(
                """
                UPDATE users
                SET failed_attempts = 0, locked_until = '', last_login_at = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (now, now, user["user_id"]),
            )
            self._audit(
                connection,
                str(user["user_id"]),
                "login",
                str(user["user_id"]),
                "success",
                ip_address=ip_address,
            )
            session = self._create_session(
                connection,
                str(user["user_id"]),
                ip_address=ip_address,
                user_agent=user_agent,
            )
            user = self._get_user_row(connection, str(user["user_id"]))
        return {"user": self._public_user(user), **session}

    def authenticate(self, session_token: str) -> Optional[AuthContext]:
        if not session_token:
            return None
        now_dt = utc_now()
        digest = token_hash(session_token)
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    s.session_id, s.csrf_hash, s.last_seen_at, s.idle_expires_at,
                    s.absolute_expires_at, s.revoked_at,
                    u.*
                FROM sessions s
                JOIN users u ON u.user_id = s.user_id
                WHERE s.token_hash = ?
                """,
                (digest,),
            ).fetchone()
            if not row:
                return None
            expired = (
                bool(row["revoked_at"])
                or str(row["status"]) != "active"
                or parse_iso(str(row["idle_expires_at"])) <= now_dt
                or parse_iso(str(row["absolute_expires_at"])) <= now_dt
            )
            if expired:
                if not row["revoked_at"]:
                    connection.execute(
                        "UPDATE sessions SET revoked_at = ? WHERE session_id = ?",
                        (iso(now_dt), row["session_id"]),
                    )
                return None
            last_seen = parse_iso(str(row["last_seen_at"]))
            if now_dt - last_seen >= timedelta(seconds=60):
                idle_expires = min(
                    now_dt + timedelta(minutes=self.idle_minutes),
                    parse_iso(str(row["absolute_expires_at"])),
                )
                connection.execute(
                    """
                    UPDATE sessions
                    SET last_seen_at = ?, idle_expires_at = ?
                    WHERE session_id = ?
                    """,
                    (iso(now_dt), iso(idle_expires), row["session_id"]),
                )
            return AuthContext(
                user=self._public_user(row),
                session_id=str(row["session_id"]),
                csrf_hash=str(row["csrf_hash"]),
            )

    def rotate_csrf(self, session_id: str) -> str:
        csrf_token = secrets.token_urlsafe(32)
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET csrf_hash = ? WHERE session_id = ? AND revoked_at = ''",
                (token_hash(csrf_token), session_id),
            )
        return csrf_token

    def csrf_for_session(self, context: AuthContext) -> str:
        """Recover a stable page token without rotating another tab's token.

        The stored hash of the random login CSRF token is a server-only,
        per-session HMAC key. Neither this key nor the session cookie is exposed.
        Keeping the original login token valid also preserves existing sessions.
        """
        if not context.session_id or not context.csrf_hash:
            return ""
        return hmac.new(
            bytes.fromhex(context.csrf_hash),
            ("webgis-csrf-page-v1:" + context.session_id).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def verify_csrf(self, context: AuthContext, supplied: str) -> bool:
        if not supplied or not context.session_id or not context.csrf_hash:
            return False
        digest = token_hash(supplied)
        return secrets.compare_digest(context.csrf_hash, digest) or secrets.compare_digest(
            token_hash(self.csrf_for_session(context)), digest,
        )

    def logout(self, session_id: str, *, actor_user_id: str = "", ip_address: str = "") -> None:
        now = iso(utc_now())
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET revoked_at = ? WHERE session_id = ? AND revoked_at = ''",
                (now, session_id),
            )
            self._audit(
                connection,
                actor_user_id,
                "logout",
                actor_user_id,
                "success",
                ip_address=ip_address,
            )

    def revoke_user_sessions(
        self,
        user_id: str,
        *,
        actor_user_id: str,
        keep_session_id: str = "",
        action: str = "revoke_sessions",
        ip_address: str = "",
    ) -> int:
        now = iso(utc_now())
        with self._lock, self._connect() as connection:
            if keep_session_id:
                cursor = connection.execute(
                    """
                    UPDATE sessions SET revoked_at = ?
                    WHERE user_id = ? AND session_id != ? AND revoked_at = ''
                    """,
                    (now, user_id, keep_session_id),
                )
            else:
                cursor = connection.execute(
                    "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at = ''",
                    (now, user_id),
                )
            self._audit(
                connection,
                actor_user_id,
                action,
                user_id,
                "success",
                detail=f"revoked={cursor.rowcount}",
                ip_address=ip_address,
            )
            return int(cursor.rowcount)

    def change_password(
        self,
        user_id: str,
        current_password: str,
        new_password: str,
        *,
        current_session_id: str,
        ip_address: str = "",
    ) -> Dict[str, Any]:
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            user = self._get_user_row(connection, user_id)
            try:
                valid = self._password_hasher.verify(
                    str(user["password_hash"]),
                    current_password or "",
                )
            except (VerifyMismatchError, InvalidHashError):
                valid = False
            if not valid:
                raise AuthError(
                    "INVALID_CURRENT_PASSWORD",
                    "当前密码不正确。",
                    400,
                )
            self._validate_password(new_password)
            now = iso(utc_now())
            connection.execute(
                """
                UPDATE users
                SET password_hash = ?, must_change_password = 0,
                    failed_attempts = 0, locked_until = '', updated_at = ?
                WHERE user_id = ?
                """,
                (self._password_hasher.hash(new_password), now, user_id),
            )
            connection.execute(
                """
                UPDATE sessions SET revoked_at = ?
                WHERE user_id = ? AND session_id != ? AND revoked_at = ''
                """,
                (now, user_id, current_session_id),
            )
            self._audit(
                connection,
                user_id,
                "change_password",
                user_id,
                "success",
                ip_address=ip_address,
            )
            return self._public_user(self._get_user_row(connection, user_id))

    def list_users(self, query: str = "", role: str = "", status: str = "") -> List[Dict[str, Any]]:
        sql = "SELECT * FROM users WHERE 1 = 1"
        params: List[Any] = []
        if query.strip():
            sql += " AND (display_name LIKE ? OR email LIKE ?)"
            needle = f"%{query.strip()}%"
            params.extend([needle, needle])
        if role in ALLOWED_ROLES:
            sql += " AND role = ?"
            params.append(role)
        if status in ALLOWED_STATUSES:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY CASE role WHEN 'admin' THEN 0 ELSE 1 END, created_at"
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
            result = []
            for row in rows:
                payload = self._public_user(row)
                count = connection.execute(
                    """
                    SELECT COUNT(*) AS count FROM sessions
                    WHERE user_id = ? AND revoked_at = ''
                    """,
                    (row["user_id"],),
                ).fetchone()
                payload["active_session_count"] = int(count["count"]) if count else 0
                result.append(payload)
        return result

    def create_user(
        self,
        *,
        actor_user_id: str,
        email: str,
        nickname: str,
        role: str = "teacher",
        ip_address: str = "",
    ) -> Dict[str, Any]:
        normalized_email = self._validate_email(email)
        self._validate_role(role)
        temporary_password = self._generate_temporary_password()
        now = iso(utc_now())
        user_id = f"user_{uuid4().hex}"
        try:
            with self._lock, self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO users (
                        user_id, username, display_name, email, role, status,
                        password_hash, must_change_password, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'active', ?, 1, ?, ?)
                    """,
                    (
                        user_id,
                        normalized_email,
                        self._clean_nickname(nickname, normalized_email),
                        normalized_email,
                        role,
                        self._password_hasher.hash(temporary_password),
                        now,
                        now,
                    ),
                )
                self._audit(
                    connection,
                    actor_user_id,
                    "create_user",
                    user_id,
                    "success",
                    detail=f"role={role}",
                    ip_address=ip_address,
                )
                user = self._public_user(self._get_user_row(connection, user_id))
        except sqlite3.IntegrityError as exc:
            raise AuthError("EMAIL_EXISTS", "该邮箱已存在。", 409) from exc
        return {"user": user, "temporary_password": temporary_password}

    def update_user(
        self,
        user_id: str,
        patch: Dict[str, Any],
        *,
        actor_user_id: str,
        ip_address: str = "",
    ) -> Dict[str, Any]:
        allowed = {"nickname", "email", "role", "status"}
        unknown = set(patch) - allowed
        if unknown:
            raise AuthError("INVALID_USER_PATCH", "包含不支持的用户字段。", 400)
        try:
            with self._lock, self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                current = self._get_user_row(connection, user_id)
                next_role = str(patch.get("role", current["role"]))
                next_status = str(patch.get("status", current["status"]))
                self._validate_role(next_role)
                self._validate_status(next_status)
                if (
                    str(current["role"]) == "admin"
                    and str(current["status"]) == "active"
                    and (next_role != "admin" or next_status != "active")
                    and self._active_admin_count(connection) <= 1
                ):
                    raise AuthError(
                        "LAST_ADMIN_REQUIRED",
                        "系统必须至少保留一个有效管理员。",
                        409,
                    )
                nickname = self._clean_nickname(
                    str(patch.get("nickname", current["display_name"])),
                    str(current["email"]),
                )
                email = self._validate_email(str(patch.get("email", current["email"])))
                now = iso(utc_now())
                connection.execute(
                    """
                    UPDATE users
                    SET username = ?, display_name = ?, email = ?, role = ?, status = ?, updated_at = ?
                    WHERE user_id = ?
                    """,
                    (email, nickname, email, next_role, next_status, now, user_id),
                )
                if (
                    next_status != "active"
                    or next_role != str(current["role"])
                    or email != str(current["email"])
                ):
                    connection.execute(
                        "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at = ''",
                        (now, user_id),
                    )
                self._audit(
                    connection,
                    actor_user_id,
                    "update_user",
                    user_id,
                    "success",
                    detail=f"role={next_role};status={next_status}",
                    ip_address=ip_address,
                )
                return self._public_user(self._get_user_row(connection, user_id))
        except sqlite3.IntegrityError as exc:
            raise AuthError("EMAIL_EXISTS", "该邮箱已存在。", 409) from exc

    def reset_password(
        self,
        user_id: str,
        *,
        actor_user_id: str,
        ip_address: str = "",
    ) -> Dict[str, Any]:
        temporary_password = self._generate_temporary_password()
        now = iso(utc_now())
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._get_user_row(connection, user_id)
            connection.execute(
                """
                UPDATE users
                SET password_hash = ?, must_change_password = 1,
                    failed_attempts = 0, locked_until = '', updated_at = ?
                WHERE user_id = ?
                """,
                (self._password_hasher.hash(temporary_password), now, user_id),
            )
            connection.execute(
                "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at = ''",
                (now, user_id),
            )
            self._audit(
                connection,
                actor_user_id,
                "reset_password",
                user_id,
                "success",
                ip_address=ip_address,
            )
            user = self._public_user(self._get_user_row(connection, user_id))
        return {"user": user, "temporary_password": temporary_password}

    def list_audit_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 500))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM audit_logs
                ORDER BY audit_id DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_user(self, user_id: str) -> Dict[str, Any]:
        with self._connect() as connection:
            return self._public_user(self._get_user_row(connection, user_id))

    def grant_file(self, user_id: str, path: Path) -> None:
        resolved = str(Path(path).resolve())
        with self._lock, self._connect() as connection:
            self._get_user_row(connection, user_id)
            connection.execute(
                """
                INSERT INTO user_files(path, user_id, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET user_id = excluded.user_id
                """,
                (resolved, user_id, iso(utc_now())),
            )

    def can_access_file(self, user_id: str, path: Path) -> bool:
        resolved = str(Path(path).resolve())
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM user_files WHERE path = ? AND user_id = ?",
                (resolved, user_id),
            ).fetchone()
        return row is not None

    def _create_session(
        self,
        connection: sqlite3.Connection,
        user_id: str,
        *,
        ip_address: str,
        user_agent: str,
    ) -> Dict[str, str]:
        now_dt = utc_now()
        session_token = secrets.token_urlsafe(48)
        csrf_token = secrets.token_urlsafe(32)
        session_id = f"session_{uuid4().hex}"
        absolute = now_dt + timedelta(hours=self.max_hours)
        idle = min(now_dt + timedelta(minutes=self.idle_minutes), absolute)
        connection.execute(
            """
            INSERT INTO sessions (
                session_id, user_id, token_hash, csrf_hash, created_at,
                last_seen_at, idle_expires_at, absolute_expires_at,
                ip_address, user_agent
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                user_id,
                token_hash(session_token),
                token_hash(csrf_token),
                iso(now_dt),
                iso(now_dt),
                iso(idle),
                iso(absolute),
                ip_address[:128],
                user_agent[:512],
            ),
        )
        # Keep at most five live sessions per account.
        stale = connection.execute(
            """
            SELECT session_id FROM sessions
            WHERE user_id = ? AND revoked_at = ''
            ORDER BY created_at DESC
            LIMIT -1 OFFSET 5
            """,
            (user_id,),
        ).fetchall()
        for row in stale:
            connection.execute(
                "UPDATE sessions SET revoked_at = ? WHERE session_id = ?",
                (iso(now_dt), row["session_id"]),
            )
        return {
            "session_token": session_token,
            "csrf_token": csrf_token,
            "session_id": session_id,
            "expires_at": iso(absolute),
        }

    @staticmethod
    def _public_user(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "user_id": str(row["user_id"]),
            "email": str(row["username"]),
            "nickname": str(row["display_name"]),
            "role": str(row["role"]),
            "status": str(row["status"]),
            "must_change_password": bool(row["must_change_password"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "last_login_at": str(row["last_login_at"] or ""),
            "locked_until": str(row["locked_until"] or ""),
        }

    @staticmethod
    def _get_user_row(connection: sqlite3.Connection, user_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            raise AuthError("USER_NOT_FOUND", "用户不存在。", 404)
        return row

    @staticmethod
    def _active_admin_count(connection: sqlite3.Connection) -> int:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM users WHERE role = 'admin' AND status = 'active'"
        ).fetchone()
        return int(row["count"]) if row else 0

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        actor_user_id: str,
        action: str,
        target_user_id: str,
        outcome: str,
        *,
        detail: str = "",
        ip_address: str = "",
    ) -> None:
        connection.execute(
            """
            INSERT INTO audit_logs (
                actor_user_id, action, target_user_id, outcome,
                detail, ip_address, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                actor_user_id,
                action,
                target_user_id,
                outcome,
                detail[:1000],
                ip_address[:128],
                iso(utc_now()),
            ),
        )

    @staticmethod
    def _clean_nickname(nickname: str, fallback: str) -> str:
        value = str(nickname or "").strip() or fallback.split("@", 1)[0]
        if len(value) > 80:
            raise AuthError("INVALID_NICKNAME", "昵称不能超过 80 个字符。", 400)
        return value

    @staticmethod
    def _validate_email(email: str) -> str:
        value = str(email or "").strip().lower()
        local, separator, domain = value.rpartition("@")
        if (
            not separator
            or not local
            or "." not in domain
            or domain.startswith(".")
            or domain.endswith(".")
            or any(ch.isspace() for ch in value)
            or len(value) > 254
        ):
            raise AuthError("INVALID_EMAIL", "邮箱格式不正确。", 400)
        return value

    @staticmethod
    def _validate_role(role: str) -> None:
        if role not in ALLOWED_ROLES:
            raise AuthError("INVALID_ROLE", "角色只能是管理员或教师。", 400)

    @staticmethod
    def _validate_status(status: str) -> None:
        if status not in ALLOWED_STATUSES:
            raise AuthError("INVALID_STATUS", "用户状态不正确。", 400)

    @staticmethod
    def _validate_password(password: str) -> None:
        value = str(password or "")
        if len(value) < 8 or len(value) > 128:
            raise AuthError(
                "WEAK_PASSWORD",
                "密码长度须为 8–128 位。",
                400,
            )
        categories = sum(
            (
                any(ch.isalpha() for ch in value),
                any(ch.isdigit() for ch in value),
                any(not ch.isalnum() and not ch.isspace() for ch in value),
            )
        )
        if categories < 2:
            raise AuthError(
                "WEAK_PASSWORD",
                "密码须包含字母、数字、特殊符号中的至少两种。",
                400,
            )

    @staticmethod
    def _generate_temporary_password() -> str:
        alphabet = string.ascii_letters + string.digits + "!@#$%*-_"
        while True:
            value = "".join(secrets.choice(alphabet) for _ in range(18))
            if (
                any(ch.islower() for ch in value)
                and any(ch.isupper() for ch in value)
                and any(ch.isdigit() for ch in value)
                and any(not ch.isalnum() for ch in value)
            ):
                return value

import { useEffect, useRef, useState } from "react";
import { changePassword, logoutUser } from "../api";
import type { AuthUser } from "../types";
import { PasswordChangeCard } from "./AuthGate";
import { UserManagementPanel } from "./UserManagementPanel";

export function UserMenu({
  user,
  onLogout,
  onUserChanged
}: {
  user: AuthUser;
  onLogout: () => void;
  onUserChanged: (user: AuthUser) => void;
}) {
  const [open, setOpen] = useState(false);
  const [adminOpen, setAdminOpen] = useState(false);
  const [changeOpen, setChangeOpen] = useState(false);
  const [error, setError] = useState("");
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const close = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, []);

  return (
    <>
      <div className="user-menu" ref={rootRef}>
        <button
          type="button"
          className="user-menu-trigger"
          aria-haspopup="menu"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          <span className="user-avatar">{(user.display_name || user.username).slice(0, 1)}</span>
          <span className="user-menu-label">
            <strong>{user.display_name || user.username}</strong>
            <small>{user.role === "admin" ? "管理员" : "教师"}</small>
          </span>
          <span aria-hidden="true">⌄</span>
        </button>
        {open ? (
          <div className="user-menu-popover" role="menu">
            <div className="user-menu-profile">
              <strong>{user.display_name || user.username}</strong>
              <span>@{user.username}</span>
              {user.email ? <span>{user.email}</span> : null}
            </div>
            {user.role === "admin" ? (
              <button type="button" role="menuitem" onClick={() => { setOpen(false); setAdminOpen(true); }}>
                用户管理
              </button>
            ) : null}
            <button type="button" role="menuitem" onClick={() => { setOpen(false); setChangeOpen(true); }}>
              修改密码
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                void logoutUser().catch(() => undefined).finally(onLogout);
              }}
            >
              退出登录
            </button>
          </div>
        ) : null}
      </div>
      {changeOpen ? (
        <PasswordChangeCard
          error={error}
          onCancel={() => { setError(""); setChangeOpen(false); }}
          onSubmit={async (currentPassword, newPassword) => {
            setError("");
            try {
              const result = await changePassword(currentPassword, newPassword);
              onUserChanged(result.user);
              setChangeOpen(false);
            } catch (reason) {
              setError(reason instanceof Error ? reason.message : "密码修改失败");
            }
          }}
        />
      ) : null}
      {adminOpen && user.role === "admin" ? (
        <UserManagementPanel
          currentUser={user}
          onClose={() => setAdminOpen(false)}
        />
      ) : null}
    </>
  );
}

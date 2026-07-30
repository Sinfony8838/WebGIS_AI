import { useCallback, useEffect, useState } from "react";
import {
  createAdminUser,
  fetchAdminUsers,
  fetchAuditLogs,
  resetAdminUserPassword,
  revokeAdminUserSessions,
  updateAdminUser
} from "../api";
import type { AuthAuditLog, AuthUser, UserRole, UserStatus } from "../types";

export function UserManagementPanel({ currentUser, onClose }: {
  currentUser: AuthUser;
  onClose: () => void;
}) {
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [logs, setLogs] = useState<AuthAuditLog[]>([]);
  const [tab, setTab] = useState<"users" | "audit">("users");
  const [query, setQuery] = useState("");
  const [role, setRole] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [temporaryPassword, setTemporaryPassword] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [editingUser, setEditingUser] = useState<AuthUser | null>(null);

  const loadUsers = useCallback(async () => {
    try {
      const response = await fetchAdminUsers({ query, role, status });
      setUsers(response.items);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "用户列表加载失败");
    }
  }, [query, role, status]);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  useEffect(() => {
    if (tab === "audit") {
      void fetchAuditLogs().then((response) => setLogs(response.items)).catch((reason) => {
        setError(reason instanceof Error ? reason.message : "审计日志加载失败");
      });
    }
  }, [tab]);

  const run = async (action: () => Promise<unknown>) => {
    setError("");
    try {
      await action();
      await loadUsers();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "操作失败");
    }
  };

  return (
    <div className="auth-modal-backdrop">
      <section className="admin-panel" role="dialog" aria-modal="true" aria-labelledby="admin-title">
        <header>
          <div>
            <p className="auth-eyebrow">系统管理</p>
            <h2 id="admin-title">教师账号与登录审计</h2>
          </div>
          <button type="button" className="admin-close" onClick={onClose} aria-label="关闭">×</button>
        </header>
        <nav className="admin-tabs" aria-label="管理功能">
          <button type="button" className={tab === "users" ? "active" : ""} onClick={() => setTab("users")}>用户</button>
          <button type="button" className={tab === "audit" ? "active" : ""} onClick={() => setTab("audit")}>登录审计</button>
        </nav>
        {error ? <p className="auth-error" role="alert">{error}</p> : null}
        {temporaryPassword ? (
          <div className="temporary-password" role="status">
            <div>
              <strong>一次性临时密码</strong>
              <span>关闭后不会再次显示，请立即安全交给该教师。</span>
            </div>
            <code>{temporaryPassword}</code>
            <button type="button" onClick={() => setTemporaryPassword("")}>已保存</button>
          </div>
        ) : null}
        {tab === "users" ? (
          <>
            <div className="admin-toolbar">
              <input aria-label="搜索用户" placeholder="搜索邮箱或昵称" value={query} onChange={(e) => setQuery(e.target.value)} />
              <select aria-label="筛选角色" value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="">全部角色</option>
                <option value="teacher">教师</option>
                <option value="admin">管理员</option>
              </select>
              <select aria-label="筛选状态" value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="">全部状态</option>
                <option value="active">已启用</option>
                <option value="disabled">已停用</option>
              </select>
              <button type="button" className="auth-primary" onClick={() => setShowCreate(true)}>创建账号</button>
            </div>
            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead><tr><th>用户</th><th>角色</th><th>状态</th><th>会话</th><th>操作</th></tr></thead>
                <tbody>
                  {users.map((item) => (
                    <tr key={item.user_id}>
                      <td><strong>{item.nickname || item.email}</strong><span>{item.email}</span></td>
                      <td>
                        <select
                          aria-label={`修改 ${item.email} 角色`}
                          value={item.role}
                          onChange={(e) => void run(() => updateAdminUser(item.user_id, { role: e.target.value as UserRole }))}
                        >
                          <option value="teacher">教师</option>
                          <option value="admin">管理员</option>
                        </select>
                      </td>
                      <td>
                        <button
                          type="button"
                          className={`status-chip ${item.status}`}
                          disabled={item.user_id === currentUser.user_id}
                          onClick={() => void run(() => updateAdminUser(item.user_id, {
                            status: (item.status === "active" ? "disabled" : "active") as UserStatus
                          }))}
                        >
                          {item.status === "active" ? "已启用" : "已停用"}
                        </button>
                      </td>
                      <td>{item.active_session_count || 0}</td>
                      <td className="admin-row-actions">
                        <button type="button" onClick={() => setEditingUser(item)}>编辑资料</button>
                        <button type="button" onClick={() => void run(async () => {
                          const result = await resetAdminUserPassword(item.user_id);
                          setTemporaryPassword(result.temporary_password);
                        })}>重置密码</button>
                        <button type="button" onClick={() => void run(() => revokeAdminUserSessions(item.user_id))}>撤销会话</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead><tr><th>时间</th><th>动作</th><th>结果</th><th>对象</th><th>来源</th></tr></thead>
              <tbody>
                {logs.map((log) => (
                  <tr key={log.audit_id}>
                    <td>{new Date(log.created_at).toLocaleString()}</td>
                    <td>{log.action}</td>
                    <td>{log.outcome}</td>
                    <td>{log.target_user_id || "—"}</td>
                    <td>{log.ip_address || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {showCreate ? (
          <CreateUserForm
            onCancel={() => setShowCreate(false)}
            onCreate={async (payload) => {
              await run(async () => {
                const result = await createAdminUser(payload);
                setTemporaryPassword(result.temporary_password);
                setShowCreate(false);
              });
            }}
          />
        ) : null}
        {editingUser ? (
          <EditUserForm
            user={editingUser}
            onCancel={() => setEditingUser(null)}
            onSave={async (patch) => {
              await run(() => updateAdminUser(editingUser.user_id, patch));
              setEditingUser(null);
            }}
          />
        ) : null}
      </section>
    </div>
  );
}

function EditUserForm({ user, onCancel, onSave }: {
  user: AuthUser;
  onCancel: () => void;
  onSave: (patch: Pick<AuthUser, "nickname" | "email">) => Promise<void>;
}) {
  const [nickname, setNickname] = useState(user.nickname);
  const [email, setEmail] = useState(user.email);
  return (
    <div className="admin-subdialog">
      <form onSubmit={(event) => { event.preventDefault(); void onSave({ nickname, email }); }}>
        <h3>编辑账号资料</h3>
        <p className="auth-hint">{user.email}</p>
        <label className="auth-field"><span>昵称</span><input value={nickname} onChange={(e) => setNickname(e.target.value)} required /></label>
        <label className="auth-field"><span>邮箱</span><input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
        <div className="auth-actions"><button type="button" onClick={onCancel}>取消</button><button className="auth-primary" type="submit">保存资料</button></div>
      </form>
    </div>
  );
}

function CreateUserForm({ onCancel, onCreate }: {
  onCancel: () => void;
  onCreate: (payload: { email: string; nickname: string; role: UserRole }) => Promise<void>;
}) {
  const [email, setEmail] = useState("");
  const [nickname, setNickname] = useState("");
  const [role, setRole] = useState<UserRole>("teacher");
  return (
    <div className="admin-subdialog">
      <form onSubmit={(event) => { event.preventDefault(); void onCreate({ email, nickname, role }); }}>
        <h3>创建教师或管理员</h3>
        <label className="auth-field"><span>邮箱</span><input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
        <label className="auth-field"><span>昵称</span><input value={nickname} onChange={(e) => setNickname(e.target.value)} required /></label>
        <label className="auth-field"><span>角色</span><select value={role} onChange={(e) => setRole(e.target.value as UserRole)}><option value="teacher">教师</option><option value="admin">管理员</option></select></label>
        <div className="auth-actions"><button type="button" onClick={onCancel}>取消</button><button className="auth-primary" type="submit">创建账号</button></div>
      </form>
    </div>
  );
}

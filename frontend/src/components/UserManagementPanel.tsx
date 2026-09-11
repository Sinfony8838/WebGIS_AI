import { useCallback, useEffect, useState } from "react";
import {
  createAdminUser,
  fetchAdminUsers,
  fetchAuditLogs,
  fetchRegistrationRequests,
  resetAdminUserPassword,
  reviewRegistrationRequest,
  revokeAdminUserSessions,
  updateAdminUser
} from "../api";
import type {
  AuthAuditLog,
  AuthUser,
  RegistrationRequest,
  RegistrationRequestStatus,
  UserRole,
  UserStatus
} from "../types";

type AdminTab = "users" | "registrations" | "audit";

export function UserManagementPanel({ currentUser, onClose }: {
  currentUser: AuthUser;
  onClose: () => void;
}) {
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [logs, setLogs] = useState<AuthAuditLog[]>([]);
  const [tab, setTab] = useState<AdminTab>("users");
  const [query, setQuery] = useState("");
  const [role, setRole] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [temporaryPassword, setTemporaryPassword] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [editingUser, setEditingUser] = useState<AuthUser | null>(null);
  const [pendingRegistrations, setPendingRegistrations] = useState(0);

  const loadUsers = useCallback(async () => {
    try {
      const response = await fetchAdminUsers({ query, role, status });
      setUsers(response.items);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "用户列表加载失败");
    }
  }, [query, role, status]);

  const loadPendingCount = useCallback(async () => {
    try {
      const response = await fetchRegistrationRequests({ status: "pending" });
      setPendingRegistrations(response.pending_count);
    } catch {
      // The badge is advisory; the registrations tab shows its own errors.
    }
  }, []);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  useEffect(() => {
    void loadPendingCount();
  }, [loadPendingCount]);

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
          <button type="button" className={tab === "registrations" ? "active" : ""} onClick={() => setTab("registrations")}>
            注册申请{pendingRegistrations > 0 ? <span className="admin-badge" aria-label={`${pendingRegistrations} 条待审核`}>{pendingRegistrations}</span> : null}
          </button>
          <button type="button" className={tab === "audit" ? "active" : ""} onClick={() => setTab("audit")}>安全审计</button>
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
        ) : tab === "registrations" ? (
          <RegistrationRequestsTab
            onChanged={() => {
              void loadUsers();
              void loadPendingCount();
            }}
          />
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

const REGISTRATION_STATUS_LABELS: Record<RegistrationRequestStatus, string> = {
  pending: "待审核",
  approved: "已批准",
  rejected: "已拒绝"
};

function RegistrationRequestsTab({ onChanged }: { onChanged: () => void }) {
  const [requests, setRequests] = useState<RegistrationRequest[]>([]);
  const [pendingCount, setPendingCount] = useState(0);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<RegistrationRequestStatus | "">("");
  const [error, setError] = useState("");
  const [busyRequestId, setBusyRequestId] = useState("");
  const [notice, setNotice] = useState("");

  const loadRequests = useCallback(async () => {
    try {
      const response = await fetchRegistrationRequests({ query, status: statusFilter });
      setRequests(response.items);
      setPendingCount(response.pending_count);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "注册申请加载失败");
    }
  }, [query, statusFilter]);

  useEffect(() => {
    void loadRequests();
  }, [loadRequests]);

  const review = async (request: RegistrationRequest, decision: "approved" | "rejected") => {
    const confirmed = window.confirm(
      decision === "approved"
        ? `确认批准 ${request.email} 的注册申请？批准后将创建教师账号。`
        : `确认拒绝 ${request.email} 的注册申请？`
    );
    if (!confirmed) return;
    setError("");
    setNotice("");
    setBusyRequestId(request.request_id);
    try {
      await reviewRegistrationRequest(request.request_id, decision);
      setNotice(
        decision === "approved"
          ? `已批准 ${request.email}，教师账号已创建。`
          : `已拒绝 ${request.email} 的注册申请。`
      );
      await loadRequests();
      onChanged();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "审核操作失败");
      await loadRequests();
    } finally {
      setBusyRequestId("");
    }
  };

  return (
    <>
      <div className="admin-toolbar admin-toolbar-registrations">
        <input
          aria-label="搜索注册申请"
          placeholder="搜索邮箱、昵称或学校"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select
          aria-label="筛选申请状态"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as RegistrationRequestStatus | "")}
        >
          <option value="">全部申请</option>
          <option value="pending">待审核</option>
          <option value="approved">已批准</option>
          <option value="rejected">已拒绝</option>
        </select>
        <span className="admin-pending-hint" role="status">
          {pendingCount > 0 ? `${pendingCount} 条待审核` : "暂无待审核申请"}
        </span>
      </div>
      {notice ? <p className="auth-success admin-notice" role="status">{notice}</p> : null}
      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr><th>申请人</th><th>学校/机构</th><th>申请说明</th><th>申请时间</th><th>状态</th><th>操作</th></tr>
          </thead>
          <tbody>
            {requests.map((item) => (
              <tr key={item.request_id}>
                <td>
                  <strong>{item.display_name || item.email}</strong>
                  <span>{item.email}</span>
                </td>
                <td>{item.organization || "—"}</td>
                <td className="admin-note-cell" title={item.application_note}>
                  {item.application_note || "—"}
                </td>
                <td>{new Date(item.created_at).toLocaleString()}</td>
                <td>
                  <span className={`status-chip reg-${item.status}`}>
                    {REGISTRATION_STATUS_LABELS[item.status]}
                  </span>
                </td>
                <td className="admin-row-actions">
                  <button
                    type="button"
                    disabled={item.status !== "pending" || busyRequestId === item.request_id}
                    onClick={() => void review(item, "approved")}
                  >
                    {busyRequestId === item.request_id ? "处理中…" : "批准"}
                  </button>
                  <button
                    type="button"
                    disabled={item.status !== "pending" || busyRequestId === item.request_id}
                    onClick={() => void review(item, "rejected")}
                  >
                    拒绝
                  </button>
                </td>
              </tr>
            ))}
            {requests.length === 0 ? (
              <tr><td colSpan={6}>暂无注册申请</td></tr>
            ) : null}
          </tbody>
        </table>
      </div>
      {error ? <p className="auth-error" role="alert">{error}</p> : null}
    </>
  );
}

function EditUserForm({ user, onCancel, onSave }: {
  user: AuthUser;
  onCancel: () => void;
  onSave: (patch: Pick<AuthUser, "nickname" | "email" | "organization">) => Promise<void>;
}) {
  const [nickname, setNickname] = useState(user.nickname);
  const [email, setEmail] = useState(user.email);
  const [organization, setOrganization] = useState(user.organization || "");
  return (
    <div className="admin-subdialog">
      <form onSubmit={(event) => { event.preventDefault(); void onSave({ nickname, email, organization }); }}>
        <h3>编辑账号资料</h3>
        <p className="auth-hint">{user.email}</p>
        <label className="auth-field"><span>昵称</span><input value={nickname} onChange={(e) => setNickname(e.target.value)} required /></label>
        <label className="auth-field"><span>邮箱</span><input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
        <label className="auth-field"><span>学校/机构</span><input value={organization} onChange={(e) => setOrganization(e.target.value)} maxLength={120} /></label>
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

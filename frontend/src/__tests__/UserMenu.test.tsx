import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({
  changePassword: vi.fn(),
  logoutUser: vi.fn(),
  fetchAdminUsers: vi.fn().mockResolvedValue({ status: "success", items: [] }),
  fetchAuditLogs: vi.fn().mockResolvedValue({ status: "success", items: [] }),
  createAdminUser: vi.fn(),
  resetAdminUserPassword: vi.fn(),
  revokeAdminUserSessions: vi.fn(),
  updateAdminUser: vi.fn()
}));

import { UserMenu } from "../components/UserMenu";
import { changePassword, logoutUser } from "../api";
import type { AuthUser } from "../types";

const admin: AuthUser = {
  user_id: "user_admin",
  email: "admin@school.edu.cn",
  nickname: "系统管理员",
  role: "admin",
  status: "active",
  must_change_password: false,
  created_at: "",
  updated_at: "",
  last_login_at: "",
  locked_until: ""
};

const teacher: AuthUser = {
  ...admin,
  user_id: "user_teacher",
  email: "teacher@school.edu.cn",
  nickname: "张老师",
  role: "teacher"
};

describe("UserMenu", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("opens and closes the administrator user-management dialog", async () => {
    render(
      <UserMenu
        user={admin}
        onLogout={vi.fn()}
        onUserChanged={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /系统管理员 管理员/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: "用户管理" }));
    expect(await screen.findByRole("dialog", { name: "教师账号与登录审计" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "关闭" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "教师账号与登录审计" })).not.toBeInTheDocument();
    });
  });

  it("reveals the email and menu actions only after the trigger is clicked", () => {
    render(
      <UserMenu
        user={admin}
        onLogout={vi.fn()}
        onUserChanged={vi.fn()}
      />
    );

    // Menu is closed initially: email and menu items are not rendered.
    expect(screen.queryByText(admin.email)).not.toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "用户管理" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /系统管理员 管理员/ }));

    // Menu is open: email surfaces in the profile block and all actions are reachable.
    expect(screen.getByText(admin.email)).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "用户管理" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "修改密码" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "退出登录" })).toBeInTheDocument();
  });

  it("hides user management for teachers but keeps password change and logout", () => {
    render(
      <UserMenu
        user={teacher}
        onLogout={vi.fn()}
        onUserChanged={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /张老师/ }));

    expect(screen.queryByRole("menuitem", { name: "用户管理" })).not.toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "修改密码" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "退出登录" })).toBeInTheDocument();
  });

  it("changes the password and propagates the updated user", async () => {
    const onUserChanged = vi.fn();
    const updated: AuthUser = { ...admin, must_change_password: false };
    (changePassword as ReturnType<typeof vi.fn>).mockResolvedValue({ status: "success", user: updated });

    render(
      <UserMenu
        user={admin}
        onLogout={vi.fn()}
        onUserChanged={onUserChanged}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /系统管理员 管理员/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: "修改密码" }));

    fireEvent.change(screen.getByLabelText("当前密码"), { target: { value: "OldPass!1" } });
    fireEvent.change(screen.getByLabelText("新密码"), { target: { value: "NewPass!1" } });
    fireEvent.change(screen.getByLabelText("确认新密码"), { target: { value: "NewPass!1" } });
    fireEvent.click(screen.getByRole("button", { name: "保存新密码" }));

    await waitFor(() => {
      expect(changePassword).toHaveBeenCalledWith("OldPass!1", "NewPass!1");
    });
    await waitFor(() => {
      expect(onUserChanged).toHaveBeenCalledWith(updated);
    });
  });

  it("logs out via the API and notifies the host", async () => {
    const onLogout = vi.fn();
    (logoutUser as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);

    render(
      <UserMenu
        user={admin}
        onLogout={onLogout}
        onUserChanged={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /系统管理员 管理员/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: "退出登录" }));

    await waitFor(() => {
      expect(logoutUser).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(onLogout).toHaveBeenCalled();
    });
  });
});

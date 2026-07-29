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
import type { AuthUser } from "../types";

const admin: AuthUser = {
  user_id: "user_admin",
  username: "admin.geo",
  display_name: "系统管理员",
  email: "",
  role: "admin",
  status: "active",
  must_change_password: false,
  created_at: "",
  updated_at: "",
  last_login_at: "",
  locked_until: ""
};

describe("UserMenu", () => {
  afterEach(cleanup);

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
});

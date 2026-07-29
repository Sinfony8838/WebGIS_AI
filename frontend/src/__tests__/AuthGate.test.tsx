import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  bootstrapAdmin: vi.fn(),
  changePassword: vi.fn(),
  fetchBootstrapStatus: vi.fn(),
  fetchCurrentUser: vi.fn(),
  loginUser: vi.fn(),
  setCsrfToken: vi.fn(),
  setUnauthorizedHandler: vi.fn()
}));

vi.mock("../api", () => apiMocks);

import { AuthGate } from "../components/AuthGate";
import type { AuthUser } from "../types";

const admin: AuthUser = {
  user_id: "user_admin",
  username: "admin.geo",
  display_name: "系统管理员",
  email: "",
  role: "admin",
  status: "active",
  must_change_password: false,
  created_at: "2026-07-29T00:00:00Z",
  updated_at: "2026-07-29T00:00:00Z",
  last_login_at: "",
  locked_until: ""
};

describe("AuthGate", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(cleanup);

  it("shows first-run admin initialization before mounting the classroom app", async () => {
    apiMocks.fetchBootstrapStatus.mockResolvedValue({
      status: "success",
      auth_mode: "users",
      required: true
    });
    apiMocks.bootstrapAdmin.mockResolvedValue({
      status: "success",
      user: admin,
      csrf_token: "csrf"
    });

    render(
      <AuthGate>
        {(user) => <div>课堂应用：{user.display_name}</div>}
      </AuthGate>
    );

    expect(await screen.findByRole("heading", { name: "创建系统管理员" })).toBeInTheDocument();
    expect(screen.queryByText(/课堂应用/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "admin.geo" } });
    fireEvent.change(screen.getByLabelText("姓名"), { target: { value: "系统管理员" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "Strong-Admin-2026!" } });
    fireEvent.click(screen.getByRole("button", { name: "创建并进入系统" }));

    expect(await screen.findByText("课堂应用：系统管理员")).toBeInTheDocument();
  });

  it("falls back to the login page when no valid cookie session exists", async () => {
    apiMocks.fetchBootstrapStatus.mockResolvedValue({
      status: "success",
      auth_mode: "users",
      required: false
    });
    apiMocks.fetchCurrentUser.mockRejectedValue(new Error("登录已失效"));

    render(<AuthGate>{() => <div>课堂应用</div>}</AuthGate>);

    expect(await screen.findByRole("heading", { name: "教师工作台登录" })).toBeInTheDocument();
    expect(screen.queryByText("课堂应用")).not.toBeInTheDocument();
  });

  it("forces temporary-password accounts through password change before mounting", async () => {
    apiMocks.fetchBootstrapStatus.mockResolvedValue({
      status: "success",
      auth_mode: "users",
      required: false
    });
    apiMocks.fetchCurrentUser.mockRejectedValue(new Error("not signed in"));
    apiMocks.loginUser.mockResolvedValue({
      status: "success",
      user: { ...admin, must_change_password: true },
      csrf_token: "csrf"
    });
    apiMocks.changePassword.mockResolvedValue({
      status: "success",
      user: admin
    });

    render(<AuthGate>{() => <div>课堂应用</div>}</AuthGate>);
    await screen.findByRole("heading", { name: "教师工作台登录" });
    fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "admin.geo" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "Temporary-2026!" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByRole("heading", { name: "请先修改临时密码" })).toBeInTheDocument();
    expect(screen.queryByText("课堂应用")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("当前密码"), { target: { value: "Temporary-2026!" } });
    fireEvent.change(screen.getByLabelText("新密码"), { target: { value: "New-Admin-Password-2026!" } });
    fireEvent.change(screen.getByLabelText("确认新密码"), { target: { value: "New-Admin-Password-2026!" } });
    fireEvent.click(screen.getByRole("button", { name: "保存新密码" }));

    await waitFor(() => expect(screen.getByText("课堂应用")).toBeInTheDocument());
  });
});

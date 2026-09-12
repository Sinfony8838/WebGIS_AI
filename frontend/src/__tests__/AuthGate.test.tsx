import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  bootstrapAdmin: vi.fn(),
  changePassword: vi.fn(),
  fetchBootstrapStatus: vi.fn(),
  fetchCurrentUser: vi.fn(),
  loginUser: vi.fn(),
  setCsrfToken: vi.fn(),
  setUnauthorizedHandler: vi.fn(),
  submitRegistration: vi.fn()
}));

vi.mock("../api", () => apiMocks);

import { AuthGate } from "../components/AuthGate";
import type { AuthUser } from "../types";

const admin: AuthUser = {
  user_id: "user_admin",
  email: "admin@school.edu.cn",
  nickname: "系统管理员",
  role: "admin",
  status: "active",
  must_change_password: false,
  created_at: "2026-07-29T00:00:00Z",
  updated_at: "2026-07-29T00:00:00Z",
  last_login_at: "",
  locked_until: ""
};

function mockLoginView(registrationMode?: string) {
  apiMocks.fetchBootstrapStatus.mockResolvedValue({
    status: "success",
    auth_mode: "users",
    registration_mode: registrationMode,
    required: false
  });
  apiMocks.fetchCurrentUser.mockRejectedValue(new Error("not signed in"));
}

async function renderLogin(registrationMode?: string) {
  mockLoginView(registrationMode);
  render(<AuthGate>{() => <div>课堂应用</div>}</AuthGate>);
  await screen.findByRole("heading", { name: "教师工作台登录" });
}

describe("AuthGate", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
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
        {(user) => <div>课堂应用：{user.nickname}</div>}
      </AuthGate>
    );

    expect(await screen.findByRole("heading", { name: "创建系统管理员" })).toBeInTheDocument();
    expect(screen.queryByText(/课堂应用/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "admin@school.edu.cn" } });
    fireEvent.change(screen.getByLabelText("昵称"), { target: { value: "系统管理员" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "Strong-Admin-2026!" } });
    fireEvent.click(screen.getByRole("button", { name: "创建并进入系统" }));

    expect(await screen.findByText("课堂应用：系统管理员")).toBeInTheDocument();
    expect(apiMocks.bootstrapAdmin).toHaveBeenCalledWith(expect.objectContaining({
      email: "admin@school.edu.cn",
      nickname: "系统管理员"
    }));
  });

  it("falls back to the login page when no valid cookie session exists", async () => {
    await renderLogin();

    expect(screen.queryByText("课堂应用")).not.toBeInTheDocument();
    expect(screen.getByText("地理智能教学平台")).toBeInTheDocument();
    expect(screen.getByText("面向地理教师与教学管理者 · 不开放学生注册")).toBeInTheDocument();
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
    fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "admin@school.edu.cn" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "Temporary-2026!" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));
    expect(apiMocks.loginUser).toHaveBeenCalledWith("admin@school.edu.cn", "Temporary-2026!");

    expect(await screen.findByRole("heading", { name: "请先修改临时密码" })).toBeInTheDocument();
    expect(screen.queryByText("课堂应用")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("当前密码"), { target: { value: "Temporary-2026!" } });
    fireEvent.change(screen.getByLabelText("新密码"), { target: { value: "New-Admin-Password-2026!" } });
    fireEvent.change(screen.getByLabelText("确认新密码"), { target: { value: "New-Admin-Password-2026!" } });
    fireEvent.click(screen.getByRole("button", { name: "保存新密码" }));

    await waitFor(() => expect(screen.getByText("课堂应用")).toBeInTheDocument());
  });
});

describe("AuthGate registration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
  });

  afterEach(cleanup);

  it("hides the registration entry in closed mode", async () => {
    await renderLogin("closed");
    expect(screen.queryByRole("button", { name: "注册" })).not.toBeInTheDocument();
    expect(
      screen.getByText("面向地理教师与教学管理者 · 不开放学生注册")
    ).toBeInTheDocument();
  });

  it("shows the registration entry in approval mode and switches between views", async () => {
    await renderLogin("approval");
    expect(screen.getByRole("button", { name: "注册" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "注册" }));
    expect(screen.getByRole("heading", { name: "申请教师账号" })).toBeInTheDocument();
    expect(screen.queryByLabelText("昵称")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("学校/机构（可选）")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("申请说明（可选）")).not.toBeInTheDocument();
    expect(screen.getByLabelText("邮箱")).toBeInTheDocument();
    expect(screen.getByLabelText(/^密码$/)).toBeInTheDocument();
    expect(screen.getByLabelText("确认密码")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "登录" }));
    expect(screen.getByRole("heading", { name: "教师工作台登录" })).toBeInTheDocument();
    // The always-present student exclusion stays visible in both modes.
    expect(screen.getByText("不开放学生注册 · 审核通过后才能登录")).toBeInTheDocument();
  });

  it("validates password confirmation and strength before submitting", async () => {
    await renderLogin("approval");
    fireEvent.click(screen.getByRole("button", { name: "注册" }));

    fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "new@school.edu.cn" } });
    fireEvent.change(screen.getByLabelText(/^密码$/), { target: { value: "abcdefgh" } });
    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: "abcdefgh" } });
    fireEvent.click(screen.getByRole("button", { name: "提交注册申请" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("密码不符合要求");

    fireEvent.change(screen.getByLabelText(/^密码$/), { target: { value: "Strong-Teacher-2026!" } });
    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: "different-value" } });
    fireEvent.click(screen.getByRole("button", { name: "提交注册申请" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("两次输入的密码不一致");
    expect(apiMocks.submitRegistration).not.toHaveBeenCalled();
  });

  it("submits the application, returns to login with a status notice, and never signs in", async () => {
    apiMocks.submitRegistration.mockResolvedValue({
      status: "submitted",
      message: "注册申请已提交，管理员审核通过后方可登录。"
    });
    await renderLogin("approval");
    fireEvent.click(screen.getByRole("button", { name: "注册" }));

    fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "new@school.edu.cn" } });
    fireEvent.change(screen.getByLabelText(/^密码$/), { target: { value: "Strong-Teacher-2026!" } });
    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: "Strong-Teacher-2026!" } });
    fireEvent.click(screen.getByRole("button", { name: "提交注册申请" }));

    await waitFor(() => expect(apiMocks.submitRegistration).toHaveBeenCalledWith({
      email: "new@school.edu.cn",
      password: "Strong-Teacher-2026!"
    }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "注册申请已提交，管理员审核通过后方可登录。"
    );
    // Back on the sign-in view, still not signed in.
    expect(screen.getByRole("heading", { name: "教师工作台登录" })).toBeInTheDocument();
    expect(screen.queryByText("课堂应用")).not.toBeInTheDocument();
    expect(apiMocks.loginUser).not.toHaveBeenCalled();
  });

  it("disables the submit button while a registration request is in flight", async () => {
    let resolveSubmit: (value: { status: string; message: string }) => void = () => undefined;
    apiMocks.submitRegistration.mockImplementation(
      () => new Promise((resolve) => { resolveSubmit = resolve; })
    );
    await renderLogin("approval");
    fireEvent.click(screen.getByRole("button", { name: "注册" }));

    fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "new@school.edu.cn" } });
    fireEvent.change(screen.getByLabelText(/^密码$/), { target: { value: "Strong-Teacher-2026!" } });
    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: "Strong-Teacher-2026!" } });
    fireEvent.click(screen.getByRole("button", { name: "提交注册申请" }));

    const submit = screen.getByRole("button", { name: "正在提交申请…" });
    expect(submit).toBeDisabled();
    resolveSubmit({ status: "submitted", message: "注册申请已提交，管理员审核通过后方可登录。" });
    await screen.findByRole("status");
  });

  it("shows the submit error with role=alert when the request fails", async () => {
    apiMocks.submitRegistration.mockRejectedValue(new Error("注册请求过于频繁，请稍后再试。"));
    await renderLogin("approval");
    fireEvent.click(screen.getByRole("button", { name: "注册" }));
    fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "new@school.edu.cn" } });
    fireEvent.change(screen.getByLabelText(/^密码$/), { target: { value: "Strong-Teacher-2026!" } });
    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: "Strong-Teacher-2026!" } });
    fireEvent.click(screen.getByRole("button", { name: "提交注册申请" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("注册请求过于频繁");
  });

  it("reflects the reduced-motion preference on the auth screen", async () => {
    vi.stubGlobal("matchMedia", vi.fn().mockImplementation((query: string) => ({
      matches: query === "(prefers-reduced-motion: reduce)",
      addEventListener: vi.fn(),
      removeEventListener: vi.fn()
    })));
    await renderLogin("approval");
    expect(screen.getByLabelText("邮箱").closest(".auth-screen")).toHaveAttribute(
      "data-reduced-motion",
      "true"
    );
  });

  it("keeps motion enabled when the OS preference is off", async () => {
    vi.stubGlobal("matchMedia", vi.fn().mockImplementation(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn()
    })));
    await renderLogin("approval");
    expect(screen.getByLabelText("邮箱").closest(".auth-screen")).toHaveAttribute(
      "data-reduced-motion",
      "false"
    );
  });

  it("rotates the projected globe in both longitude and latitude when dragged", async () => {
    await renderLogin("approval");
    const globe = screen.getByTestId("auth-globe");
    const svg = globe.querySelector("svg");
    expect(svg).not.toBeNull();
    const beforeLon = svg?.getAttribute("data-rotation-lon");
    const beforeLat = svg?.getAttribute("data-rotation-lat");

    fireEvent.pointerDown(globe, { pointerId: 7, button: 0, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(globe, { pointerId: 7, clientX: 150, clientY: 125 });
    fireEvent.pointerUp(globe, { pointerId: 7, clientX: 150, clientY: 125 });

    expect(svg?.getAttribute("data-rotation-lon")).not.toBe(beforeLon);
    expect(svg?.getAttribute("data-rotation-lat")).not.toBe(beforeLat);
  });
});

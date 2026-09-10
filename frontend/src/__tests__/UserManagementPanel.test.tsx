import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  createAdminUser: vi.fn(),
  fetchAdminUsers: vi.fn(),
  fetchAuditLogs: vi.fn(),
  fetchRegistrationRequests: vi.fn(),
  resetAdminUserPassword: vi.fn(),
  reviewRegistrationRequest: vi.fn(),
  revokeAdminUserSessions: vi.fn(),
  updateAdminUser: vi.fn(),
  changePassword: vi.fn(),
  logoutUser: vi.fn()
}));

vi.mock("../api", () => apiMocks);

import { UserManagementPanel } from "../components/UserManagementPanel";
import { UserMenu } from "../components/UserMenu";
import type { AuthUser, RegistrationRequest } from "../types";

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

const teacher: AuthUser = {
  ...admin,
  user_id: "user_teacher",
  email: "teacher@school.edu.cn",
  nickname: "普通教师",
  role: "teacher"
};

const pendingRequest: RegistrationRequest = {
  request_id: "regreq_1",
  email: "applicant@school.edu.cn",
  display_name: "申请教师",
  organization: "上海中学",
  application_note: "任教高一地理，希望使用平台备课。",
  status: "pending",
  source_ip: "127.0.0.1",
  user_agent: "vitest",
  created_at: "2026-09-01T08:00:00Z",
  updated_at: "2026-09-01T08:00:00Z",
  reviewed_by: "",
  reviewed_at: "",
  resulting_user_id: ""
};

const approvedRequest: RegistrationRequest = {
  ...pendingRequest,
  request_id: "regreq_2",
  email: "approved@school.edu.cn",
  display_name: "已批准教师",
  organization: "北京中学",
  application_note: "任教高二地理。",
  status: "approved",
  reviewed_by: "user_admin",
  reviewed_at: "2026-09-02T08:00:00Z",
  resulting_user_id: "user_new"
};

function mockAdminData() {
  apiMocks.fetchAdminUsers.mockResolvedValue({ status: "success", items: [admin, teacher] });
  apiMocks.fetchAuditLogs.mockResolvedValue({ status: "success", items: [] });
  apiMocks.fetchRegistrationRequests.mockResolvedValue({
    status: "success",
    items: [pendingRequest, approvedRequest],
    pending_count: 1
  });
}

describe("UserMenu admin entry gating", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(cleanup);

  it("hides the management entry from ordinary teachers", () => {
    render(<UserMenu user={teacher} onLogout={() => undefined} onUserChanged={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: /账号菜单/ }));
    expect(screen.queryByRole("menuitem", { name: "用户管理" })).not.toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "退出登录" })).toBeInTheDocument();
  });

  it("shows the management entry for admins", () => {
    render(<UserMenu user={admin} onLogout={() => undefined} onUserChanged={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: /账号菜单/ }));
    expect(screen.getByRole("menuitem", { name: "用户管理" })).toBeInTheDocument();
  });
});

describe("UserManagementPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAdminData();
  });

  afterEach(cleanup);

  it("lists users and keeps the existing capabilities visible", async () => {
    render(<UserManagementPanel currentUser={admin} onClose={() => undefined} />);
    expect(await screen.findByText("teacher@school.edu.cn")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "创建账号" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "安全审计" })).toBeInTheDocument();
  });

  it("shows the registrations tab with a pending badge and request details", async () => {
    render(<UserManagementPanel currentUser={admin} onClose={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: /注册申请/ }));

    expect(await screen.findByText("applicant@school.edu.cn")).toBeInTheDocument();
    expect(screen.getByText("上海中学")).toBeInTheDocument();
    expect(screen.getByText(/任教高一地理/)).toBeInTheDocument();
    expect(screen.getByText("1 条待审核")).toBeInTheDocument();
    expect(screen.getByLabelText("1 条待审核")).toHaveTextContent("1");
  });

  it("searches and filters registration requests", async () => {
    render(<UserManagementPanel currentUser={admin} onClose={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: /注册申请/ }));
    await screen.findByText("applicant@school.edu.cn");

    fireEvent.change(screen.getByLabelText("搜索注册申请"), { target: { value: "上海中学" } });
    await waitFor(() =>
      expect(apiMocks.fetchRegistrationRequests).toHaveBeenLastCalledWith({
        query: "上海中学",
        status: ""
      })
    );

    fireEvent.change(screen.getByLabelText("筛选申请状态"), { target: { value: "pending" } });
    await waitFor(() =>
      expect(apiMocks.fetchRegistrationRequests).toHaveBeenLastCalledWith({
        query: "上海中学",
        status: "pending"
      })
    );
  });

  it("approves a pending request after confirmation and refreshes both lists", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    apiMocks.reviewRegistrationRequest.mockResolvedValue({
      status: "success",
      request: { ...pendingRequest, status: "approved" }
    });
    render(<UserManagementPanel currentUser={admin} onClose={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: /注册申请/ }));

    const row = (await screen.findByText("applicant@school.edu.cn")).closest("tr");
    expect(row).not.toBeNull();
    const approve = within(row as HTMLElement).getByRole("button", { name: "批准" });
    fireEvent.click(approve);

    await waitFor(() =>
      expect(apiMocks.reviewRegistrationRequest).toHaveBeenCalledWith("regreq_1", "approved")
    );
    expect(await screen.findByText(/已批准 applicant@school\.edu\.cn/)).toBeInTheDocument();
    await waitFor(() => expect(apiMocks.fetchAdminUsers).toHaveBeenCalledTimes(2));
    // Mount badge check + tab load + post-decision reload + badge refresh.
    expect(apiMocks.fetchRegistrationRequests).toHaveBeenCalledTimes(4);
  });

  it("does not review when the confirmation is dismissed", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<UserManagementPanel currentUser={admin} onClose={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: /注册申请/ }));
    const row = (await screen.findByText("applicant@school.edu.cn")).closest("tr");
    fireEvent.click(within(row as HTMLElement).getByRole("button", { name: "拒绝" }));

    expect(apiMocks.reviewRegistrationRequest).not.toHaveBeenCalled();
  });

  it("rejects a request after confirmation", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    apiMocks.reviewRegistrationRequest.mockResolvedValue({
      status: "success",
      request: { ...pendingRequest, status: "rejected" }
    });
    render(<UserManagementPanel currentUser={admin} onClose={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: /注册申请/ }));
    const row = (await screen.findByText("applicant@school.edu.cn")).closest("tr");
    fireEvent.click(within(row as HTMLElement).getByRole("button", { name: "拒绝" }));

    await waitFor(() =>
      expect(apiMocks.reviewRegistrationRequest).toHaveBeenCalledWith("regreq_1", "rejected")
    );
    expect(await screen.findByText(/已拒绝 applicant@school\.edu\.cn/)).toBeInTheDocument();
  });

  it("surfaces review errors with role=alert and refreshes the list", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    apiMocks.reviewRegistrationRequest.mockRejectedValue(new Error("该邮箱已被注册，无法批准；请拒绝该申请或联系教师更换邮箱。"));
    render(<UserManagementPanel currentUser={admin} onClose={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: /注册申请/ }));
    const row = (await screen.findByText("applicant@school.edu.cn")).closest("tr");
    fireEvent.click(within(row as HTMLElement).getByRole("button", { name: "批准" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("该邮箱已被注册");
  });

  it("disables review actions for already-reviewed requests", async () => {
    render(<UserManagementPanel currentUser={admin} onClose={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: /注册申请/ }));
    const row = (await screen.findByText("approved@school.edu.cn")).closest("tr");
    expect(within(row as HTMLElement).getByRole("button", { name: "批准" })).toBeDisabled();
    expect(within(row as HTMLElement).getByRole("button", { name: "拒绝" })).toBeDisabled();
  });
});

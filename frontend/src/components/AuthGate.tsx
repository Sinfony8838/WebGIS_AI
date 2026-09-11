import { useEffect, useState } from "react";
import {
  bootstrapAdmin,
  changePassword,
  fetchBootstrapStatus,
  fetchCurrentUser,
  loginUser,
  setCsrfToken,
  setUnauthorizedHandler,
  submitRegistration
} from "../api";
import type { AuthUser, RegistrationMode } from "../types";
import "../auth.css";
import { BrandLogo } from "./BrandLogo";
import { ThemeToggle } from "../theme";
import globeDark from "../assets/earth/auth-globe-dark.svg";
import globeLight from "../assets/earth/auth-globe-light.svg";

type AuthGateProps = {
  children: (user: AuthUser, signOut: () => void, updateUser: (user: AuthUser) => void) => React.ReactNode;
};

type AuthView = "loading" | "login" | "bootstrap" | "change-password";

const PASSWORD_HINT = "至少 8 位，并包含字母、数字、特殊符号中的至少两种。";

function passwordMeetsPolicy(value: string): boolean {
  if (value.length < 8 || value.length > 128) return false;
  const categories = [
    /[a-zA-Z]/.test(value),
    /[0-9]/.test(value),
    /[^a-zA-Z0-9\s]/.test(value)
  ].filter(Boolean).length;
  return categories >= 2;
}

/** Tracks the OS reduce-motion preference so the login view can drop every
 * decorative animation. CSS also honors the media query; this attribute keeps
 * it testable and covers browsers where the SVG media context differs. */
function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () => typeof window !== "undefined" && Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches)
  );
  useEffect(() => {
    const query = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!query) return undefined;
    const update = () => setReduced(query.matches);
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);
  return reduced;
}

export function AuthGate({ children }: AuthGateProps) {
  const [view, setView] = useState<AuthView>("loading");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [error, setError] = useState("");
  const [registrationMode, setRegistrationMode] = useState<RegistrationMode | undefined>(undefined);

  const reset = () => {
    setCsrfToken("");
    setUser(null);
    setError("");
    setView("login");
  };

  useEffect(() => {
    let active = true;
    setUnauthorizedHandler(() => {
      if (active) reset();
    });
    void (async () => {
      try {
        const status = await fetchBootstrapStatus();
        if (!active) return;
        setRegistrationMode(status.registration_mode);
        if (status.required) {
          setView("bootstrap");
          return;
        }
        try {
          const session = await fetchCurrentUser();
          if (!active) return;
          setUser(session.user);
          setView(session.user.must_change_password ? "change-password" : "login");
        } catch {
          if (active) setView("login");
        }
      } catch (reason) {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : "无法连接到鉴权服务");
        setView("login");
      }
    })();
    return () => {
      active = false;
      setUnauthorizedHandler(null);
    };
  }, []);

  if (user && !user.must_change_password && view !== "change-password") {
    return <>{children(user, reset, setUser)}</>;
  }

  if (view === "loading") {
    return (
      <div className="auth-screen auth-entry" aria-busy="true" data-reduced-motion="false">
        <div className="auth-loading">正在验证教师身份…</div>
      </div>
    );
  }

  if (view === "change-password" && user) {
    return (
      <PasswordChangeCard
        forced
        error={error}
        onSubmit={async (currentPassword, newPassword) => {
          setError("");
          try {
            const result = await changePassword(currentPassword, newPassword);
            setUser(result.user);
            setView("login");
          } catch (reason) {
            setError(reason instanceof Error ? reason.message : "密码修改失败");
          }
        }}
        onCancel={reset}
      />
    );
  }

  return (
    <LoginCard
      bootstrap={view === "bootstrap"}
      error={error}
      registrationMode={registrationMode}
      onSubmit={async (payload) => {
        setError("");
        try {
          const session =
            view === "bootstrap"
              ? await bootstrapAdmin({
                  email: payload.email,
                  nickname: payload.nickname,
                  password: payload.password,
                  bootstrap_key: payload.bootstrapKey
                })
              : await loginUser(payload.email, payload.password);
          setUser(session.user);
          setView(session.user.must_change_password ? "change-password" : "login");
        } catch (reason) {
          setError(reason instanceof Error ? reason.message : "登录失败");
        }
      }}
    />
  );
}

type LoginPayload = {
  email: string;
  nickname: string;
  password: string;
  bootstrapKey: string;
};

type AuthCardMode = "signin" | "signup";

function LoginCard({
  bootstrap,
  error,
  registrationMode,
  onSubmit
}: {
  bootstrap: boolean;
  error: string;
  registrationMode: RegistrationMode | undefined;
  onSubmit: (payload: LoginPayload) => Promise<void>;
}) {
  const [mode, setMode] = useState<AuthCardMode>("signin");
  const [email, setEmail] = useState("");
  const [nickname, setNickname] = useState("");
  const [organization, setOrganization] = useState("");
  const [applicationNote, setApplicationNote] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [bootstrapKey, setBootstrapKey] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const [pending, setPending] = useState(false);
  const [signupError, setSignupError] = useState("");
  const [signupNotice, setSignupNotice] = useState("");

  const signupAllowed = !bootstrap && Boolean(registrationMode && registrationMode !== "closed");
  const reducedMotion = usePrefersReducedMotion();

  const switchTo = (next: AuthCardMode) => {
    setMode(next);
    setSignupError("");
    if (next === "signin") {
      // Keep the submitted notice visible until the teacher types again.
    } else {
      setSignupNotice("");
    }
  };

  const handleSignup = async () => {
    setSignupError("");
    if (!email.trim() || !nickname.trim()) {
      setSignupError("请填写邮箱和昵称。");
      return;
    }
    if (!passwordMeetsPolicy(password)) {
      setSignupError(`密码不符合要求：${PASSWORD_HINT}`);
      return;
    }
    if (password !== confirmPassword) {
      setSignupError("两次输入的密码不一致。");
      return;
    }
    setPending(true);
    try {
      const result = await submitRegistration({
        email: email.trim(),
        nickname: nickname.trim(),
        password,
        organization: organization.trim(),
        application_note: applicationNote.trim()
      });
      // Success: return to the sign-in view with a safe notice. Registration
      // never signs the user in, in any mode.
      setPassword("");
      setConfirmPassword("");
      setApplicationNote("");
      setSignupNotice(result.message || APPROVAL_NOTICE_DEFAULT);
      setMode("signin");
    } catch (reason) {
      setSignupError(reason instanceof Error ? reason.message : "注册提交失败，请稍后再试。");
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="auth-screen auth-entry" data-reduced-motion={reducedMotion ? "true" : "false"}>
      <ThemeToggle className="auth-theme-toggle" />
      <div className="auth-entry-layout">
        <section className="auth-story" aria-labelledby="auth-story-title">
          <div className="auth-story-brand anim-rise">
            <BrandLogo className="auth-story-logo" />
            <span>GeoBot<small>地理智能教学平台</small></span>
          </div>
          <div className="auth-story-copy anim-rise">
            <p className="auth-story-kicker">地图里的世界 · 课堂里的发现</p>
            <h2 id="auth-story-title">让地理可见，<br />让探究发生。</h2>
            <p>从一张地图出发，连接教案设计、课堂探究与教学复盘。</p>
          </div>
          <div className="auth-globe-wrap anim-rise" aria-hidden="true">
            <img className="auth-globe-img auth-globe-img-dark" src={globeDark} alt="" draggable={false} loading="eager" decoding="async" />
            <img className="auth-globe-img auth-globe-img-light" src={globeLight} alt="" draggable={false} loading="eager" decoding="async" />
          </div>
          <ol className="auth-teaching-cycle anim-rise">
            <li><span>01 / 课前</span><strong>设计一堂好课</strong><p>教案共创 · 资源准备</p></li>
            <li><span>02 / 课中</span><strong>在地图上探究</strong><p>可视化工具 · 智能助教</p></li>
            <li><span>03 / 课后</span><strong>让教学有回响</strong><p>课堂记录 · 复盘改进</p></li>
          </ol>
        </section>
        <main className="auth-card auth-entry-card anim-rise" aria-labelledby="auth-title">
          <div className="auth-brand" aria-hidden="true">
            <BrandLogo className="auth-brand-logo" />
            <span>GeoBot</span>
          </div>
          <p className="auth-eyebrow">{bootstrap ? "开始使用 GEOBOT" : "欢迎回到 GEOBOT"}</p>
          <h1 id="auth-title">{bootstrap ? "创建系统管理员" : mode === "signup" ? "申请教师账号" : "教师工作台登录"}</h1>
          <p className="auth-subtitle">
            {bootstrap
              ? "首次启动仅需初始化一个管理员账号，之后由管理员为教师开户。"
              : mode === "signup"
                ? "提交注册申请，管理员审核通过后即可登录使用。"
                : "登录教师账号，继续你的地理课堂。"}
          </p>
          {signupAllowed ? (
            <div className="auth-mode-switch" role="group" aria-label="登录或注册">
              <button
                type="button"
                aria-pressed={mode === "signin"}
                className={mode === "signin" ? "active" : ""}
                onClick={() => switchTo("signin")}
              >
                登录
              </button>
              <button
                type="button"
                aria-pressed={mode === "signup"}
                className={mode === "signup" ? "active" : ""}
                onClick={() => switchTo("signup")}
              >
                注册
              </button>
            </div>
          ) : null}
          {signupNotice && mode === "signin" ? (
            <p className="auth-success" role="status">{signupNotice}</p>
          ) : null}
          {mode === "signin" || bootstrap ? (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                setPending(true);
                void onSubmit({ email, nickname, password, bootstrapKey }).finally(() => setPending(false));
              }}
            >
              <label className="auth-field">
                <span>邮箱</span>
                <input
                  autoFocus
                  type="email"
                  autoComplete="username"
                  inputMode="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="例如：teacher@school.edu.cn"
                  required
                />
              </label>
              {bootstrap ? (
                <label className="auth-field">
                  <span>昵称</span>
                  <input
                    autoComplete="nickname"
                    value={nickname}
                    onChange={(event) => setNickname(event.target.value)}
                    placeholder="用于课堂工作台显示"
                    required
                  />
                </label>
              ) : null}
              {bootstrap ? (
                <label className="auth-field">
                  <span>部署初始化密钥（仅远程部署需要）</span>
                  <input
                    type="password"
                    autoComplete="off"
                    value={bootstrapKey}
                    onChange={(event) => setBootstrapKey(event.target.value)}
                    placeholder="本机初始化可留空"
                  />
                </label>
              ) : null}
              <label className="auth-field">
                <span>密码</span>
                <span className="auth-password">
                  <input
                    type={showPassword ? "text" : "password"}
                    autoComplete={bootstrap ? "new-password" : "current-password"}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    onKeyUp={(event) => setCapsLock(event.getModifierState("CapsLock"))}
                    onKeyDown={(event) => setCapsLock(event.getModifierState("CapsLock"))}
                    minLength={bootstrap ? 8 : undefined}
                    required
                  />
                  <button type="button" onClick={() => setShowPassword((value) => !value)}>
                    {showPassword ? "隐藏" : "显示"}
                  </button>
                </span>
              </label>
              {capsLock ? <p className="auth-hint">Caps Lock 已开启</p> : null}
              {bootstrap ? <p className="auth-hint">{PASSWORD_HINT}</p> : null}
              {error ? <p className="auth-error" role="alert">{error}</p> : null}
              <button className="auth-primary" type="submit" disabled={pending}>
                {pending ? "请稍候…" : bootstrap ? "创建并进入系统" : "登录"}
              </button>
            </form>
          ) : (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (!pending) void handleSignup();
              }}
            >
              <label className="auth-field">
                <span>邮箱</span>
                <input
                  type="email"
                  autoComplete="username"
                  inputMode="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="例如：teacher@school.edu.cn"
                  required
                />
              </label>
              <label className="auth-field">
                <span>昵称</span>
                <input
                  autoComplete="nickname"
                  value={nickname}
                  onChange={(event) => setNickname(event.target.value)}
                  placeholder="用于课堂工作台显示"
                  maxLength={80}
                  required
                />
              </label>
              <label className="auth-field">
                <span>学校/机构（可选）</span>
                <input
                  autoComplete="organization"
                  value={organization}
                  onChange={(event) => setOrganization(event.target.value)}
                  placeholder="例如：上海市某中学"
                  maxLength={120}
                />
              </label>
              <label className="auth-field">
                <span>申请说明（可选）</span>
                <textarea
                  value={applicationNote}
                  onChange={(event) => setApplicationNote(event.target.value)}
                  placeholder="简要说明教学场景，帮助管理员更快审核"
                  maxLength={300}
                  rows={3}
                />
              </label>
              <label className="auth-field">
                <span>密码</span>
                <span className="auth-password">
                  <input
                    type={showPassword ? "text" : "password"}
                    autoComplete="new-password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    onKeyUp={(event) => setCapsLock(event.getModifierState("CapsLock"))}
                    onKeyDown={(event) => setCapsLock(event.getModifierState("CapsLock"))}
                    minLength={8}
                    maxLength={128}
                    required
                  />
                  <button type="button" onClick={() => setShowPassword((value) => !value)}>
                    {showPassword ? "隐藏" : "显示"}
                  </button>
                </span>
              </label>
              <label className="auth-field">
                <span>确认密码</span>
                <input
                  type={showPassword ? "text" : "password"}
                  autoComplete="new-password"
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  minLength={8}
                  maxLength={128}
                  required
                />
              </label>
              <p className="auth-hint">{PASSWORD_HINT}</p>
              {capsLock ? <p className="auth-hint">Caps Lock 已开启</p> : null}
              {signupError ? <p className="auth-error" role="alert">{signupError}</p> : null}
              <button className="auth-primary" type="submit" disabled={pending}>
                {pending ? "正在提交申请…" : "提交注册申请"}
              </button>
            </form>
          )}
          <footer>
            {registrationMode === "approval" || registrationMode === "open"
              ? "面向地理教师与教学管理者 · 支持教师注册申请"
              : "面向地理教师与教学管理者 · 不开放学生注册"}
            <span className="auth-footer-note">不开放学生注册 · 审核通过后才能登录</span>
          </footer>
        </main>
      </div>
    </div>
  );
}

const APPROVAL_NOTICE_DEFAULT = "注册申请已提交，管理员审核通过后方可登录。";

export function PasswordChangeCard({
  forced = false,
  error = "",
  onSubmit,
  onCancel
}: {
  forced?: boolean;
  error?: string;
  onSubmit: (currentPassword: string, newPassword: string) => Promise<void>;
  onCancel: () => void;
}) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [localError, setLocalError] = useState("");
  const [pending, setPending] = useState(false);
  return (
    <div className={forced ? "auth-screen" : "auth-modal-backdrop"}>
      <form
        className="auth-card auth-card-compact"
        aria-labelledby="password-title"
        onSubmit={(event) => {
          event.preventDefault();
          if (newPassword !== confirmPassword) {
            setLocalError("两次输入的新密码不一致");
            return;
          }
          setLocalError("");
          setPending(true);
          void onSubmit(currentPassword, newPassword).finally(() => setPending(false));
        }}
      >
        <p className="auth-eyebrow">账号安全</p>
        <h2 id="password-title">{forced ? "请先修改临时密码" : "修改密码"}</h2>
        <label className="auth-field">
          <span>当前密码</span>
          <input
            type="password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
            required
          />
        </label>
        <label className="auth-field">
          <span>新密码</span>
          <input
            type="password"
            autoComplete="new-password"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            minLength={8}
            required
          />
        </label>
        <label className="auth-field">
          <span>确认新密码</span>
          <input
            type="password"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
            minLength={8}
            required
          />
        </label>
        <p className="auth-hint">至少 8 位，并包含字母、数字、特殊符号中的至少两种。</p>
        {localError || error ? <p className="auth-error" role="alert">{localError || error}</p> : null}
        <div className="auth-actions">
          {!forced ? <button type="button" onClick={onCancel}>取消</button> : null}
          {forced ? <button type="button" onClick={onCancel}>退出登录</button> : null}
          <button className="auth-primary" type="submit" disabled={pending}>
            {pending ? "保存中…" : "保存新密码"}
          </button>
        </div>
      </form>
    </div>
  );
}

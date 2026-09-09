import { useEffect, useState } from "react";
import {
  bootstrapAdmin,
  changePassword,
  fetchBootstrapStatus,
  fetchCurrentUser,
  loginUser,
  setCsrfToken,
  setUnauthorizedHandler
} from "../api";
import type { AuthUser } from "../types";
import "../auth.css";
import { BrandLogo } from "./BrandLogo";
import { ThemeToggle } from "../theme";

type AuthGateProps = {
  children: (user: AuthUser, signOut: () => void, updateUser: (user: AuthUser) => void) => React.ReactNode;
};

type AuthView = "loading" | "login" | "bootstrap" | "change-password";

export function AuthGate({ children }: AuthGateProps) {
  const [view, setView] = useState<AuthView>("loading");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [error, setError] = useState("");

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
      <div className="auth-screen" aria-busy="true">
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

function LoginCard({
  bootstrap,
  error,
  onSubmit
}: {
  bootstrap: boolean;
  error: string;
  onSubmit: (payload: LoginPayload) => Promise<void>;
}) {
  const [email, setEmail] = useState("");
  const [nickname, setNickname] = useState("");
  const [password, setPassword] = useState("");
  const [bootstrapKey, setBootstrapKey] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const [pending, setPending] = useState(false);

  return (
    <div className="auth-screen auth-entry">
      <ThemeToggle className="auth-theme-toggle" />
      <div className="auth-map-grid" aria-hidden="true" />
      <div className="auth-population-points" aria-hidden="true" />
      <div className="auth-entry-layout">
      <section className="auth-story" aria-labelledby="auth-story-title">
        <div className="auth-story-brand"><BrandLogo className="auth-story-logo" /><span>GeoBot<small>人口地理智能教学平台</small></span></div>
        <div className="auth-story-copy">
          <p className="auth-story-kicker">地图里的世界 · 课堂里的发现</p>
          <h2 id="auth-story-title">让地理可见，<br />让探究发生。</h2>
          <p>从一张地图出发，连接教案设计、课堂探究与教学复盘。</p>
        </div>
        <svg className="auth-globe-art" viewBox="0 0 640 420" fill="none" aria-hidden="true">
          <defs>
            <radialGradient id="auth-globe-fill"><stop stopColor="#23868c" stopOpacity=".24"/><stop offset="1" stopColor="#0b2a3e" stopOpacity=".04"/></radialGradient>
            <clipPath id="auth-globe-clip"><circle cx="320" cy="218" r="173"/></clipPath>
          </defs>
          <ellipse cx="320" cy="218" rx="286" ry="90" transform="rotate(-23 320 218)" stroke="currentColor" strokeOpacity=".17" strokeDasharray="5 8"/>
          <circle cx="320" cy="218" r="173" fill="url(#auth-globe-fill)" stroke="currentColor" strokeOpacity=".5"/>
          <g stroke="currentColor" strokeOpacity=".2" clipPath="url(#auth-globe-clip)">
            <ellipse cx="320" cy="218" rx="70" ry="173"/><ellipse cx="320" cy="218" rx="137" ry="173"/>
            <ellipse cx="320" cy="218" rx="173" ry="59"/><ellipse cx="320" cy="218" rx="173" ry="125"/>
            <path d="M147 218h346M320 45v346"/>
            <path d="m201 116 32-16 18 15 35-8 21 25-19 18-4 32-32 4-19 31-22-15-5-29-30-14zM253 220l30 5 19 30-10 30-20 18-8 48-18-22-6-39-23-29zM335 107l36-22 52 29 33 37-17 22-39-13-15 32-29 5-15 39-27-20 8-42-22-24zM397 283l38-15 20 28-17 26-41-12z" fill="currentColor" fillOpacity=".2" strokeOpacity=".45"/>
          </g>
          <path d="M256 176Q340 87 411 179M256 176Q284 221 272 270" stroke="currentColor" strokeOpacity=".65" strokeDasharray="4 6"/>
          <g fill="currentColor"><circle cx="256" cy="176" r="5"/><circle cx="411" cy="179" r="5"/><circle cx="272" cy="270" r="4"/></g>
          <circle cx="411" cy="179" r="13" stroke="currentColor" strokeOpacity=".4"/>
        </svg>
        <ol className="auth-teaching-cycle">
          <li><span>01 / 课前</span><strong>设计一堂好课</strong><p>教案共创 · 资源准备</p></li>
          <li><span>02 / 课中</span><strong>在地图上探究</strong><p>可视化工具 · 智能助教</p></li>
          <li><span>03 / 课后</span><strong>让教学有回响</strong><p>课堂记录 · 复盘改进</p></li>
        </ol>
      </section>
      <main className="auth-card auth-entry-card" aria-labelledby="auth-title">
        <div className="auth-brand" aria-hidden="true">
          <BrandLogo className="auth-brand-logo" />
          <span>GeoBot</span>
        </div>
        <p className="auth-eyebrow">{bootstrap ? "开始使用 GEOBOT" : "欢迎回到 GEOBOT"}</p>
        <h1 id="auth-title">{bootstrap ? "创建系统管理员" : "教师工作台登录"}</h1>
        <p className="auth-subtitle">
          {bootstrap
            ? "首次启动仅需初始化一个管理员账号，之后由管理员为教师开户。"
            : "登录教师账号，继续你的地理课堂。"}
        </p>
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
          {bootstrap ? <p className="auth-hint">至少 8 位，并包含字母、数字、特殊符号中的至少两种。</p> : null}
          {error ? <p className="auth-error" role="alert">{error}</p> : null}
          <button className="auth-primary" type="submit" disabled={pending}>
            {pending ? "请稍候…" : bootstrap ? "创建并进入系统" : "登录"}
          </button>
        </form>
        <footer>仅面向教师与管理员 · 不开放学生注册</footer>
      </main>
      </div>
    </div>
  );
}

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

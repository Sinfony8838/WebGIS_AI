import platformLogo from "../assets/brand/geobot-platform-logo.png";
import "./BrandLogo.css";

export function BrandLogo({ className = "" }: { className?: string }) {
  return (
    <img
      className={`geobot-brand-logo ${className}`.trim()}
      src={platformLogo}
      alt=""
      aria-hidden="true"
      draggable={false}
    />
  );
}

import { IconMoon, IconSun } from "@tabler/icons-react";
import { useTheme } from "../theme";

type ThemeToggleProps = {
  className?: string;
};

export function ThemeToggle({ className = "" }: ThemeToggleProps) {
  const { theme, toggleTheme } = useTheme();
  const nextThemeLabel = theme === "dark" ? "切换到日间模式" : "切换到夜间模式";

  return (
    <button
      type="button"
      className={`theme-toggle${className ? ` ${className}` : ""}`}
      aria-label={nextThemeLabel}
      title={nextThemeLabel}
      onClick={toggleTheme}
    >
      {theme === "dark" ? <IconSun size={18} stroke={1.8} /> : <IconMoon size={18} stroke={1.8} />}
      <span className="theme-toggle__label">{theme === "dark" ? "日间" : "夜间"}</span>
    </button>
  );
}

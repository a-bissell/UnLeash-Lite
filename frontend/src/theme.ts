const THEME_KEY = 'unleash_theme';
export type Theme = 'dark' | 'light';

export function getTheme(): Theme {
  // Light is the default; only an explicit stored 'dark' opts out.
  return localStorage.getItem(THEME_KEY) === 'dark' ? 'dark' : 'light';
}

/** Apply the stored theme to <html>. Call once before render. */
export function initTheme() {
  applyTheme(getTheme());
}

function applyTheme(theme: Theme) {
  if (theme === 'light') {
    document.documentElement.setAttribute('data-theme', 'light');
  } else {
    document.documentElement.removeAttribute('data-theme');
  }
}

/** Flip the theme, persist it, and return the new value. */
export function toggleTheme(): Theme {
  const next: Theme = getTheme() === 'light' ? 'dark' : 'light';
  localStorage.setItem(THEME_KEY, next);
  applyTheme(next);
  return next;
}

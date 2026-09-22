// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
  #[cfg(target_os = "linux")]
  {
    // WebKitGTK 2.42+ DMA-BUF renderer and Wayland compositor crash inside WSLg
    // (Weston software copy mode). Forcing X11 backend and software compositing fixes this.
    if std::env::var_os("WEBKIT_DISABLE_DMABUF_RENDERER").is_none() {
      std::env::set_var("WEBKIT_DISABLE_DMABUF_RENDERER", "1");
    }
    if std::env::var_os("WEBKIT_DISABLE_COMPOSITING_MODE").is_none() {
      std::env::set_var("WEBKIT_DISABLE_COMPOSITING_MODE", "1");
    }
    if std::env::var_os("GDK_BACKEND").is_none() {
      std::env::set_var("GDK_BACKEND", "x11");
    }
  }

  app_lib::run();
}

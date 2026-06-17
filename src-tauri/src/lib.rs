use std::process::Command;
#[cfg(windows)]
use std::os::windows::process::CommandExt;
use std::sync::Mutex;
use tauri::{Manager, path::BaseDirectory};

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

/// Holds the handle to the Python sidecar so it can be force-killed as a
/// fallback if the window is destroyed without the JS side sending the
/// normal "shutdown" websocket message (e.g. app crash, task-killed window).
struct Sidecar(Mutex<Option<std::process::Child>>);

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .manage(Sidecar(Mutex::new(None)))
    .setup(|app| {
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }

      // Only auto-spawn the embedded sidecar in production builds (i.e. the
      // installed MSI). In `tauri dev`, src-tauri/resources/python/ doesn't
      // exist until build_installer.ps1 has run — dev relies on start.bat
      // launching python.exe from the dev venv instead.
      if !cfg!(debug_assertions) {
        let python_exe = app
          .path()
          .resolve("python/python.exe", BaseDirectory::Resource)?;
        let backend_dir = app
          .path()
          .resolve("python_backend", BaseDirectory::Resource)?;
        let app_script = backend_dir.join("app.py");

        let mut cmd = Command::new(python_exe);
        cmd.arg(app_script).current_dir(&backend_dir);

        // Prevent a console window from flashing open for non-technical users.
        #[cfg(windows)]
        cmd.creation_flags(CREATE_NO_WINDOW);

        let child = cmd
          .spawn()
          .expect("failed to start the embedded Python sidecar");

        app.state::<Sidecar>().0.lock().unwrap().replace(child);
      }

      Ok(())
    })
    .on_window_event(|window, event| {
      if let tauri::WindowEvent::Destroyed = event {
        if let Some(mut child) = window
          .app_handle()
          .state::<Sidecar>()
          .0
          .lock()
          .unwrap()
          .take()
        {
          let _ = child.kill();
        }
      }
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}
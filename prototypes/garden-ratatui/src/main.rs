use std::{io, path::PathBuf, time::Duration};

use crossterm::{
    event::{self, DisableMouseCapture, EnableMouseCapture, Event},
    execute,
    terminal::{EnterAlternateScreen, LeaveAlternateScreen, disable_raw_mode, enable_raw_mode},
};
use gengowatcher_tui::{
    App, ConnectionState, View,
    api::ApiClient,
    live::{LiveWorker, WorkerEvent},
    preview::render_previews,
    render,
};
use ratatui::{Terminal, backend::CrosstermBackend};

fn main() -> io::Result<()> {
    let mode = parse_mode()?;
    if let Mode::Render(output_dir) = mode {
        for path in render_previews(&output_dir)? {
            println!("{}", path.display());
        }
        return Ok(());
    }
    let Mode::Interactive(options) = mode else {
        unreachable!()
    };
    let (app, worker) = if options.demo {
        (App::new(options.view), None)
    } else {
        let token = std::env::var("GENGOWATCHER_API_TOKEN").map_err(|_| {
            io::Error::new(
                io::ErrorKind::PermissionDenied,
                "GENGOWATCHER_API_TOKEN is required for live mode; use --demo for sample data",
            )
        })?;
        let client = ApiClient::new(&options.api_url, &token)
            .map_err(|error| io::Error::new(io::ErrorKind::InvalidInput, error))?;
        (
            App::live(options.view),
            Some(LiveWorker::start(client, options.poll_interval)),
        )
    };
    let mut session = TerminalSession::new()?;
    let result = run(&mut session.terminal, app, worker);
    let restore_result = session.restore();
    result.and(restore_result)
}

enum Mode {
    Interactive(InteractiveOptions),
    Render(PathBuf),
}

struct InteractiveOptions {
    view: View,
    demo: bool,
    api_url: String,
    poll_interval: Duration,
}

fn parse_mode() -> io::Result<Mode> {
    let mut args = std::env::args().skip(1);
    let mut view = View::Overview;
    let mut demo = false;
    let mut api_url =
        std::env::var("GENGOWATCHER_API_URL").unwrap_or_else(|_| "http://127.0.0.1:8000".into());
    let mut poll_interval = Duration::from_secs(2);
    let mut render_dir = None;
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--view" => {
                let value = args.next().ok_or_else(|| {
                    io::Error::new(io::ErrorKind::InvalidInput, "--view requires a value")
                })?;
                view = View::from_slug(&value).ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, format!("unknown view {value:?}; use overview, jobs, work, history, analytics, or system")))?;
            }
            "--demo" => demo = true,
            "--api-url" => {
                api_url = args.next().ok_or_else(|| {
                    io::Error::new(io::ErrorKind::InvalidInput, "--api-url requires a value")
                })?;
            }
            "--poll-ms" => {
                let value = args.next().ok_or_else(|| {
                    io::Error::new(io::ErrorKind::InvalidInput, "--poll-ms requires a value")
                })?;
                let milliseconds = value.parse::<u64>().map_err(|_| {
                    io::Error::new(io::ErrorKind::InvalidInput, "--poll-ms must be an integer")
                })?;
                if milliseconds < 250 {
                    return Err(io::Error::new(
                        io::ErrorKind::InvalidInput,
                        "--poll-ms must be at least 250",
                    ));
                }
                poll_interval = Duration::from_millis(milliseconds);
            }
            "--render" => {
                let value = args.next().ok_or_else(|| {
                    io::Error::new(
                        io::ErrorKind::InvalidInput,
                        "--render requires an output directory",
                    )
                })?;
                render_dir = Some(PathBuf::from(value));
            }
            "-h" | "--help" => {
                println!(
                    "GengoWatcher Ratatui TUI\n\nUsage:\n  cargo run -- [--view VIEW] [--api-url URL] [--poll-ms 2000]\n  cargo run -- --demo [--view VIEW]\n  cargo run -- --render OUTPUT_DIR\n\nLive mode reads the bearer token from GENGOWATCHER_API_TOKEN.\nViews: overview, jobs, work, history, analytics, system"
                );
                std::process::exit(0);
            }
            other => {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidInput,
                    format!("unexpected argument {other:?}"),
                ));
            }
        }
    }
    if let Some(output_dir) = render_dir {
        return Ok(Mode::Render(output_dir));
    }
    Ok(Mode::Interactive(InteractiveOptions {
        view,
        demo,
        api_url,
        poll_interval,
    }))
}

struct TerminalSession {
    terminal: Terminal<CrosstermBackend<io::Stdout>>,
    restored: bool,
}

impl TerminalSession {
    fn new() -> io::Result<Self> {
        enable_raw_mode()?;
        let mut stdout = io::stdout();
        if let Err(error) = execute!(stdout, EnterAlternateScreen, EnableMouseCapture) {
            let _ = disable_raw_mode();
            return Err(error);
        }
        match Terminal::new(CrosstermBackend::new(stdout)) {
            Ok(terminal) => Ok(Self {
                terminal,
                restored: false,
            }),
            Err(error) => {
                let mut stdout = io::stdout();
                let _ = execute!(stdout, DisableMouseCapture, LeaveAlternateScreen);
                let _ = disable_raw_mode();
                Err(error)
            }
        }
    }

    fn restore(&mut self) -> io::Result<()> {
        if self.restored {
            return Ok(());
        }
        self.restored = true;
        restore_terminal(&mut self.terminal)
    }
}

impl Drop for TerminalSession {
    fn drop(&mut self) {
        let _ = self.restore();
    }
}

fn restore_terminal(terminal: &mut Terminal<CrosstermBackend<io::Stdout>>) -> io::Result<()> {
    let raw_result = disable_raw_mode();
    let screen_result = execute!(
        terminal.backend_mut(),
        DisableMouseCapture,
        LeaveAlternateScreen
    );
    let cursor_result = terminal.show_cursor();
    raw_result.and(screen_result).and(cursor_result)
}

fn run(
    terminal: &mut Terminal<CrosstermBackend<io::Stdout>>,
    mut app: App,
    worker: Option<LiveWorker>,
) -> io::Result<()> {
    while !app.should_quit {
        if let Some(worker) = worker.as_ref() {
            drain_worker(worker, &mut app);
        }
        terminal.draw(|frame| render(frame, &mut app))?;
        if !event::poll(Duration::from_millis(250))? {
            continue;
        }
        let action = match event::read()? {
            Event::Key(key) => app.handle_key(key),
            Event::Mouse(mouse) => {
                app.handle_mouse(mouse);
                None
            }
            Event::Resize(_, _) | Event::FocusGained | Event::FocusLost | Event::Paste(_) => None,
        };
        if let Some(action) = action {
            if let Some(worker) = worker.as_ref() {
                if let Err(error) = worker.send(action) {
                    app.apply_action_result(Err(error));
                }
            } else if app.connection == ConnectionState::Demo {
                app.apply_action_result(Ok("Demo mode · action was not sent".into()));
            }
        }
    }
    Ok(())
}

fn drain_worker(worker: &LiveWorker, app: &mut App) {
    loop {
        match worker.try_recv() {
            Ok(Some(WorkerEvent::Snapshot(snapshot))) => app.apply_snapshot(*snapshot),
            Ok(Some(WorkerEvent::ActionResult(result))) => app.apply_action_result(result),
            Ok(Some(WorkerEvent::ConnectionError(error))) | Err(error) => {
                app.apply_error(error);
                break;
            }
            Ok(None) => break,
        }
    }
}

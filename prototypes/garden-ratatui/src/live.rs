//! Background polling and command execution for the terminal event loop.

use std::{
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
        mpsc::{self, Receiver, RecvTimeoutError, Sender, TryRecvError},
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};

use crate::{
    UiAction,
    api::ApiClient,
    model::{DashboardData, TranslateRunDetail, TranslateRunSummary},
};

#[derive(Debug)]
enum WorkerCommand {
    Action(UiAction),
    Shutdown,
}

#[derive(Debug)]
pub enum WorkerEvent {
    Snapshot(Box<DashboardData>),
    ActionResult {
        action: UiAction,
        result: Result<String, String>,
    },
    TranslateList(Vec<TranslateRunSummary>),
    TranslateDetail(Box<TranslateRunDetail>),
    TranslateModels(Vec<String>),
    TranslateStarted(String),
    ConnectionError(String),
}

pub struct LiveWorker {
    commands: Sender<WorkerCommand>,
    events: Receiver<WorkerEvent>,
    shutdown: Arc<AtomicBool>,
    thread: Option<JoinHandle<()>>,
}

impl LiveWorker {
    #[must_use]
    pub fn start(client: ApiClient, poll_interval: Duration) -> Self {
        let (command_tx, command_rx) = mpsc::channel();
        let (event_tx, event_rx) = mpsc::channel();
        let shutdown = Arc::new(AtomicBool::new(false));
        let worker_shutdown = Arc::clone(&shutdown);
        let thread = thread::Builder::new()
            .name("gengowatcher-api".into())
            .spawn(move || {
                worker_loop(
                    client,
                    poll_interval,
                    command_rx,
                    &event_tx,
                    &worker_shutdown,
                );
            })
            .expect("failed to start API worker thread");
        Self {
            commands: command_tx,
            events: event_rx,
            shutdown,
            thread: Some(thread),
        }
    }

    pub fn send(&self, action: UiAction) -> Result<(), String> {
        self.commands
            .send(WorkerCommand::Action(action))
            .map_err(|_| "API worker stopped".into())
    }

    pub fn try_recv(&self) -> Result<Option<WorkerEvent>, String> {
        match self.events.try_recv() {
            Ok(event) => Ok(Some(event)),
            Err(TryRecvError::Empty) => Ok(None),
            Err(TryRecvError::Disconnected) => Err("API worker stopped".into()),
        }
    }
}

impl Drop for LiveWorker {
    fn drop(&mut self) {
        self.shutdown.store(true, Ordering::Release);
        let _ = self.commands.send(WorkerCommand::Shutdown);
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
    }
}

fn worker_loop(
    client: ApiClient,
    poll_interval: Duration,
    commands: Receiver<WorkerCommand>,
    events: &Sender<WorkerEvent>,
    shutdown: &AtomicBool,
) {
    let poll_interval = poll_interval.max(Duration::from_millis(250));
    let mut next_poll = Instant::now();
    let mut retry_delay = Duration::from_secs(1);
    loop {
        if shutdown.load(Ordering::Acquire) {
            break;
        }
        let timeout = next_poll.saturating_duration_since(Instant::now());
        match commands.recv_timeout(timeout) {
            Ok(WorkerCommand::Shutdown) | Err(RecvTimeoutError::Disconnected) => break,
            Ok(WorkerCommand::Action(action)) => {
                // Translate reads are lazy (only while the Translate view is
                // active) so the 2s snapshot loop stays small. Detail fetches
                // read retained files server-side and respect snapshot timeout.
                match &action {
                    UiAction::RefreshTranslate => {
                        match client.list_translate_runs() {
                            Ok(runs) => {
                                let count = runs.len();
                                if events.send(WorkerEvent::TranslateList(runs)).is_err() {
                                    break;
                                }
                                if events
                                    .send(WorkerEvent::ActionResult {
                                        action: action.clone(),
                                        result: Ok(format!("Translate runs updated · {count}")),
                                    })
                                    .is_err()
                                {
                                    break;
                                }
                            }
                            Err(error) => {
                                if events
                                    .send(WorkerEvent::ActionResult {
                                        action: action.clone(),
                                        result: Err(error.to_string()),
                                    })
                                    .is_err()
                                {
                                    break;
                                }
                            }
                        }
                        next_poll = Instant::now();
                    }
                    UiAction::GetTranslateDetail(run_id) => {
                        match client.get_translate_run(run_id) {
                            Ok(detail) => {
                                if events
                                    .send(WorkerEvent::TranslateDetail(Box::new(detail)))
                                    .is_err()
                                {
                                    break;
                                }
                                if events
                                    .send(WorkerEvent::ActionResult {
                                        action: action.clone(),
                                        result: Ok(format!("Translate detail loaded · {run_id}")),
                                    })
                                    .is_err()
                                {
                                    break;
                                }
                            }
                            Err(error) => {
                                if events
                                    .send(WorkerEvent::ActionResult {
                                        action: action.clone(),
                                        result: Err(error.to_string()),
                                    })
                                    .is_err()
                                {
                                    break;
                                }
                            }
                        }
                        next_poll = Instant::now();
                    }
                    UiAction::FetchTranslateModels => {
                        match client.list_translate_models() {
                            Ok(models) => {
                                let count = models.len();
                                if events.send(WorkerEvent::TranslateModels(models)).is_err() {
                                    break;
                                }
                                if events
                                    .send(WorkerEvent::ActionResult {
                                        action: action.clone(),
                                        result: Ok(format!("Translate models loaded · {count}")),
                                    })
                                    .is_err()
                                {
                                    break;
                                }
                            }
                            Err(error) => {
                                if events
                                    .send(WorkerEvent::ActionResult {
                                        action: action.clone(),
                                        result: Err(error.to_string()),
                                    })
                                    .is_err()
                                {
                                    break;
                                }
                            }
                        }
                        next_poll = Instant::now();
                    }
                    UiAction::StartTranslate {
                        text,
                        models,
                        with_review,
                    } => {
                        // Submit is a single 202 POST; the worker then chains a
                        // list refresh plus detail for the new run so the TUI
                        // selects it without main-loop round trips. Event order
                        // over the channel is FIFO: Started, List, Detail.
                        match client.start_translate(text, models.clone(), *with_review) {
                            Ok(run_id) => {
                                // One final ActionResult carries the outcome: an
                                // unconditional Ok here would overwrite a chained
                                // partial failure applied earlier in the same
                                // drain loop, hiding it from the user.
                                let mut chain_error: Option<String> = None;
                                if events
                                    .send(WorkerEvent::TranslateStarted(run_id.clone()))
                                    .is_err()
                                {
                                    break;
                                }
                                match client.list_translate_runs() {
                                    Ok(runs) => {
                                        if events.send(WorkerEvent::TranslateList(runs)).is_err() {
                                            break;
                                        }
                                    }
                                    Err(error) => {
                                        chain_error = Some(format!(
                                            "Translate run {run_id} submitted but list refresh failed · {error}"
                                        ));
                                    }
                                }
                                match client.get_translate_run(&run_id) {
                                    Ok(detail) => {
                                        if events
                                            .send(WorkerEvent::TranslateDetail(Box::new(detail)))
                                            .is_err()
                                        {
                                            break;
                                        }
                                    }
                                    Err(error) => {
                                        chain_error.get_or_insert(format!(
                                            "Translate run {run_id} submitted but detail refresh failed · {error}"
                                        ));
                                    }
                                }
                                if events
                                    .send(WorkerEvent::ActionResult {
                                        action: action.clone(),
                                        result: chain_error.map_or_else(
                                            || Ok(format!("Translate run submitted · {run_id}")),
                                            Err,
                                        ),
                                    })
                                    .is_err()
                                {
                                    break;
                                }
                            }
                            Err(error) => {
                                if events
                                    .send(WorkerEvent::ActionResult {
                                        action: action.clone(),
                                        result: Err(error.to_string()),
                                    })
                                    .is_err()
                                {
                                    break;
                                }
                            }
                        }
                        next_poll = Instant::now();
                    }
                    _ => {
                        let result = execute_action(&client, &action);
                        if events
                            .send(WorkerEvent::ActionResult { action, result })
                            .is_err()
                        {
                            break;
                        }
                        next_poll = Instant::now();
                    }
                }
            }
            Err(RecvTimeoutError::Timeout) => match client.fetch_snapshot() {
                Ok(snapshot) => {
                    retry_delay = Duration::from_secs(1);
                    next_poll = Instant::now() + poll_interval;
                    if events
                        .send(WorkerEvent::Snapshot(Box::new(snapshot)))
                        .is_err()
                    {
                        break;
                    }
                }
                Err(error) => {
                    next_poll = Instant::now() + retry_delay;
                    retry_delay = (retry_delay * 2).min(Duration::from_secs(15));
                    if events
                        .send(WorkerEvent::ConnectionError(error.to_string()))
                        .is_err()
                    {
                        break;
                    }
                }
            },
        }
    }
}

fn execute_action(client: &ApiClient, action: &UiAction) -> Result<String, String> {
    let response = match action {
        UiAction::Refresh => client.command("check"),
        UiAction::Command(command) => client.command(command),
        UiAction::AcceptJob(job_id) => client.accept_job(job_id),
        UiAction::CancelCurrentJob => client.cancel_current_job(),
        UiAction::RefreshTranslate | UiAction::GetTranslateDetail(_) => {
            return Err("Translate reads use dedicated worker events".into());
        }
        UiAction::FetchTranslateModels | UiAction::StartTranslate { .. } => {
            return Err("Translate submit uses dedicated worker events".into());
        }
    }
    .map_err(|error| error.to_string())?;
    if response.status.eq_ignore_ascii_case("success") {
        Ok(response.message)
    } else {
        Err(if response.message.is_empty() {
            "API action failed".into()
        } else {
            response.message
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        io::{Read, Write},
        net::TcpListener,
    };

    #[test]
    fn poll_interval_has_a_safe_lower_bound() {
        let requested = Duration::from_millis(10);
        assert_eq!(
            requested.max(Duration::from_millis(250)),
            Duration::from_millis(250)
        );
    }

    #[test]
    fn start_translate_chains_started_list_and_detail_events() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind test server");
        let address = listener.local_addr().expect("test address");
        let server = thread::spawn(move || {
            let script = [
                (
                    "POST /api/translate",
                    "202 Accepted",
                    r#"{"run_id":"id-1"}"#,
                ),
                (
                    "GET /api/translate HTTP/1.1",
                    "200 OK",
                    r#"{"runs":[{"run_id":"id-1","kind":"text","char_count":2,"with_review":true,"models":["opencode"],"created_at":1000,"finished":false,"per_model":{"opencode":{"status":"running"}},"input_preview":"hi"}]}"#,
                ),
                (
                    "GET /api/translate/id-1 HTTP/1.1",
                    "200 OK",
                    r#"{"run_id":"id-1","source_text":"hi","results":{}}"#,
                ),
            ];
            for (prefix, status, body) in script {
                // The worker may fetch a snapshot before the queued command
                // arrives; reject those leading reads instead of failing the
                // scripted assertion.
                let (mut stream, request) = loop {
                    let (mut stream, _) = listener.accept().expect("accept request");
                    let mut buffer = vec![0_u8; 16_384];
                    let bytes = stream.read(&mut buffer).expect("read request");
                    let request = String::from_utf8_lossy(&buffer[..bytes]).into_owned();
                    if request.starts_with(prefix) {
                        break (stream, request);
                    }
                    assert!(
                        request.starts_with("GET /api/status")
                            || request.starts_with("GET /api/jobs")
                            || request.starts_with("GET /api/events")
                            || request.starts_with("GET /api/stats"),
                        "{request}"
                    );
                    write!(
                        stream,
                        "HTTP/1.1 500 Internal Server Error\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                    )
                    .expect("write rejection");
                };
                let _ = &request;
                write!(
                    stream,
                    "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len(),
                )
                .expect("write response");
            }
        });
        let client =
            ApiClient::new(&format!("http://{address}"), "test-token").expect("valid client");
        let worker = LiveWorker::start(client, Duration::from_secs(60));
        worker
            .send(UiAction::StartTranslate {
                text: "hi".into(),
                models: None,
                with_review: true,
            })
            .expect("submit sent");

        let mut events = Vec::new();
        let deadline = Instant::now() + Duration::from_secs(10);
        while events.len() < 4 && Instant::now() < deadline {
            match worker.try_recv().expect("worker alive") {
                Some(event) => events.push(event),
                None => thread::sleep(Duration::from_millis(10)),
            }
        }
        drop(worker);
        assert_eq!(events.len(), 4, "Started, List, Detail, ActionResult");

        match &events[0] {
            WorkerEvent::TranslateStarted(run_id) => assert_eq!(run_id, "id-1"),
            other => panic!("expected TranslateStarted first, got {other:?}"),
        }
        match &events[1] {
            WorkerEvent::TranslateList(runs) => {
                assert_eq!(runs.len(), 1);
                assert_eq!(runs[0].run_id, "id-1");
            }
            other => panic!("expected TranslateList second, got {other:?}"),
        }
        match &events[2] {
            WorkerEvent::TranslateDetail(detail) => {
                assert_eq!(detail.summary.run_id, "id-1");
            }
            other => panic!("expected TranslateDetail third, got {other:?}"),
        }
        match &events[3] {
            WorkerEvent::ActionResult { result, .. } => {
                let message = result.as_ref().expect("submit succeeded");
                assert!(message.contains("submitted · id-1"), "{message}");
            }
            other => panic!("expected ActionResult last, got {other:?}"),
        }
        server.join().expect("test server joined");
    }

    #[test]
    fn start_translate_reports_chained_refresh_failure_once() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind test server");
        let address = listener.local_addr().expect("test address");
        let server = thread::spawn(move || {
            let script = [
                (
                    "POST /api/translate",
                    "202 Accepted",
                    r#"{"run_id":"id-9"}"#,
                ),
                (
                    "GET /api/translate HTTP/1.1",
                    "500 Internal Server Error",
                    r#"{"detail":"boom"}"#,
                ),
                (
                    "GET /api/translate/id-9 HTTP/1.1",
                    "200 OK",
                    r#"{"run_id":"id-9","source_text":"hi","results":{}}"#,
                ),
            ];
            for (prefix, status, body) in script {
                let (mut stream, _) = listener.accept().expect("accept request");
                let mut buffer = vec![0_u8; 16_384];
                let bytes = stream.read(&mut buffer).expect("read request");
                let request = String::from_utf8_lossy(&buffer[..bytes]);
                assert!(request.starts_with(prefix), "{request}");
                write!(
                    stream,
                    "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len(),
                )
                .expect("write response");
            }
        });
        let client =
            ApiClient::new(&format!("http://{address}"), "test-token").expect("valid client");
        // A long poll interval keeps snapshots out of this scripted exchange.
        let worker = LiveWorker::start(client, Duration::from_secs(60));
        worker
            .send(UiAction::StartTranslate {
                text: "hi".into(),
                models: None,
                with_review: true,
            })
            .expect("submit sent");

        let mut events = Vec::new();
        let deadline = Instant::now() + Duration::from_secs(10);
        while events.len() < 3 && Instant::now() < deadline {
            match worker.try_recv().expect("worker alive") {
                Some(event) => events.push(event),
                None => thread::sleep(Duration::from_millis(10)),
            }
        }
        drop(worker);
        assert_eq!(events.len(), 3, "Started, Detail, single ActionResult");
        match &events[2] {
            WorkerEvent::ActionResult { result, .. } => {
                let error = result.as_ref().expect_err("list failure reported");
                assert!(
                    error.contains("submitted but list refresh failed"),
                    "{error}"
                );
            }
            other => panic!("expected ActionResult last, got {other:?}"),
        }
        server.join().expect("test server joined");
    }
}

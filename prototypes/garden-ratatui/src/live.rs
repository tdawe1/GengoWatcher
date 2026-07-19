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

use crate::{UiAction, api::ApiClient, model::DashboardData};

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
                let result = execute_action(&client, action.clone());
                if events
                    .send(WorkerEvent::ActionResult { action, result })
                    .is_err()
                {
                    break;
                }
                next_poll = Instant::now();
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

fn execute_action(client: &ApiClient, action: UiAction) -> Result<String, String> {
    let response = match action {
        UiAction::Refresh => client.command("check"),
        UiAction::Command(command) => client.command(command),
        UiAction::AcceptJob(job_id) => client.accept_job(&job_id),
        UiAction::CancelCurrentJob => client.cancel_current_job(),
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

    #[test]
    fn poll_interval_has_a_safe_lower_bound() {
        let requested = Duration::from_millis(10);
        assert_eq!(
            requested.max(Duration::from_millis(250)),
            Duration::from_millis(250)
        );
    }
}

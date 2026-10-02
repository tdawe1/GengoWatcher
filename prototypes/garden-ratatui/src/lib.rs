//! Native Ratatui client for GengoWatcher's operational dashboard.
//!
//! Live mode consumes the authenticated loopback API. Demo and deterministic
//! preview modes retain sample data for development and visual regression work.

use std::{
    collections::{BTreeMap, HashSet},
    time::{SystemTime, UNIX_EPOCH},
};

use crossterm::event::{
    KeyCode, KeyEvent, KeyEventKind, KeyModifiers, MouseButton, MouseEvent, MouseEventKind,
};
use ratatui::{
    Frame,
    layout::{Alignment, Constraint, Layout, Margin, Rect},
    style::{Modifier, Style},
    text::{Line, Span, Text},
    widgets::{
        Block, BorderType, Borders, Cell, Clear, List, ListItem, Paragraph, Row, Table, TableState,
        Wrap,
    },
};

pub mod api;
pub mod live;
pub mod model;
pub mod preview;
pub mod theme;

use model::{DashboardData, Job, TranslateRunDetail, TranslateRunSummary, WorkStage};
use theme::*;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum View {
    Overview,
    Jobs,
    Work,
    History,
    Analytics,
    System,
    Translate,
}

impl View {
    pub const ALL: [Self; 7] = [
        Self::Overview,
        Self::Jobs,
        Self::Work,
        Self::History,
        Self::Analytics,
        Self::System,
        Self::Translate,
    ];

    #[must_use]
    pub const fn label(self) -> &'static str {
        match self {
            Self::Overview => "Overview",
            Self::Jobs => "Available Jobs",
            Self::Work => "Active Work",
            Self::History => "History",
            Self::Analytics => "Analytics",
            Self::System => "System",
            Self::Translate => "Translate",
        }
    }

    #[must_use]
    pub const fn slug(self) -> &'static str {
        match self {
            Self::Overview => "overview",
            Self::Jobs => "jobs",
            Self::Work => "work",
            Self::History => "history",
            Self::Analytics => "analytics",
            Self::System => "system",
            Self::Translate => "translate",
        }
    }

    #[must_use]
    pub fn from_slug(value: &str) -> Option<Self> {
        Self::ALL.into_iter().find(|view| view.slug() == value)
    }

    const fn index(self) -> usize {
        match self {
            Self::Overview => 0,
            Self::Jobs => 1,
            Self::Work => 2,
            Self::History => 3,
            Self::Analytics => 4,
            Self::System => 5,
            Self::Translate => 6,
        }
    }

    const fn previous(self) -> Self {
        Self::ALL[(self.index() + Self::ALL.len() - 1) % Self::ALL.len()]
    }

    const fn next(self) -> Self {
        Self::ALL[(self.index() + 1) % Self::ALL.len()]
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum LayoutKind {
    /// Sidebar navigation with per-view dashboards (original chrome).
    #[default]
    Classic,
    /// Alert instrument: top tabs, hero opportunity card, queue, action rail.
    Beacon,
    /// Dense dashboard: top tabs, single-row tables, content-sized panels.
    Dense,
}

impl LayoutKind {
    #[must_use]
    pub const fn slug(self) -> &'static str {
        match self {
            Self::Classic => "classic",
            Self::Beacon => "beacon",
            Self::Dense => "dense",
        }
    }

    #[must_use]
    pub fn from_slug(value: &str) -> Option<Self> {
        match value {
            "classic" => Some(Self::Classic),
            "beacon" => Some(Self::Beacon),
            "dense" => Some(Self::Dense),
            _ => None,
        }
    }

    #[must_use]
    pub const fn next(self) -> Self {
        match self {
            Self::Classic => Self::Beacon,
            Self::Beacon => Self::Dense,
            Self::Dense => Self::Classic,
        }
    }

    #[must_use]
    pub const fn label(self) -> &'static str {
        match self {
            Self::Classic => "Classic",
            Self::Beacon => "Beacon",
            Self::Dense => "Dense",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum UiAction {
    Refresh,
    Command(&'static str),
    AcceptJob(String),
    CancelCurrentJob,
    RefreshTranslate,
    GetTranslateDetail(String),
    FetchTranslateModels,
    StartTranslate {
        text: String,
        models: Option<Vec<String>>,
        with_review: bool,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ConnectionState {
    Demo,
    Connecting,
    Live,
    Reconnecting(String),
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum Confirmation {
    Accept(String),
    CancelCurrent,
}

#[derive(Debug)]
pub struct App {
    pub view: View,
    pub layout: LayoutKind,
    pub should_quit: bool,
    pub paused: bool,
    pub alert_visible: bool,
    pub selected_job: usize,
    pub selected_history: usize,
    pub selected_translate: usize,
    pub translate_runs: Vec<TranslateRunSummary>,
    pub translate_detail: Option<TranslateRunDetail>,
    pub translate_loading: bool,
    pending_translate_detail: Option<String>,
    pub translate_draft: String,
    draft_cursor: usize,
    pub editing_draft: bool,
    pub translate_modal: bool,
    pub translate_models: Vec<String>,
    translate_models_selected: Vec<bool>,
    pub translate_with_review: bool,
    translate_models_loading: bool,
    pub submit_pending: bool,
    pending_select_run: Option<String>,
    pub status_message: String,
    pub data: DashboardData,
    pub connection: ConnectionState,
    ignored_job_ids: HashSet<String>,
    confirmation: Option<Confirmation>,
    pending_destructive: Option<Confirmation>,
    nav_hitboxes: Vec<(Rect, View)>,
}

impl Default for App {
    fn default() -> Self {
        Self::new(View::Overview)
    }
}

impl App {
    #[must_use]
    pub fn new(view: View) -> Self {
        Self::with_data(view, DashboardData::demo(), ConnectionState::Demo)
    }

    #[must_use]
    pub fn with_layout(view: View, layout: LayoutKind) -> Self {
        let mut app = Self::new(view);
        app.layout = layout;
        app
    }

    #[must_use]
    pub fn live(view: View) -> Self {
        Self::with_data(view, DashboardData::default(), ConnectionState::Connecting)
    }

    #[must_use]
    pub fn live_with_layout(view: View, layout: LayoutKind) -> Self {
        let mut app = Self::live(view);
        app.layout = layout;
        app
    }

    fn with_data(view: View, data: DashboardData, connection: ConnectionState) -> Self {
        let paused = data.status.is_paused;
        let is_demo = connection == ConnectionState::Demo;
        let translate_runs = if is_demo {
            TranslateRunSummary::demo_list()
        } else {
            Vec::new()
        };
        let translate_detail = if is_demo {
            translate_runs
                .first()
                .map(|run| TranslateRunDetail::demo(&run.run_id))
        } else {
            None
        };
        Self {
            view,
            layout: LayoutKind::Classic,
            should_quit: false,
            paused,
            alert_visible: true,
            selected_job: 0,
            selected_history: 0,
            selected_translate: 0,
            translate_runs,
            translate_detail,
            translate_loading: false,
            pending_translate_detail: None,
            translate_draft: String::new(),
            draft_cursor: 0,
            editing_draft: false,
            translate_modal: false,
            translate_models: Vec::new(),
            translate_models_selected: Vec::new(),
            translate_with_review: true,
            translate_models_loading: false,
            submit_pending: false,
            pending_select_run: None,
            status_message: if is_demo {
                "Demo data · no API actions are sent".into()
            } else {
                "Connecting to GengoWatcher API…".into()
            },
            data,
            connection,
            ignored_job_ids: HashSet::new(),
            confirmation: None,
            pending_destructive: None,
            nav_hitboxes: Vec::with_capacity(View::ALL.len()),
        }
    }

    pub fn apply_snapshot(&mut self, data: DashboardData) {
        let previous_ids: HashSet<String> = self
            .visible_available_jobs()
            .into_iter()
            .map(|job| job.id.clone())
            .collect();
        self.paused = data.status.is_paused;
        self.data = data;
        self.connection = ConnectionState::Live;
        self.clamp_selection();
        self.status_message = "Live data updated".into();
        if self
            .visible_available_jobs()
            .into_iter()
            .any(|job| !previous_ids.contains(&job.id))
        {
            self.alert_visible = true;
        }
    }

    pub fn apply_error(&mut self, message: impl Into<String>) {
        let message = message.into();
        self.pending_destructive = None;
        // A dead worker must not wedge in-flight translate flags: without
        // this the auto-poll skips forever and the submit modal refuses to
        // refetch models. Local compose state (draft/modal) is preserved.
        self.translate_loading = false;
        self.translate_models_loading = false;
        self.submit_pending = false;
        self.connection = ConnectionState::Reconnecting(message.clone());
        self.status_message = format!("API unavailable · {message}");
    }

    pub fn apply_action_result(&mut self, result: Result<String, String>) {
        match result {
            Ok(message) => self.status_message = message,
            Err(message) => self.status_message = format!("Action failed · {message}"),
        }
    }

    pub fn apply_action_result_for(&mut self, action: &UiAction, result: Result<String, String>) {
        let matches_pending = matches!(
            (&self.pending_destructive, action),
            (Some(Confirmation::Accept(pending_id)), UiAction::AcceptJob(result_id))
                if pending_id == result_id
        ) || matches!(
            (&self.pending_destructive, action),
            (
                Some(Confirmation::CancelCurrent),
                UiAction::CancelCurrentJob
            )
        );
        if matches_pending {
            self.pending_destructive = None;
        }
        if matches!(
            action,
            UiAction::RefreshTranslate | UiAction::GetTranslateDetail(_)
        ) {
            match &result {
                Ok(message) => self.status_message = message.clone(),
                Err(message) => {
                    self.translate_loading = false;
                    self.status_message = format!("Translate failed · {message}");
                }
            }
            return;
        }
        if matches!(action, UiAction::FetchTranslateModels) {
            self.translate_models_loading = false;
            self.apply_action_result(result);
            return;
        }
        if matches!(action, UiAction::StartTranslate { .. }) {
            if result.is_err() {
                self.submit_pending = false;
                self.translate_loading = false;
            }
            self.apply_action_result(result);
            return;
        }
        self.apply_action_result(result);
    }

    pub fn apply_translate_models(&mut self, models: Vec<String>) {
        // Preserve per-model toggles across refetches by name; a first load
        // selects every model (server default is all).
        let had_models = !self.translate_models.is_empty();
        let previously_selected: HashSet<&str> = self
            .translate_models
            .iter()
            .zip(self.translate_models_selected.iter())
            .filter(|(_, selected)| **selected)
            .map(|(name, _)| name.as_str())
            .collect();
        self.translate_models_selected = models
            .iter()
            .map(|name| {
                if had_models {
                    previously_selected.contains(name.as_str())
                } else {
                    true
                }
            })
            .collect();
        self.translate_models = models;
        self.translate_models_loading = false;
        self.status_message = format!("Translate models loaded · {}", self.translate_models.len());
    }

    pub fn apply_translate_started(&mut self, run_id: String) {
        self.submit_pending = false;
        self.translate_loading = true;
        self.pending_select_run = Some(run_id.clone());
        self.status_message = format!("Translate run submitted · {run_id}");
    }

    pub fn apply_translate_list(&mut self, runs: Vec<TranslateRunSummary>) {
        self.translate_runs = runs;
        self.translate_loading = false;
        self.clamp_translate_selection();
        // A fresh submit selects its own run once the chained list arrives.
        if let Some(pending) = self.pending_select_run.clone()
            && let Some(index) = self
                .translate_runs
                .iter()
                .position(|run| run.run_id == pending)
        {
            self.selected_translate = index;
            self.pending_select_run = None;
        }
        self.status_message = format!("Translate runs updated · {}", self.translate_runs.len());
    }

    pub fn apply_translate_detail(&mut self, detail: TranslateRunDetail) {
        let selected_matches = self
            .selected_translate_run()
            .is_some_and(|run| run.run_id == detail.summary.run_id);
        let pending_matches = self
            .pending_translate_detail
            .as_deref()
            .is_none_or(|pending| pending == detail.summary.run_id);
        if !(selected_matches && pending_matches) {
            return;
        }
        self.translate_detail = Some(detail);
        self.pending_translate_detail = None;
        self.translate_loading = false;
        self.status_message = "Translate detail loaded".into();
    }

    #[must_use]
    pub fn selected_translate_run(&self) -> Option<&TranslateRunSummary> {
        self.translate_runs.get(self.selected_translate)
    }

    fn clamp_translate_selection(&mut self) {
        self.selected_translate = self
            .selected_translate
            .min(self.translate_runs.len().saturating_sub(1));
        if let Some(selected) = self.selected_translate_run() {
            let selected_id = selected.run_id.clone();
            let detail_matches = self
                .translate_detail
                .as_ref()
                .is_some_and(|detail| detail.summary.run_id == selected_id);
            if !detail_matches {
                self.translate_detail = None;
            }
            let pending_matches = self
                .pending_translate_detail
                .as_deref()
                .is_none_or(|pending| pending == selected_id);
            if !pending_matches {
                self.pending_translate_detail = None;
                self.translate_loading = false;
            }
        } else {
            self.translate_detail = None;
            self.pending_translate_detail = None;
            self.translate_loading = false;
        }
    }

    fn clear_translate_selection_state(&mut self) {
        self.translate_detail = None;
        self.pending_translate_detail = None;
        self.translate_loading = false;
        // Manual navigation wins over a pending post-submit selection.
        self.pending_select_run = None;
    }

    /// Actions the event loop should send while the Translate view is active.
    /// Live progress without loading the 2s snapshot loop: refresh the list
    /// and, when the selected run is still unfinished, its detail.
    #[must_use]
    pub fn translate_auto_poll(&self) -> Vec<UiAction> {
        if self.view != View::Translate || self.connection == ConnectionState::Demo {
            return Vec::new();
        }
        if self.translate_loading || self.submit_pending || self.translate_models_loading {
            return Vec::new();
        }
        let mut actions = vec![UiAction::RefreshTranslate];
        // The list refresh never updates the cached detail, so an unfinished
        // selection refetches its detail on every poll until it finishes.
        if let Some(run) = self.selected_translate_run()
            && !run.finished
        {
            actions.push(UiAction::GetTranslateDetail(run.run_id.clone()));
        }
        actions
    }

    #[must_use]
    pub fn handle_key(&mut self, key: KeyEvent) -> Option<UiAction> {
        if key.code == KeyCode::Char('c') && key.modifiers.contains(KeyModifiers::CONTROL) {
            self.should_quit = true;
            return None;
        }
        // Compose modes run before the repeat gate so held editing keys
        // (backspace, arrows, characters) repeat naturally. The confirmation
        // modal below stays unreachable while composing: its keys never enter
        // these modes, and composing keys never open a confirmation.
        if self.translate_modal || self.editing_draft {
            if key.kind != KeyEventKind::Press && key.kind != KeyEventKind::Repeat {
                return None;
            }
            if self.translate_modal {
                return self.handle_translate_modal_key(key);
            }
            self.handle_draft_edit_key(key);
            return None;
        }
        if key.kind == KeyEventKind::Repeat && !is_repeatable_key(key.code) {
            return None;
        }
        if key.kind != KeyEventKind::Press && key.kind != KeyEventKind::Repeat {
            return None;
        }
        if let Some(confirmation) = self.confirmation.clone() {
            return match key.code {
                KeyCode::Char('y') | KeyCode::Enter => {
                    self.confirmation = None;
                    self.pending_destructive = Some(confirmation.clone());
                    self.status_message = "Action submitted…".into();
                    match confirmation {
                        Confirmation::Accept(job_id) => Some(UiAction::AcceptJob(job_id)),
                        Confirmation::CancelCurrent => Some(UiAction::CancelCurrentJob),
                    }
                }
                KeyCode::Char('n') | KeyCode::Esc | KeyCode::Char('q') => {
                    self.confirmation = None;
                    self.status_message = "Action cancelled".into();
                    None
                }
                _ => None,
            };
        }
        match key.code {
            KeyCode::Char('q') => self.should_quit = true,
            KeyCode::Char('1') => self.switch_to(View::Overview),
            KeyCode::Char('2') => self.switch_to(View::Jobs),
            KeyCode::Char('3') => self.switch_to(View::Work),
            KeyCode::Char('4') => self.switch_to(View::History),
            KeyCode::Char('5') => self.switch_to(View::Analytics),
            KeyCode::Char('6') => self.switch_to(View::System),
            KeyCode::Char('7') => return self.switch_to_translate(),
            KeyCode::Left | KeyCode::BackTab => self.switch_to(self.view.previous()),
            KeyCode::Right | KeyCode::Tab => self.switch_to(self.view.next()),
            KeyCode::Up if self.view == View::Jobs => {
                self.selected_job = self.selected_job.saturating_sub(1);
                self.set_selected_job_status();
            }
            KeyCode::Down if self.view == View::Jobs => {
                self.selected_job = (self.selected_job + 1)
                    .min(self.visible_available_jobs().len().saturating_sub(1));
                self.set_selected_job_status();
            }
            KeyCode::Up if self.view == View::History => {
                self.selected_history = self.selected_history.saturating_sub(1);
            }
            KeyCode::Down if self.view == View::History => {
                self.selected_history =
                    (self.selected_history + 1).min(self.data.jobs.len().saturating_sub(1));
            }
            KeyCode::PageUp if self.view == View::History => {
                self.selected_history = self.selected_history.saturating_sub(10);
            }
            KeyCode::PageDown if self.view == View::History => {
                self.selected_history =
                    (self.selected_history + 10).min(self.data.jobs.len().saturating_sub(1));
            }
            KeyCode::Up if self.view == View::Translate => {
                self.selected_translate = self.selected_translate.saturating_sub(1);
                self.clear_translate_selection_state();
                self.set_selected_translate_status();
            }
            KeyCode::Down if self.view == View::Translate => {
                self.selected_translate =
                    (self.selected_translate + 1).min(self.translate_runs.len().saturating_sub(1));
                self.clear_translate_selection_state();
                self.set_selected_translate_status();
            }
            KeyCode::Char('a') if self.view == View::Jobs => {
                if self.pending_destructive.is_some() {
                    self.status_message = "Wait for the pending action to finish…".into();
                } else if let Some(job) = self.selected_available_job() {
                    self.confirmation = Some(Confirmation::Accept(job.id.clone()));
                }
            }
            KeyCode::Char('o') if self.view == View::Overview && self.alert_visible => {
                self.switch_to(View::Jobs);
            }
            KeyCode::Char('d') if self.view == View::Overview && self.alert_visible => {
                self.alert_visible = false;
                self.status_message = "Alert dismissed · order remains in Available Jobs".into();
            }
            KeyCode::Char('i') if self.view == View::Jobs => {
                if let Some(job) = self.selected_available_job() {
                    let id = job.id.clone();
                    self.ignored_job_ids.insert(id.clone());
                    self.status_message = format!("Ignored order {id} for this session");
                    self.clamp_selection();
                }
            }
            KeyCode::Char('c') => {
                self.status_message = "Manual check requested…".into();
                return Some(UiAction::Refresh);
            }
            KeyCode::Char('v') => {
                self.layout = self.layout.next();
                self.status_message = format!("Layout: {}", self.layout.label());
            }
            KeyCode::Char('p') => {
                self.status_message = if self.paused {
                    "Resume requested…".into()
                } else {
                    "Pause requested…".into()
                };
                return Some(UiAction::Command(if self.paused {
                    "resume"
                } else {
                    "pause"
                }));
            }
            KeyCode::Char('x') if self.view == View::Work => {
                if self.pending_destructive.is_some() {
                    self.status_message = "Wait for the pending action to finish…".into();
                } else {
                    self.confirmation = Some(Confirmation::CancelCurrent);
                }
            }
            KeyCode::Char('t') if matches!(self.view, View::Jobs | View::Work) => {
                // Draft-only: copies the job title for translation. This never
                // accepts the job — acceptance stays on `a` + confirm.
                let drafted = if self.view == View::Jobs {
                    self.selected_available_job()
                        .map(|job| (job.id.clone(), job.display_title().to_owned()))
                } else {
                    self.data
                        .active_jobs()
                        .first()
                        .map(|job| (job.id.clone(), job.display_title().to_owned()))
                };
                let action = self.switch_to_translate();
                if let Some((id, title)) = drafted {
                    self.translate_draft = title;
                    self.draft_cursor = self.translate_draft.chars().count();
                    self.editing_draft = false;
                    if self.connection == ConnectionState::Demo {
                        self.status_message = format!(
                            "Demo data · draft filled from order {id} (NOT accepted) — e edits, s previews submit"
                        );
                    } else {
                        self.status_message = format!(
                            "Draft filled from order {id} · NOT accepted — e edits, s submits"
                        );
                    }
                }
                return action;
            }
            KeyCode::Char('e') if self.view == View::Translate => {
                self.editing_draft = true;
                self.draft_cursor = self.translate_draft.chars().count();
                self.status_message =
                    "Editing draft · type text, enter done, alt+enter newline, esc cancel".into();
            }
            KeyCode::Char('s') if self.view == View::Translate => {
                return self.open_translate_modal();
            }
            KeyCode::Char('r') if self.view == View::Translate => {
                if self.connection == ConnectionState::Demo {
                    self.status_message = "Demo data · translate list is static".into();
                    return None;
                }
                self.translate_loading = true;
                self.status_message = "Translate runs requested…".into();
                return Some(UiAction::RefreshTranslate);
            }
            KeyCode::Enter if self.view == View::Translate => {
                if let Some(run) = self.selected_translate_run() {
                    let run_id = run.run_id.clone();
                    if self.connection == ConnectionState::Demo {
                        self.translate_detail = Some(TranslateRunDetail::demo(&run_id));
                        self.status_message = "Translate detail loaded · demo".into();
                        return None;
                    }
                    self.translate_loading = true;
                    self.status_message = "Translate detail requested…".into();
                    self.pending_translate_detail = Some(run_id.clone());
                    return Some(UiAction::GetTranslateDetail(run_id));
                }
            }
            _ => {}
        }
        None
    }

    pub fn handle_mouse(&mut self, event: MouseEvent) {
        if event.kind != MouseEventKind::Down(MouseButton::Left) {
            return;
        }
        let point = (event.column, event.row);
        if let Some(view) = self
            .nav_hitboxes
            .iter()
            .find_map(|(area, view)| contains(*area, point).then_some(*view))
        {
            self.switch_to(view);
        }
    }

    fn switch_to(&mut self, view: View) {
        self.view = view;
        self.status_message = format!("{} workspace", view.label());
    }

    fn switch_to_translate(&mut self) -> Option<UiAction> {
        self.view = View::Translate;
        self.clamp_translate_selection();
        if self.connection == ConnectionState::Demo {
            self.status_message = "Translate workspace · demo data".into();
            return None;
        }
        self.translate_loading = true;
        self.status_message = "Translate runs requested…".into();
        Some(UiAction::RefreshTranslate)
    }

    fn open_translate_modal(&mut self) -> Option<UiAction> {
        if self.translate_draft.trim().is_empty() {
            self.status_message = "Draft is empty · e edits, t fills from a job".into();
            return None;
        }
        self.editing_draft = false;
        self.translate_modal = true;
        if self.connection == ConnectionState::Demo {
            self.status_message = "Submit preview · demo data, submit disabled".into();
            return None;
        }
        if !self.translate_models.is_empty() || self.translate_models_loading {
            self.status_message =
                "Submit modal · 1-9 toggle models, r review, enter submits".into();
            return None;
        }
        self.translate_models_loading = true;
        self.status_message = "Translate models requested…".into();
        Some(UiAction::FetchTranslateModels)
    }

    fn handle_translate_modal_key(&mut self, key: KeyEvent) -> Option<UiAction> {
        // Held keys must not flicker toggles.
        if key.kind == KeyEventKind::Repeat {
            return None;
        }
        match key.code {
            KeyCode::Esc | KeyCode::Char('n') | KeyCode::Char('q') => {
                self.translate_modal = false;
                self.status_message = "Translate submit cancelled".into();
                None
            }
            KeyCode::Enter | KeyCode::Char('y') => self.confirm_translate_submit(),
            KeyCode::Char('r') => {
                self.translate_with_review = !self.translate_with_review;
                self.status_message = format!(
                    "Review pass {}",
                    if self.translate_with_review {
                        "on"
                    } else {
                        "off"
                    }
                );
                None
            }
            KeyCode::Char('a') => {
                if self.translate_models.is_empty() {
                    self.status_message = "No models loaded · esc then s to retry".into();
                } else {
                    self.translate_models_selected.fill(true);
                    self.status_message = "All models selected".into();
                }
                None
            }
            KeyCode::Char(character) if character.is_ascii_digit() => {
                self.toggle_translate_model(character);
                None
            }
            _ => None,
        }
    }

    fn toggle_translate_model(&mut self, digit: char) {
        if self.translate_models.is_empty() {
            self.status_message = "No models loaded · esc then s to retry".into();
            return;
        }
        let index = (digit as usize).saturating_sub('0' as usize);
        if index == 0 || index > self.translate_models.len() {
            self.status_message = "No model at that number".into();
            return;
        }
        let slot = &mut self.translate_models_selected[index - 1];
        *slot = !*slot;
        let name = self.translate_models[index - 1].clone();
        self.status_message = format!(
            "Model {name} {}",
            if *slot { "selected" } else { "skipped" }
        );
    }

    fn confirm_translate_submit(&mut self) -> Option<UiAction> {
        if self.connection == ConnectionState::Demo {
            self.translate_modal = false;
            self.status_message = "Demo data · submit is disabled".into();
            return None;
        }
        if self.submit_pending {
            self.status_message = "Submit already in flight…".into();
            return None;
        }
        if self.translate_draft.trim().is_empty() {
            self.translate_modal = false;
            self.status_message = "Draft is empty · submit cancelled".into();
            return None;
        }
        let selected: Vec<String> = self
            .translate_models
            .iter()
            .zip(self.translate_models_selected.iter())
            .filter(|(_, selected)| **selected)
            .map(|(name, _)| name.clone())
            .collect();
        if !self.translate_models.is_empty() && selected.is_empty() {
            self.status_message = "Select at least one model · 1-9 toggle, a all".into();
            return None;
        }
        // All (or unknown, when the models fetch failed) means server default.
        let models = if selected.len() == self.translate_models.len() {
            None
        } else {
            Some(selected)
        };
        self.translate_modal = false;
        self.editing_draft = false;
        self.submit_pending = true;
        self.translate_loading = true;
        self.status_message = "Translate run submitting…".into();
        Some(UiAction::StartTranslate {
            text: self.translate_draft.clone(),
            models,
            with_review: self.translate_with_review,
        })
    }

    fn handle_draft_edit_key(&mut self, key: KeyEvent) {
        match key.code {
            KeyCode::Enter if key.modifiers.contains(KeyModifiers::ALT) => {
                let byte = draft_byte_index(&self.translate_draft, self.draft_cursor);
                self.translate_draft.insert(byte, '\n');
                self.draft_cursor += 1;
            }
            KeyCode::Esc | KeyCode::Enter => {
                self.editing_draft = false;
                let chars = self.translate_draft.chars().count();
                self.status_message = format!("Draft updated · {chars} chars · s submits");
            }
            KeyCode::Left => {
                self.draft_cursor = self.draft_cursor.saturating_sub(1);
            }
            KeyCode::Right => {
                let end = self.translate_draft.chars().count();
                self.draft_cursor = (self.draft_cursor + 1).min(end);
            }
            KeyCode::Home => self.draft_cursor = 0,
            KeyCode::End => self.draft_cursor = self.translate_draft.chars().count(),
            KeyCode::Backspace if self.draft_cursor > 0 => {
                let byte = draft_byte_index(&self.translate_draft, self.draft_cursor - 1);
                self.translate_draft.remove(byte);
                self.draft_cursor -= 1;
            }
            KeyCode::Backspace => {}
            KeyCode::Delete => {
                let end = self.translate_draft.chars().count();
                if self.draft_cursor < end {
                    let byte = draft_byte_index(&self.translate_draft, self.draft_cursor);
                    self.translate_draft.remove(byte);
                }
            }
            KeyCode::Char(character)
                if key.modifiers.is_empty() || key.modifiers == KeyModifiers::SHIFT =>
            {
                let byte = draft_byte_index(&self.translate_draft, self.draft_cursor);
                self.translate_draft.insert(byte, character);
                self.draft_cursor += 1;
            }
            _ => {}
        }
        let end = self.translate_draft.chars().count();
        self.draft_cursor = self.draft_cursor.min(end);
    }

    fn set_selected_translate_status(&mut self) {
        if let Some(run) = self.selected_translate_run() {
            self.status_message = format!(
                "Selected run {} · {} · {} chars",
                run.run_id, run.kind, run.char_count
            );
        } else {
            self.status_message = "No translate runs yet".into();
        }
    }

    fn set_selected_job_status(&mut self) {
        if let Some(job) = self.selected_available_job() {
            self.status_message = format!(
                "Selected order {} · {} · {}",
                job.id,
                job.display_title(),
                job.display_value()
            );
        }
    }

    fn visible_available_jobs(&self) -> Vec<&Job> {
        self.data
            .available_jobs()
            .into_iter()
            .filter(|job| !self.ignored_job_ids.contains(&job.id))
            .collect()
    }

    fn selected_available_job(&self) -> Option<&Job> {
        self.visible_available_jobs()
            .get(self.selected_job)
            .copied()
    }

    fn clamp_selection(&mut self) {
        self.selected_job = self
            .selected_job
            .min(self.visible_available_jobs().len().saturating_sub(1));
        self.selected_history = self
            .selected_history
            .min(self.data.jobs.len().saturating_sub(1));
        self.clamp_translate_selection();
    }
}

fn draft_byte_index(text: &str, cursor: usize) -> usize {
    text.char_indices()
        .nth(cursor)
        .map_or(text.len(), |(index, _)| index)
}

fn is_repeatable_key(code: KeyCode) -> bool {
    matches!(
        code,
        KeyCode::Left
            | KeyCode::Right
            | KeyCode::Tab
            | KeyCode::BackTab
            | KeyCode::Up
            | KeyCode::Down
            | KeyCode::PageUp
            | KeyCode::PageDown
            | KeyCode::Char('1'..='7')
    )
}

const fn contains(area: Rect, (x, y): (u16, u16)) -> bool {
    x >= area.x
        && x < area.x.saturating_add(area.width)
        && y >= area.y
        && y < area.y.saturating_add(area.height)
}

pub fn render(frame: &mut Frame<'_>, app: &mut App) {
    frame.render_widget(
        Block::default().style(Style::default().bg(GROUND).fg(INK)),
        frame.area(),
    );
    match app.layout {
        LayoutKind::Classic => render_classic(frame, app),
        LayoutKind::Beacon | LayoutKind::Dense => render_tabbed(frame, app),
    }
    if app.confirmation.is_some() {
        render_confirmation(frame, app);
    }
}

fn render_classic(frame: &mut Frame<'_>, app: &mut App) {
    let shell = Layout::vertical([
        Constraint::Length(3),
        Constraint::Min(1),
        Constraint::Length(2),
        Constraint::Length(1),
    ])
    .split(frame.area());
    render_header(frame, shell[0], app);

    if frame.area().width < 110 || frame.area().height < 30 {
        render_compact(frame, shell[1], app);
    } else {
        let nav_width = if shell[1].width >= 120 { 24 } else { 20 };
        let body = Layout::horizontal([Constraint::Length(nav_width), Constraint::Min(50)])
            .split(shell[1]);
        render_nav(frame, body[0], app);
        render_workspace(frame, body[1], app);
    }
    render_status(frame, shell[2], app);
    render_footer(frame, shell[3]);
}

/// Tabbed chrome shared by the Beacon and Dense layouts: header, one-row
/// tab bar with live session totals, body, status, footer.
fn render_tabbed(frame: &mut Frame<'_>, app: &mut App) {
    let shell = Layout::vertical([
        Constraint::Length(3),
        Constraint::Length(1),
        Constraint::Min(1),
        Constraint::Length(2),
        Constraint::Length(1),
    ])
    .split(frame.area());
    render_header(frame, shell[0], app);
    render_tabbar(frame, shell[1], app);
    if frame.area().width < 110 || frame.area().height < 30 {
        render_compact(frame, shell[2], app);
    } else if app.layout == LayoutKind::Beacon {
        render_beacon_body(frame, shell[2], app);
    } else {
        render_dense_body(frame, shell[2], app);
    }
    render_status(frame, shell[3], app);
    render_footer(frame, shell[4]);
}

fn render_tabbar(frame: &mut Frame<'_>, area: Rect, app: &mut App) {
    frame.render_widget(Block::default().style(Style::default().bg(NAV_BG)), area);
    let mut spans = Vec::new();
    let mut hitboxes: Vec<(Rect, View)> = Vec::new();
    let mut cursor = area.x.saturating_add(1);
    for (index, view) in View::ALL.into_iter().enumerate() {
        let selected = app.view == view;
        let text = format!(" {} {} ", index + 1, view.label());
        let width = text.chars().count() as u16;
        if cursor + width > area.x + area.width.saturating_sub(42) {
            break;
        }
        let style = if selected {
            selection_style()
        } else {
            Style::default().fg(INK)
        };
        let mut tab_spans = vec![Span::styled(
            format!(" {} ", index + 1),
            Style::default().fg(if selected { INK } else { MUTED }),
        )];
        if selected {
            tab_spans[0].style = tab_spans[0].style.bg(SELECTION);
        }
        tab_spans.push(Span::styled(format!("{} ", view.label()), style));
        spans.extend(tab_spans);
        spans.push(Span::raw(" "));
        hitboxes.push((Rect::new(cursor, area.y, width.saturating_add(1), 1), view));
        cursor += width + 1;
    }
    app.nav_hitboxes.clear();
    app.nav_hitboxes.extend(hitboxes);
    let used = cursor.saturating_sub(area.x);
    let session_full = format!(
        "${:.2} · {} accepted · {} seen",
        app.data.status.session_stats.total_value,
        app.data.accepted_count(),
        app.data.status.session_stats.new_entries,
    );
    let session_room = area.width.saturating_sub(used).saturating_sub(2).max(8) as usize;
    let session = truncate(&session_full, session_room);
    let right = Line::from(Span::styled(session, Style::default().fg(MUTED)));
    let right_width = right.width() as u16 + 1;
    let tabs_width = area.width.saturating_sub(right_width).max(used);
    let columns =
        Layout::horizontal([Constraint::Length(tabs_width), Constraint::Min(1)]).split(area);
    frame.render_widget(
        Paragraph::new(Line::from(spans)).style(Style::default().bg(NAV_BG)),
        columns[0],
    );
    frame.render_widget(
        Paragraph::new(right)
            .style(Style::default().bg(NAV_BG))
            .alignment(Alignment::Right),
        columns[1],
    );
}

fn render_header(frame: &mut Frame<'_>, area: Rect, app: &App) {
    let columns = Layout::horizontal([Constraint::Percentage(55), Constraint::Percentage(45)])
        .split(area.inner(Margin::new(2, 0)));
    frame.render_widget(Block::default().style(Style::default().bg(CANOPY)), area);
    let (state, state_color) = match &app.connection {
        ConnectionState::Demo => ("● demo data", LAVENDER),
        ConnectionState::Connecting => ("● connecting to API", ORANGE),
        ConnectionState::Reconnecting(_) => ("● API reconnecting", RED),
        ConnectionState::Live if app.paused => ("● monitoring paused", ORANGE),
        ConnectionState::Live if !app.data.status.is_running => ("● watcher stopped", RED),
        ConnectionState::Live => ("● all monitors operational", LEAF),
    };
    let next_check = seconds_until(app.data.status.next_check_time, app.data.fetched_at);
    frame.render_widget(
        Paragraph::new(vec![
            Line::from(vec![
                Span::styled(
                    "GENGOWATCHER",
                    Style::default().fg(INK).add_modifier(Modifier::BOLD),
                ),
                Span::styled("  translation operations", Style::default().fg(MUTED)),
            ]),
            Line::from(Span::styled(
                format!(
                    "{} jobs loaded · next check {}",
                    app.data.jobs.len(),
                    format_duration(next_check)
                ),
                Style::default().fg(MUTED),
            )),
        ]),
        columns[0],
    );
    frame.render_widget(
        Paragraph::new(vec![
            Line::from(Span::styled(
                state,
                Style::default()
                    .fg(state_color)
                    .add_modifier(Modifier::BOLD),
            )),
            Line::from(Span::styled(
                format!(
                    "{} · {}",
                    app.view.label(),
                    connection_label(&app.connection)
                ),
                Style::default().fg(MUTED),
            )),
        ])
        .alignment(Alignment::Right),
        columns[1],
    );
}

fn render_nav(frame: &mut Frame<'_>, area: Rect, app: &mut App) {
    frame.render_widget(
        Block::default()
            .borders(Borders::RIGHT)
            .border_style(Style::default().fg(LINE))
            .style(Style::default().bg(NAV_BG)),
        area,
    );
    let inner = area.inner(Margin::new(1, 1));
    let rows = Layout::vertical([
        Constraint::Length(2),
        Constraint::Length(3),
        Constraint::Length(3),
        Constraint::Length(3),
        Constraint::Length(3),
        Constraint::Length(3),
        Constraint::Length(3),
        Constraint::Length(3),
        Constraint::Min(1),
        Constraint::Length(6),
    ])
    .split(inner);
    frame.render_widget(
        Paragraph::new("WORKSPACES").style(Style::default().fg(MUTED).add_modifier(Modifier::BOLD)),
        rows[0],
    );
    app.nav_hitboxes.clear();
    for (index, view) in View::ALL.into_iter().enumerate() {
        let selected = app.view == view;
        let row_bg = if selected { SELECTION } else { NAV_BG };
        let marker = if selected { "▶" } else { " " };
        frame.render_widget(
            Paragraph::new(Line::from(vec![
                Span::styled(
                    format!("{marker} {}  ", index + 1),
                    Style::default().fg(if selected { INK } else { MUTED }),
                ),
                Span::styled(
                    view.label().to_owned(),
                    if selected {
                        selection_style()
                    } else {
                        Style::default().fg(INK)
                    },
                ),
            ]))
            .style(Style::default().bg(row_bg))
            .alignment(Alignment::Left),
            rows[index + 1],
        );
        app.nav_hitboxes.push((rows[index + 1], view));
    }
    frame.render_widget(
        Paragraph::new(vec![
            Line::from(Span::styled(
                "SESSION",
                Style::default().fg(MUTED).add_modifier(Modifier::BOLD),
            )),
            Line::from(vec![
                Span::styled(
                    app.data.status.session_stats.new_entries.to_string(),
                    value_style(),
                ),
                Span::styled(" detected", Style::default().fg(MUTED)),
            ]),
            Line::from(vec![
                Span::styled(app.data.accepted_count().to_string(), value_style()),
                Span::styled(" accepted", Style::default().fg(MUTED)),
            ]),
            Line::from(vec![
                Span::styled(
                    format!("${:.2}", app.data.status.session_stats.total_value),
                    Style::default().fg(LEAF).add_modifier(Modifier::BOLD),
                ),
                Span::styled(" value", Style::default().fg(MUTED)),
            ]),
        ])
        .style(Style::default().fg(MUTED).bg(NAV_BG)),
        rows[9],
    );
}

fn render_confirmation(frame: &mut Frame<'_>, app: &App) {
    let area = centered_rect(58, 9, frame.area());
    frame.render_widget(Clear, area);
    let (question, detail) = match app.confirmation.as_ref() {
        Some(Confirmation::Accept(job_id)) => (
            format!("Accept order {job_id}?"),
            "This sends an acceptance request to GengoWatcher.",
        ),
        Some(Confirmation::CancelCurrent) => (
            "Cancel the current active job?".into(),
            "This cannot be undone from the TUI.",
        ),
        None => return,
    };
    frame.render_widget(
        Paragraph::new(vec![
            Line::from(Span::styled(
                question,
                Style::default().fg(INK).add_modifier(Modifier::BOLD),
            )),
            Line::from(Span::styled(detail, Style::default().fg(MUTED))),
            Line::from(""),
            Line::from(vec![
                button_solid("y", "CONFIRM"),
                Span::raw("  "),
                button_ghost("n", "CANCEL"),
            ]),
            Line::from(""),
            Line::from(Span::styled(
                "y / enter confirm · n / esc cancel",
                Style::default().fg(MUTED),
            )),
        ])
        .block(
            Block::default()
                .borders(Borders::ALL)
                .border_type(BorderType::Rounded)
                .border_style(Style::default().fg(ORANGE))
                .title(Span::styled(
                    " CONFIRM ACTION ",
                    Style::default().fg(ORANGE).add_modifier(Modifier::BOLD),
                )),
        )
        .style(Style::default().fg(INK).bg(PAPER))
        .alignment(Alignment::Center)
        .wrap(Wrap { trim: true }),
        area,
    );
}

fn render_workspace(frame: &mut Frame<'_>, area: Rect, app: &mut App) {
    let inner = area.inner(Margin::new(2, 1));
    let parts = Layout::vertical([Constraint::Length(2), Constraint::Min(1)]).split(inner);
    frame.render_widget(
        Paragraph::new(app.view.label().to_uppercase())
            .style(Style::default().fg(LEAF).add_modifier(Modifier::BOLD)),
        parts[0],
    );
    match app.view {
        View::Overview => render_overview(frame, parts[1], app),
        View::Jobs => render_jobs(frame, parts[1], app),
        View::Work => render_work(frame, parts[1], app),
        View::History => render_history(frame, parts[1], app),
        View::Analytics => render_analytics(frame, parts[1], app),
        View::System => render_system(frame, parts[1], app),
        View::Translate => render_translate(frame, parts[1], app),
    }
}

/// View content without the classic masthead, for tabbed layouts where the
/// tab bar already names the active view.
fn render_view_body(frame: &mut Frame<'_>, area: Rect, app: &mut App) {
    match app.view {
        View::Overview => render_overview(frame, area, app),
        View::Jobs => render_jobs(frame, area, app),
        View::Work => render_work(frame, area, app),
        View::History => render_history(frame, area, app),
        View::Analytics => render_analytics(frame, area, app),
        View::System => render_system(frame, area, app),
        View::Translate => render_translate(frame, area, app),
    }
}

fn render_beacon_body(frame: &mut Frame<'_>, area: Rect, app: &mut App) {
    match app.view {
        View::Overview => render_ops(frame, area, app),
        _ => render_view_body(frame, area, app),
    }
}

fn render_dense_body(frame: &mut Frame<'_>, area: Rect, app: &mut App) {
    render_view_body(frame, area, app)
}

impl App {
    /// Tabbed layouts use single-row tables to double visible density.
    const fn compact_rows(&self) -> bool {
        !matches!(self.layout, LayoutKind::Classic)
    }
}

fn render_overview(frame: &mut Frame<'_>, area: Rect, app: &App) {
    let alert_height = if app.alert_visible { 5 } else { 3 };
    let rows = Layout::vertical([
        Constraint::Length(alert_height),
        Constraint::Length(1),
        Constraint::Min(12),
    ])
    .split(area);
    let available = app.visible_available_jobs();
    let alert_job = available.first().copied();
    if let (true, Some(job)) = (app.alert_visible, alert_job) {
        frame.render_widget(
            Block::default()
                .borders(Borders::ALL)
                .border_type(BorderType::Rounded)
                .border_style(Style::default().fg(ORANGE))
                .style(Style::default().bg(ORANGE_BG)),
            rows[0],
        );
        frame.render_widget(
            Paragraph::new(vec![
                Line::from(Span::styled(
                    "▲ NEW JOB AVAILABLE",
                    Style::default().fg(ORANGE).add_modifier(Modifier::BOLD),
                )),
                Line::from(Span::styled(
                    format!("{}  ·  {}", job.display_value(), job.display_title()),
                    Style::default().fg(INK).add_modifier(Modifier::BOLD),
                )),
                Line::from(vec![
                    Span::styled(
                        format!("Order {}  ·  {}  ·  ", job.id, job.source,),
                        Style::default().fg(MUTED),
                    ),
                    time_left_span(job),
                    Span::styled(" remaining   ", Style::default().fg(MUTED)),
                    button_solid("o", "VIEW"),
                    Span::raw(" "),
                    button_ghost("d", "DISMISS"),
                ]),
            ])
            .block(Block::default().style(Style::default().bg(ORANGE_BG)))
            .alignment(Alignment::Left),
            rows[0].inner(Margin::new(2, 0)),
        );
    } else {
        frame.render_widget(
            Paragraph::new(format!(
                "○ No current alert · {} jobs remain available",
                available.len()
            ))
            .style(Style::default().fg(MUTED).bg(PAPER))
            .block(panel_block()),
            rows[0],
        );
    }
    let main = Layout::vertical([Constraint::Min(10), Constraint::Length(4)]).split(rows[2]);
    let columns =
        Layout::horizontal([Constraint::Percentage(62), Constraint::Percentage(38)]).split(main[0]);
    let side = Layout::vertical([Constraint::Percentage(50), Constraint::Percentage(50)])
        .split(columns[1]);
    render_available_summary(frame, inset_right(columns[0]), app);
    render_work_summary(frame, inset_left(side[0]), app);
    render_system_summary(frame, inset_left(side[1]), app);
    render_metric_strip(frame, main[1], app);
}

/// Beacon ops screen: one hero opportunity, the live queue, and an action
/// rail. Everything the accept/ignore loop needs, no view switching.
fn render_ops(frame: &mut Frame<'_>, area: Rect, app: &mut App) {
    let rows = Layout::vertical([
        Constraint::Length(6),
        Constraint::Min(8),
        Constraint::Length(2),
    ])
    .split(area);
    render_hero(frame, rows[0], app);
    let main = Layout::horizontal([Constraint::Min(60), Constraint::Length(40)]).split(rows[1]);
    render_queue(frame, inset_right(main[0]), app);
    render_rail(frame, inset_left(main[1]), app);
    render_ops_strip(frame, rows[2], app);
}

fn render_hero(frame: &mut Frame<'_>, area: Rect, app: &App) {
    let available = app.visible_available_jobs();
    let Some(job) = available.first().copied() else {
        frame.render_widget(
            Paragraph::new(Span::styled(
                format!(
                    "○ Watching · {} jobs seen · next check {}",
                    app.data.jobs.len(),
                    format_duration(seconds_until(
                        app.data.status.next_check_time,
                        app.data.fetched_at
                    )),
                ),
                Style::default().fg(MUTED),
            ))
            .block(panel_block()),
            area,
        );
        return;
    };
    frame.render_widget(
        Block::default()
            .borders(Borders::ALL)
            .border_type(BorderType::Rounded)
            .border_style(Style::default().fg(ORANGE))
            .style(Style::default().bg(ORANGE_BG)),
        area,
    );
    frame.render_widget(
        Paragraph::new(vec![
            Line::from(vec![
                Span::styled(
                    "▲ BEST OPPORTUNITY  ",
                    Style::default().fg(ORANGE).add_modifier(Modifier::BOLD),
                ),
                Span::styled(
                    format!("{}  ·  {}", job.display_value(), job.display_title()),
                    Style::default().fg(INK).add_modifier(Modifier::BOLD),
                ),
            ]),
            Line::from(vec![
                Span::styled(
                    format!("Order {}  ·  {}  ·  ", job.id, job.source,),
                    Style::default().fg(MUTED),
                ),
                time_left_span(job),
                Span::styled(" left   ", Style::default().fg(MUTED)),
                button_solid("a", "ACCEPT"),
                Span::raw(" "),
                button_danger("i", "IGNORE"),
            ]),
        ])
        .block(Block::default().style(Style::default().bg(ORANGE_BG)))
        .alignment(Alignment::Left),
        area.inner(Margin::new(2, 1)),
    );
}

fn render_queue(frame: &mut Frame<'_>, area: Rect, app: &mut App) {
    let jobs = app.visible_available_jobs();
    let header = Row::new(["ORDER", "JOB", "VALUE", "TIME", "SRC"]).style(table_header_style());
    let rows = jobs
        .iter()
        .map(|job| {
            Row::new([
                Cell::from(job.id.clone()),
                Cell::from(truncate(job.display_title(), 34)),
                Cell::from(job.display_value()),
                Cell::from(time_left_span(job)),
                Cell::from(job.source.clone()),
            ])
        })
        .collect::<Vec<_>>();
    let table = Table::new(
        rows,
        [
            Constraint::Length(8),
            Constraint::Min(20),
            Constraint::Length(8),
            Constraint::Length(7),
            Constraint::Length(10),
        ],
    )
    .header(header)
    .row_highlight_style(selection_style())
    .highlight_symbol("▶ ")
    .block(counted_panel("QUEUE", jobs.len()))
    .column_spacing(1);
    let mut state = TableState::default().with_selected(Some(app.selected_job));
    frame.render_stateful_widget(table, area, &mut state);
}

fn render_rail(frame: &mut Frame<'_>, area: Rect, app: &App) {
    let parts = Layout::vertical([
        Constraint::Min(10),
        Constraint::Length(6),
        Constraint::Min(5),
    ])
    .split(area);
    render_act_card(frame, parts[0], app);
    render_stages_card(frame, parts[1], app);
    render_health_card(frame, parts[2], app);
}

fn render_act_card(frame: &mut Frame<'_>, area: Rect, app: &App) {
    let jobs = app.visible_available_jobs();
    let body = jobs.get(app.selected_job).copied().map_or_else(
        || Text::from(Span::styled("No job selected", Style::default().fg(MUTED))),
        |job| {
            Text::from(vec![
                Line::from(vec![
                    Span::styled(
                        format!("{}  ", job.display_value()),
                        Style::default().fg(LEAF).add_modifier(Modifier::BOLD),
                    ),
                    Span::styled(
                        truncate(job.display_title(), 26),
                        Style::default().fg(INK).add_modifier(Modifier::BOLD),
                    ),
                ]),
                Line::from(vec![
                    Span::styled(
                        format!("Order {} · {} · ", job.id, job.source,),
                        Style::default().fg(MUTED),
                    ),
                    time_left_span(job),
                    Span::styled(" left", Style::default().fg(MUTED)),
                ]),
                Line::from(""),
                Line::from(vec![
                    button_solid("a", "ACCEPT"),
                    Span::raw(" "),
                    button_danger("i", "IGNORE"),
                ]),
            ])
        },
    );
    frame.render_widget(
        Paragraph::new(body)
            .block(titled_panel("ACT"))
            .style(Style::default().fg(INK).bg(PAPER))
            .wrap(Wrap { trim: true }),
        area,
    );
}

fn render_stages_card(frame: &mut Frame<'_>, area: Rect, app: &App) {
    let active = app.data.active_jobs();
    let count = |stage| {
        active
            .iter()
            .filter(|job| job.work_stage() == stage)
            .count()
    };
    let peak = active.len().max(1);
    let row = |label: &str, stage, accent: ratatui::style::Color| {
        let total = count(stage);
        Line::from(vec![
            Span::styled(format!("{label:<10}"), Style::default().fg(MUTED)),
            Span::styled(
                format!("{total:>2} "),
                Style::default().fg(accent).add_modifier(Modifier::BOLD),
            ),
            Span::styled(bar(total, peak, 8), Style::default().fg(accent)),
        ])
    };
    frame.render_widget(
        Paragraph::new(vec![
            row("READY", WorkStage::Ready, LEAF),
            row("ACTIVE", WorkStage::InProgress, ORANGE),
            row("REVIEW", WorkStage::Review, LAVENDER),
        ])
        .block(counted_panel("WORK", active.len()))
        .style(Style::default().fg(INK).bg(PAPER)),
        area,
    );
}

fn render_health_card(frame: &mut Frame<'_>, area: Rect, app: &App) {
    let mut lines = health_summary_lines(app);
    lines.truncate(3);
    lines.push(Line::from(Span::styled(
        format!(
            "${:.2} session · {} accepted",
            app.data.status.session_stats.total_value,
            app.data.accepted_count()
        ),
        Style::default().fg(MUTED),
    )));
    frame.render_widget(
        Paragraph::new(lines)
            .block(titled_panel("HEALTH"))
            .style(Style::default().bg(PAPER)),
        area,
    );
}

fn render_ops_strip(frame: &mut Frame<'_>, area: Rect, app: &App) {
    let total = app.data.jobs.len();
    let accepted = app.data.accepted_count();
    let accept_rate = if total == 0 {
        0.0
    } else {
        accepted as f64 / total as f64 * 100.0
    };
    frame.render_widget(
        Paragraph::new(Line::from(vec![
            Span::styled("VALUE ", Style::default().fg(MUTED)),
            Span::styled(
                format!("${:.2}  ", app.data.status.session_stats.total_value),
                value_style(),
            ),
            Span::styled("ACCEPT ", Style::default().fg(MUTED)),
            Span::styled(format!("{accept_rate:.1}%  "), value_style()),
            Span::styled(source_sparkline(&app.data), Style::default().fg(BLUE)),
        ]))
        .style(Style::default().bg(GROUND)),
        area,
    );
}

fn render_available_summary(frame: &mut Frame<'_>, area: Rect, app: &App) {
    let jobs = app.visible_available_jobs();
    let rows = usize::from(area.height.saturating_sub(2));
    let items = jobs
        .iter()
        .take(rows)
        .map(|job| {
            ListItem::new(Line::from(vec![
                Span::styled(
                    format!("{:<8}", job.display_value()),
                    Style::default().fg(LEAF).add_modifier(Modifier::BOLD),
                ),
                Span::styled(
                    format!("{:<30}", truncate(job.display_title(), 30)),
                    Style::default().fg(INK),
                ),
                padded_time_left_span(job),
                Span::styled(job.source.clone(), Style::default().fg(MUTED)),
            ]))
        })
        .collect::<Vec<_>>();
    frame.render_widget(
        List::new(items)
            .block(counted_panel("AVAILABLE JOBS", jobs.len()))
            .style(Style::default().fg(INK).bg(PAPER)),
        area,
    );
}

fn render_work_summary(frame: &mut Frame<'_>, area: Rect, app: &App) {
    let active = app.data.active_jobs();
    let count = |stage| {
        active
            .iter()
            .filter(|job| job.work_stage() == stage)
            .count()
    };
    let peak = active.len().max(1);
    let row = |label: &str, stage| {
        let total = count(stage);
        Line::from(vec![
            Span::styled(format!("{label:<14}"), Style::default().fg(MUTED)),
            Span::styled(
                format!("{total:>2} "),
                Style::default().fg(INK).add_modifier(Modifier::BOLD),
            ),
            Span::styled(bar(total, peak, 10), Style::default().fg(LEAF)),
        ])
    };
    frame.render_widget(
        Paragraph::new(vec![
            row("READY TO START", WorkStage::Ready),
            row("IN PROGRESS", WorkStage::InProgress),
            row("REVIEW REQUIRED", WorkStage::Review),
        ])
        .block(counted_panel("ACTIVE WORK", active.len()))
        .style(Style::default().fg(INK).bg(PAPER)),
        area,
    );
}

/// Full-width session analytics strip: headline metrics on one line,
///
/// source volume on the next.
fn render_metric_strip(frame: &mut Frame<'_>, area: Rect, app: &App) {
    let total = app.data.jobs.len();
    let accepted = app.data.accepted_count();
    let accept_rate = if total == 0 {
        0.0
    } else {
        accepted as f64 / total as f64 * 100.0
    };
    let uptime_hours = (app.data.status.session_stats.uptime / 3600.0).max(1.0 / 60.0);
    let pace = f64::from(app.data.status.session_stats.new_entries as u32) / uptime_hours;
    let metric = |label: &str, value: String| {
        vec![
            Span::styled(format!("{label} "), Style::default().fg(MUTED)),
            Span::styled(value, value_style()),
            Span::raw("    "),
        ]
    };
    let mut headline = Vec::new();
    headline.extend(metric(
        "VALUE",
        format!("${:.2}", app.data.status.session_stats.total_value),
    ));
    headline.extend(metric("ACCEPT", format!("{accept_rate:.1}%")));
    headline.extend(metric("PACE", format!("{pace:.1}/h")));
    headline.extend(metric(
        "AVG",
        format!("${:.2}", app.data.stats.average_reward),
    ));
    frame.render_widget(
        Paragraph::new(vec![
            Line::from(headline),
            Line::from(Span::styled(
                source_sparkline(&app.data),
                Style::default().fg(BLUE),
            )),
        ])
        .block(titled_panel("SESSION ANALYTICS"))
        .style(Style::default().fg(INK).bg(PAPER)),
        area,
    );
}

fn render_system_summary(frame: &mut Frame<'_>, area: Rect, app: &App) {
    let health_lines = health_summary_lines(app);
    let event_lines = app
        .data
        .events
        .iter()
        .rev()
        .take(3)
        .map(event_line)
        .collect::<Vec<_>>();
    let mut lines = health_lines;
    lines.push(Line::from(""));
    lines.extend(event_lines);
    frame.render_widget(
        Paragraph::new(lines)
            .block(titled_panel("SYSTEM & ACTIVITY"))
            .style(Style::default().bg(PAPER)),
        area,
    );
}

fn render_jobs(frame: &mut Frame<'_>, area: Rect, app: &mut App) {
    let row_height = if app.compact_rows() { 1 } else { 2 };
    let columns = Layout::horizontal([Constraint::Min(62), Constraint::Length(36)]).split(area);
    let header = Row::new(["ORDER", "JOB", "VALUE", "SOURCE", "STATUS", "TIME"])
        .style(table_header_style())
        .height(row_height);
    let jobs = app.visible_available_jobs();
    let selected = jobs.get(app.selected_job).copied().cloned();
    let rows = jobs
        .iter()
        .map(|job| {
            Row::new([
                Cell::from(job.id.clone()),
                Cell::from(truncate(job.display_title(), 28)),
                Cell::from(job.display_value()),
                Cell::from(job.source.clone()),
                Cell::from(job.display_status().to_owned()),
                Cell::from(time_left_span(job)),
            ])
            .height(row_height)
        })
        .collect::<Vec<_>>();
    let table = Table::new(
        rows,
        [
            Constraint::Length(8),
            Constraint::Min(18),
            Constraint::Length(8),
            Constraint::Length(11),
            Constraint::Length(10),
            Constraint::Length(7),
        ],
    )
    .header(header)
    .row_highlight_style(selection_style())
    .highlight_symbol("▶ ")
    .block(panel_block())
    .column_spacing(1);
    let mut state = TableState::default().with_selected(Some(app.selected_job));
    frame.render_stateful_widget(table, inset_right(columns[0]), &mut state);
    let detail = selected.map_or_else(
        || Text::from("No available jobs"),
        |job| {
            let mut lines = vec![
                Line::from(Span::styled(
                    job.display_value(),
                    Style::default().fg(INK).add_modifier(Modifier::BOLD),
                )),
                Line::from(job.display_title().to_owned()),
                Line::from(""),
                detail_owned("Order", job.id.clone()),
                detail_owned("Source", job.source.clone()),
                detail_owned("Status", job.display_status().to_owned()),
                detail_owned("Time left", job.display_time_left()),
            ];
            if let Some(characters) = job.accepted_source_char_count {
                lines.push(detail_owned("Source chars", characters.to_string()));
            }
            if let Some(segments) = job.accepted_segment_count {
                lines.push(detail_owned("Segments", segments.to_string()));
            }
            lines.extend([
                Line::from(""),
                Line::from(vec![
                    button_solid("a", "ACCEPT"),
                    Span::raw("  "),
                    button_danger("i", "IGNORE"),
                ]),
            ]);
            Text::from(lines)
        },
    );
    frame.render_widget(
        Paragraph::new(detail)
            .block(titled_panel("SELECTED JOB"))
            .style(Style::default().fg(INK).bg(PAPER))
            .wrap(Wrap { trim: true }),
        inset_left(columns[1]),
    );
}

fn render_work(frame: &mut Frame<'_>, area: Rect, app: &App) {
    let columns = Layout::horizontal([
        Constraint::Percentage(33),
        Constraint::Percentage(34),
        Constraint::Percentage(33),
    ])
    .split(area);
    let active = app.data.active_jobs();
    for (index, (stage, title, accent)) in [
        (WorkStage::Ready, "READY TO START", LEAF),
        (WorkStage::InProgress, "IN PROGRESS", ORANGE),
        (WorkStage::Review, "REVIEW REQUIRED", LAVENDER),
    ]
    .into_iter()
    .enumerate()
    {
        let target = match index {
            0 => inset_right(columns[index]),
            2 => inset_left(columns[index]),
            _ => inset_both(columns[index]),
        };
        let jobs = active
            .iter()
            .filter(|job| job.work_stage() == stage)
            .copied()
            .collect::<Vec<_>>();
        render_work_column(frame, target, title, accent, &jobs);
    }
}

fn render_work_column(
    frame: &mut Frame<'_>,
    area: Rect,
    title: &'static str,
    accent: ratatui::style::Color,
    jobs: &[&Job],
) {
    let mut lines = Vec::new();
    if jobs.is_empty() {
        lines.push(Line::from(Span::styled(
            "○ No jobs in this stage",
            Style::default().fg(MUTED),
        )));
    }
    for (position, job) in jobs.iter().take(6).enumerate() {
        if position > 0 {
            lines.push(Line::from(Span::styled(
                "─".repeat(24),
                Style::default().fg(LINE),
            )));
        }
        lines.extend([
            Line::from(vec![
                Span::styled(
                    format!("Order {}  ", job.id),
                    Style::default().fg(accent).add_modifier(Modifier::BOLD),
                ),
                Span::styled(
                    job.display_value(),
                    Style::default().fg(LEAF).add_modifier(Modifier::BOLD),
                ),
            ]),
            Line::from(Span::styled(
                truncate(job.display_title(), 30),
                Style::default().fg(INK),
            )),
            Line::from(vec![
                Span::styled(
                    format!("{} · ", job.display_status()),
                    Style::default().fg(MUTED),
                ),
                time_left_span(job),
            ]),
        ]);
    }
    frame.render_widget(
        Paragraph::new(lines)
            .block(
                panel_block()
                    .title(Line::from(vec![
                        Span::styled(
                            format!(" {title} · "),
                            Style::default().fg(MUTED).add_modifier(Modifier::BOLD),
                        ),
                        Span::styled(
                            jobs.len().to_string(),
                            Style::default().fg(accent).add_modifier(Modifier::BOLD),
                        ),
                        Span::styled(" ", Style::default().fg(MUTED)),
                    ]))
                    .border_style(Style::default().fg(LINE)),
            )
            .style(Style::default().fg(INK).bg(PAPER))
            .wrap(Wrap { trim: true }),
        area,
    );
}

fn render_history(frame: &mut Frame<'_>, area: Rect, app: &mut App) {
    let rows = Layout::vertical([
        Constraint::Length(4),
        Constraint::Length(1),
        Constraint::Min(8),
    ])
    .split(area);
    let toolbar = Layout::horizontal([Constraint::Min(40), Constraint::Length(34)])
        .split(rows[0].inner(Margin::new(1, 1)));
    frame.render_widget(panel_block(), rows[0]);
    frame.render_widget(
        Paragraph::new("LATEST 100 · all sources · all languages")
            .style(Style::default().fg(MUTED)),
        toolbar[0],
    );
    frame.render_widget(
        Paragraph::new(format!(
            "{} jobs · ${:.2} total",
            app.data.stats.total_jobs.max(app.data.jobs.len()),
            app.data.stats.total_value
        ))
        .style(Style::default().fg(LEAF).add_modifier(Modifier::BOLD))
        .alignment(Alignment::Right),
        toolbar[1],
    );
    let header =
        Row::new(["ORDER", "JOB", "VALUE", "SOURCE", "STATUS", "SEEN"]).style(table_header_style());
    let row_height = if app.compact_rows() { 1 } else { 2 };
    let data = app.data.jobs.iter().map(|job| {
        Row::new([
            job.id.clone(),
            truncate(job.display_title(), 42),
            job.display_value(),
            job.source.clone(),
            job.display_status().to_owned(),
            format_age(app.data.fetched_at - job.timestamp),
        ])
        .height(row_height)
    });
    let table = Table::new(
        data,
        [
            Constraint::Length(10),
            Constraint::Min(20),
            Constraint::Length(10),
            Constraint::Length(14),
            Constraint::Length(12),
            Constraint::Length(8),
        ],
    )
    .header(header)
    .row_highlight_style(selection_style())
    .highlight_symbol("▶ ")
    .block(panel_block())
    .column_spacing(2);
    let mut state = TableState::default().with_selected(Some(app.selected_history));
    frame.render_stateful_widget(table, rows[2], &mut state);
}

fn render_analytics(frame: &mut Frame<'_>, area: Rect, app: &App) {
    let rows = Layout::vertical([
        Constraint::Length(6),
        Constraint::Length(1),
        Constraint::Min(12),
    ])
    .split(area);
    let metrics = Layout::horizontal([Constraint::Percentage(25); 4]).split(rows[0]);
    let total = app.data.stats.total_jobs.max(app.data.jobs.len());
    let loaded = app.data.jobs.len();
    let accept_rate = if loaded == 0 {
        0.0
    } else {
        app.data.accepted_count() as f64 / loaded as f64 * 100.0
    };
    for (index, (value, label)) in [
        (total.to_string(), "JOBS DETECTED"),
        (format!("{accept_rate:.1}%"), "ACCEPT RATE"),
        (
            format!("${:.2}", app.data.stats.average_reward),
            "AVG VALUE",
        ),
        (app.data.status.failure_count.to_string(), "FAILURES"),
    ]
    .into_iter()
    .enumerate()
    {
        let target = match index {
            0 => inset_right(metrics[index]),
            3 => inset_left(metrics[index]),
            _ => inset_both(metrics[index]),
        };
        frame.render_widget(
            Paragraph::new(vec![
                Line::from(Span::styled(value, value_style())),
                Line::from(Span::styled(label, Style::default().fg(MUTED))),
            ])
            .block(panel_block())
            .style(Style::default().bg(PAPER)),
            target,
        );
    }
    let chart_rows =
        Layout::vertical([Constraint::Percentage(50), Constraint::Percentage(50)]).split(rows[2]);
    let top = Layout::horizontal([Constraint::Percentage(50), Constraint::Percentage(50)])
        .split(chart_rows[0]);
    let bottom = Layout::horizontal([Constraint::Percentage(50), Constraint::Percentage(50)])
        .split(chart_rows[1]);
    render_chart(
        frame,
        inset_right(top[0]),
        "JOBS BY HOUR",
        jobs_by_hour_lines(&app.data.jobs),
    );
    render_chart(
        frame,
        inset_left(top[1]),
        "SOURCE PERFORMANCE",
        source_performance_lines(&app.data),
    );
    render_chart(
        frame,
        inset_right(bottom[0]),
        "VALUE TREND · 7 DAYS",
        value_trend_lines(&app.data.jobs),
    );
    render_chart(
        frame,
        inset_left(bottom[1]),
        "TOP JOB TYPES",
        top_job_type_lines(&app.data.jobs),
    );
}

fn render_chart(frame: &mut Frame<'_>, area: Rect, title: &'static str, lines: Vec<String>) {
    frame.render_widget(
        Paragraph::new(lines.into_iter().map(Line::from).collect::<Vec<_>>())
            .block(titled_panel(title))
            .style(Style::default().fg(INK).bg(PAPER)),
        area,
    );
}

fn render_system(frame: &mut Frame<'_>, area: Rect, app: &App) {
    let rows =
        Layout::vertical([Constraint::Percentage(50), Constraint::Percentage(50)]).split(area);
    let top =
        Layout::horizontal([Constraint::Percentage(50), Constraint::Percentage(50)]).split(rows[0]);
    let bottom =
        Layout::horizontal([Constraint::Percentage(50), Constraint::Percentage(50)]).split(rows[1]);
    render_info_panel(
        frame,
        inset_right(top[0]),
        "MONITORS",
        health_summary_lines(app),
    );
    render_info_panel(
        frame,
        inset_left(top[1]),
        "API CONNECTION",
        vec![
            detail_owned("State", connection_label(&app.connection)),
            detail_owned(
                "Last update",
                if app.connection == ConnectionState::Demo {
                    "Static sample".into()
                } else {
                    format_age(current_unix_timestamp() - app.data.fetched_at)
                },
            ),
            detail_owned("Jobs loaded", app.data.jobs.len().to_string()),
            detail_owned("Events loaded", app.data.events.len().to_string()),
            detail_owned(
                "Watcher",
                if app.data.status.is_running {
                    "Running"
                } else {
                    "Stopped"
                },
            ),
        ],
    );
    render_info_panel(
        frame,
        inset_right(bottom[0]),
        "SESSION",
        vec![
            detail_owned(
                "Uptime",
                format_duration(app.data.status.session_stats.uptime.max(0.0) as u64),
            ),
            detail_owned(
                "New jobs",
                app.data.status.session_stats.new_entries.to_string(),
            ),
            detail_owned(
                "Session value",
                format!("${:.2}", app.data.status.session_stats.total_value),
            ),
            detail_owned("Failures", app.data.status.failure_count.to_string()),
            detail_owned(
                "Paused",
                if app.data.status.is_paused {
                    "Yes"
                } else {
                    "No"
                },
            ),
        ],
    );
    render_info_panel(
        frame,
        inset_left(bottom[1]),
        "RECENT EVENTS",
        app.data
            .events
            .iter()
            .rev()
            .take(8)
            .map(event_line)
            .collect(),
    );
}

fn render_translate(frame: &mut Frame<'_>, area: Rect, app: &mut App) {
    let rows = Layout::vertical([
        Constraint::Length(4),
        Constraint::Length(1),
        Constraint::Length(5),
        Constraint::Min(8),
    ])
    .split(area);
    let toolbar = Layout::horizontal([Constraint::Min(40), Constraint::Length(34)])
        .split(rows[0].inner(Margin::new(1, 1)));
    frame.render_widget(panel_block(), rows[0]);
    let hint = if app.translate_loading {
        "Loading…"
    } else {
        "↑/↓ select · enter detail · e edit draft · s submit · r refresh"
    };
    frame.render_widget(
        Paragraph::new(hint).style(Style::default().fg(MUTED)),
        toolbar[0],
    );
    frame.render_widget(
        Paragraph::new(format!(
            "{} runs · {}",
            app.translate_runs.len(),
            if app.translate_detail.is_some() {
                "detail loaded"
            } else {
                "no detail"
            }
        ))
        .style(Style::default().fg(LEAF).add_modifier(Modifier::BOLD))
        .alignment(Alignment::Right),
        toolbar[1],
    );
    let columns = Layout::horizontal([Constraint::Min(62), Constraint::Length(36)]).split(rows[3]);
    let header = Row::new(["RUN ID", "KIND", "CHARS", "STATUS"]).style(table_header_style());
    let row_height = if app.compact_rows() { 1 } else { 2 };
    let table_rows = app
        .translate_runs
        .iter()
        .map(|run| {
            Row::new([
                Cell::from(truncate(&run.run_id, 22)),
                Cell::from(run.kind.clone()),
                Cell::from(run.char_count.to_string()),
                Cell::from(run.display_status().to_owned()),
            ])
            .height(row_height)
        })
        .collect::<Vec<_>>();
    let table = Table::new(
        table_rows,
        [
            Constraint::Min(20),
            Constraint::Length(8),
            Constraint::Length(8),
            Constraint::Length(10),
        ],
    )
    .header(header)
    .row_highlight_style(selection_style())
    .highlight_symbol("▶ ")
    .block(counted_panel("TRANSLATE RUNS", app.translate_runs.len()))
    .column_spacing(2);
    let mut state = TableState::default().with_selected(Some(app.selected_translate));
    frame.render_stateful_widget(table, inset_right(columns[0]), &mut state);
    let detail = app.translate_detail.as_ref().map_or_else(
        || {
            if app.translate_runs.is_empty() {
                Text::from(vec![
                    Line::from("No translate runs yet"),
                    Line::from(""),
                    Line::from("e edit draft · s submit a run from the TUI,"),
                    Line::from("or POST /api/translate to start a fan-out run."),
                ])
            } else if let Some(run) = app.selected_translate_run() {
                Text::from(vec![
                    Line::from(Span::styled(
                        truncate(&run.run_id, 30),
                        Style::default().fg(INK).add_modifier(Modifier::BOLD),
                    )),
                    Line::from(truncate(&run.input_preview, 60)),
                    Line::from(""),
                    Line::from("Press enter to load detail."),
                ])
            } else {
                Text::from("No run selected")
            }
        },
        |detail| {
            let mut lines = vec![
                Line::from(Span::styled(
                    truncate(&detail.summary.run_id, 30),
                    Style::default().fg(INK).add_modifier(Modifier::BOLD),
                )),
                Line::from(truncate(&detail.summary.input_preview, 60)),
                Line::from(""),
            ];
            let mut models: Vec<_> = detail.summary.per_model.iter().collect();
            models.sort_by_key(|(name, _)| (*name).clone());
            for (name, state) in models.iter().take(4) {
                lines.push(Line::from(vec![
                    Span::styled(
                        format!("{name:<10}"),
                        Style::default().fg(BLUE).add_modifier(Modifier::BOLD),
                    ),
                    Span::raw(state.status.clone()),
                ]));
            }
            lines.push(Line::from(""));
            if let Some((name, result)) = detail.results.iter().next() {
                lines.push(Line::from(Span::styled(
                    format!("{name} final:"),
                    Style::default().fg(MUTED).add_modifier(Modifier::BOLD),
                )));
                lines.push(Line::from(truncate(&result.final_text, 120)));
            } else {
                lines.push(Line::from("No model results yet"));
            }
            Text::from(lines)
        },
    );
    frame.render_widget(
        Paragraph::new(detail)
            .block(titled_panel("SELECTED RUN"))
            .style(Style::default().fg(INK).bg(PAPER))
            .wrap(Wrap { trim: true }),
        inset_left(columns[1]),
    );
    render_translate_compose(frame, rows[2], app);
    if app.translate_modal {
        render_translate_modal(frame, area, app);
    }
}

fn render_translate_compose(frame: &mut Frame<'_>, area: Rect, app: &App) {
    let chars = app.translate_draft.chars().count();
    let draft_text = if app.translate_draft.trim().is_empty() {
        "(empty) · e edit · t on a job fills from title".to_owned()
    } else if app.editing_draft {
        let cursor = app.draft_cursor.min(chars);
        let head: String = app.translate_draft.chars().take(cursor).collect();
        let tail: String = app.translate_draft.chars().skip(cursor).collect();
        format!("{head}▏{tail}")
    } else {
        app.translate_draft.clone()
    };
    let models_text = if app.translate_models.is_empty() {
        "all (default)".to_owned()
    } else {
        let selected: Vec<&str> = app
            .translate_models
            .iter()
            .zip(app.translate_models_selected.iter())
            .filter(|(_, selected)| **selected)
            .map(|(name, _)| name.as_str())
            .collect();
        if selected.len() == app.translate_models.len() {
            "all".to_owned()
        } else if selected.is_empty() {
            "none".to_owned()
        } else {
            selected.join("+")
        }
    };
    let lines = vec![
        Line::from(vec![
            Span::styled(
                if app.editing_draft {
                    "DRAFT [editing] "
                } else {
                    "DRAFT "
                },
                Style::default().fg(BLUE).add_modifier(Modifier::BOLD),
            ),
            Span::raw(truncate(&draft_text, 110)),
        ]),
        Line::from(format!(
            "{chars} chars · models: {models_text} · review: {} · e edit · s submit",
            if app.translate_with_review {
                "on"
            } else {
                "off"
            }
        )),
    ];
    frame.render_widget(
        Paragraph::new(lines)
            .block(titled_panel("COMPOSE"))
            .style(Style::default().fg(INK).bg(PAPER))
            .wrap(Wrap { trim: true }),
        area,
    );
}

fn render_translate_modal(frame: &mut Frame<'_>, area: Rect, app: &App) {
    let chars = app.translate_draft.chars().count();
    let height = (app.translate_models.len().max(1) + 9) as u16;
    let modal = centered_rect(60, height, area);
    frame.render_widget(Clear, modal);
    let mut lines = vec![
        Line::from(Span::styled(
            "SUBMIT TRANSLATE RUN",
            Style::default().fg(ORANGE).add_modifier(Modifier::BOLD),
        )),
        Line::from(""),
        Line::from(format!(
            "{chars} chars · review {} (r toggles)",
            if app.translate_with_review {
                "on"
            } else {
                "off"
            }
        )),
    ];
    if app.translate_models.is_empty() {
        lines.push(Line::from("Models loading… (submit uses server defaults)"));
    } else {
        for (index, name) in app.translate_models.iter().enumerate() {
            let mark = if app.translate_models_selected[index] {
                "x"
            } else {
                " "
            };
            lines.push(Line::from(format!("[{mark}] {} {name}", index + 1)));
        }
    }
    lines.push(Line::from(""));
    lines.push(Line::from(vec![
        button_solid("enter", "SUBMIT"),
        Span::raw(" "),
        button_ghost("esc", "CANCEL"),
    ]));
    lines.push(Line::from(Span::styled(
        "1-9 toggle · a all · r review",
        Style::default().fg(MUTED),
    )));
    frame.render_widget(
        Paragraph::new(lines).block(
            Block::default()
                .borders(Borders::ALL)
                .border_type(BorderType::Rounded)
                .border_style(Style::default().fg(ORANGE))
                .style(Style::default().bg(PAPER)),
        ),
        modal,
    );
}

fn render_info_panel(
    frame: &mut Frame<'_>,
    area: Rect,
    title: &'static str,
    lines: Vec<Line<'static>>,
) {
    frame.render_widget(
        Paragraph::new(lines)
            .block(titled_panel(title))
            .style(Style::default().fg(INK).bg(PAPER))
            .wrap(Wrap { trim: true }),
        area,
    );
}

fn render_compact(frame: &mut Frame<'_>, area: Rect, app: &mut App) {
    app.nav_hitboxes.clear();
    let rows = Layout::vertical([Constraint::Length(3), Constraint::Min(8)])
        .split(area.inner(Margin::new(1, 0)));
    let tabs = View::ALL
        .into_iter()
        .enumerate()
        .map(|(i, view)| {
            let selected = view == app.view;
            let style = if selected {
                selection_style()
            } else {
                Style::default().fg(INK).bg(NAV_BG)
            };
            let marker = if selected { "▶" } else { " " };
            Span::styled(format!("{marker}{} {} ", i + 1, view.label()), style)
        })
        .collect::<Vec<_>>();
    frame.render_widget(
        Paragraph::new(Line::from(tabs)).wrap(Wrap { trim: true }),
        rows[0],
    );
    frame.render_widget(Paragraph::new(format!("{}\n\nTerminal is too small for the full dashboard. Resize to at least 110 × 30.\nKeyboard navigation remains available: 1–7, ←/→, q.", app.view.label().to_uppercase())).block(panel_block()).style(Style::default().fg(INK).bg(PAPER)).wrap(Wrap { trim: true }), rows[1]);
}

fn render_status(frame: &mut Frame<'_>, area: Rect, app: &App) {
    frame.render_widget(
        Block::default()
            .borders(Borders::TOP)
            .border_style(Style::default().fg(LINE))
            .style(Style::default().bg(CANOPY)),
        area,
    );
    let message_area = Rect::new(
        area.x,
        area.y.saturating_add(1),
        area.width,
        area.height.saturating_sub(1),
    );
    frame.render_widget(
        Paragraph::new(format!("  {}", app.status_message))
            .style(Style::default().fg(MUTED).bg(CANOPY)),
        message_area,
    );
}

fn render_footer(frame: &mut Frame<'_>, area: Rect) {
    let key = |hint: &str| {
        Span::styled(
            format!(" {hint} "),
            Style::default().fg(INK).add_modifier(Modifier::BOLD),
        )
    };
    let dim = |hint: &str| Span::styled(hint.to_owned(), Style::default().fg(MUTED));
    frame.render_widget(
        Paragraph::new(Line::from(vec![
            key("1–7"),
            dim("workspace  "),
            key("←/→"),
            dim("switch  "),
            key("↑/↓"),
            dim("select  "),
            key("a"),
            dim("accept  "),
            key("i"),
            dim("ignore  "),
            key("t"),
            dim("translate  "),
            key("v"),
            dim("layout  "),
            key("r"),
            dim("refresh  "),
            key("q"),
            dim("quit"),
        ]))
        .style(Style::default().fg(MUTED).bg(GROUND)),
        area,
    );
}

fn selection_style() -> Style {
    Style::default()
        .fg(INK)
        .bg(SELECTION)
        .add_modifier(Modifier::BOLD)
}

/// Column headers for every table: quiet caps, no filled background, so
/// the selection wash is the only strong horizontal band.
fn table_header_style() -> Style {
    Style::default().fg(MUTED).add_modifier(Modifier::BOLD)
}

/// Solid call-to-action chip: `[key] LABEL`.
fn button_solid(key: &str, label: &str) -> Span<'static> {
    Span::styled(
        format!(" [{key}] {label} "),
        Style::default()
            .fg(GROUND)
            .bg(LEAF)
            .add_modifier(Modifier::BOLD),
    )
}

/// Destructive chip: `[key] LABEL`.
fn button_danger(key: &str, label: &str) -> Span<'static> {
    Span::styled(
        format!(" [{key}] {label} "),
        Style::default()
            .fg(GROUND)
            .bg(RED)
            .add_modifier(Modifier::BOLD),
    )
}

/// Low-emphasis chip for dismissive actions: `[key] LABEL`.
fn button_ghost(key: &str, label: &str) -> Span<'static> {
    Span::styled(
        format!(" [{key}] {label} "),
        Style::default().fg(MUTED).bg(CANOPY),
    )
}

fn panel_block<'a>() -> Block<'a> {
    Block::default()
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(LINE))
        .style(Style::default().bg(PAPER))
}

fn titled_panel(title: &'static str) -> Block<'static> {
    panel_block().title(Span::styled(
        format!(" {title} "),
        Style::default().fg(MUTED).add_modifier(Modifier::BOLD),
    ))
}

fn counted_panel(title: &'static str, count: usize) -> Block<'static> {
    panel_block().title(Line::from(vec![
        Span::styled(
            format!(" {title} · "),
            Style::default().fg(MUTED).add_modifier(Modifier::BOLD),
        ),
        Span::styled(
            count.to_string(),
            Style::default().fg(LEAF).add_modifier(Modifier::BOLD),
        ),
        Span::styled(" ", Style::default().fg(MUTED)),
    ]))
}

fn value_style() -> Style {
    Style::default().fg(INK).add_modifier(Modifier::BOLD)
}

/// Time-left with urgency encoding: expired/imminent (<5m) is red, tight
/// (<15m) is orange, everything else stays quiet. String-sourced times
/// without a numeric reading render quiet.
fn time_left_span(job: &Job) -> Span<'static> {
    let text = job.display_time_left();
    let style = match job.accepted_seconds_left {
        Some(seconds) if seconds <= 0 || job.accepted_expired == Some(true) => {
            Style::default().fg(RED).add_modifier(Modifier::BOLD)
        }
        Some(seconds) if seconds < 300 => Style::default().fg(RED).add_modifier(Modifier::BOLD),
        Some(seconds) if seconds < 900 => Style::default().fg(ORANGE),
        _ => Style::default().fg(MUTED),
    };
    Span::styled(text, style)
}

/// Width-preserving variant for columnar lists (`{:>7}` + two spaces).
fn padded_time_left_span(job: &Job) -> Span<'static> {
    let span = time_left_span(job);
    Span::styled(format!("{:>7}  ", span.content), span.style)
}

fn status_owned(
    label: impl Into<String>,
    value: impl Into<String>,
    color: ratatui::style::Color,
) -> Line<'static> {
    Line::from(vec![
        Span::styled("● ", Style::default().fg(color)),
        Span::styled(format!("{:<12}", label.into()), Style::default().fg(INK)),
        Span::styled(value.into(), Style::default().fg(MUTED)),
    ])
}

fn detail_owned(label: impl Into<String>, value: impl Into<String>) -> Line<'static> {
    Line::from(vec![
        Span::styled(format!("{:<18}", label.into()), Style::default().fg(MUTED)),
        Span::styled(value.into(), Style::default().fg(INK)),
    ])
}

fn health_summary_lines(app: &App) -> Vec<Line<'static>> {
    let mut lines = vec![
        status_owned(
            "WebSocket",
            app.data.status.websocket_status.clone(),
            state_color(&app.data.status.websocket_status),
        ),
        status_owned(
            "RSS",
            app.data.status.rss_status.clone(),
            state_color(&app.data.status.rss_status),
        ),
    ];
    for (name, value) in app.data.status.health.iter().take(4) {
        let state = value
            .get("state")
            .and_then(serde_json::Value::as_str)
            .unwrap_or("unknown");
        let detail = value
            .get("detail")
            .and_then(serde_json::Value::as_str)
            .unwrap_or(state);
        lines.push(status_owned(
            title_case(name),
            truncate(detail, 28),
            state_color(state),
        ));
    }
    lines
}

fn state_color(state: &str) -> ratatui::style::Color {
    let state = state.to_ascii_lowercase();
    if state.contains("error")
        || state.contains("fail")
        || state.contains("stopped")
        || state.contains("unhealthy")
    {
        RED
    } else if state == "ok"
        || state.contains("healthy")
        || state.contains("live")
        || state.contains("watch")
        || state.contains("running")
        || (state.contains("connected") && !state.contains("disconnected"))
    {
        LEAF
    } else {
        ORANGE
    }
}

fn event_line(event: &model::ApiEvent) -> Line<'static> {
    let id = event
        .data
        .get("id")
        .or_else(|| event.data.get("job_id"))
        .and_then(serde_json::Value::as_str)
        .unwrap_or("");
    Line::from(Span::styled(
        format!(
            "{}  {:<28} {}",
            format_clock(event.timestamp),
            truncate(&event.event_type, 28),
            id
        ),
        Style::default().fg(MUTED),
    ))
}

fn source_sparkline(data: &DashboardData) -> String {
    if data.stats.jobs_by_source.is_empty() {
        return "No source data available".into();
    }
    data.stats
        .jobs_by_source
        .iter()
        .take(5)
        .map(|(source, count)| format!("{} {}", truncate(source, 8), mini_bar(*count, 8)))
        .collect::<Vec<_>>()
        .join("   ")
}

fn jobs_by_hour_lines(jobs: &[Job]) -> Vec<String> {
    let mut counts = [0_usize; 24];
    for job in jobs {
        if job.timestamp.is_finite() && job.timestamp >= 0.0 {
            counts[(job.timestamp as u64 / 3_600 % 24) as usize] += 1;
        }
    }
    let max = counts.iter().copied().max().unwrap_or(1).max(1);
    let lines = counts
        .iter()
        .enumerate()
        .filter(|(_, count)| **count > 0)
        .take(8)
        .map(|(hour, count)| format!("{hour:02}  {:<16} {count}", bar(*count, max, 16)))
        .collect::<Vec<_>>();
    if lines.is_empty() {
        vec!["No timestamp data".into()]
    } else {
        lines
    }
}

fn source_performance_lines(data: &DashboardData) -> Vec<String> {
    let max = data
        .stats
        .jobs_by_source
        .values()
        .copied()
        .max()
        .unwrap_or(1)
        .max(1);
    let total = data.stats.total_jobs.max(1);
    let mut sources = data.stats.jobs_by_source.iter().collect::<Vec<_>>();
    sources.sort_by_key(|(_, count)| std::cmp::Reverse(**count));
    let lines = sources
        .into_iter()
        .take(8)
        .map(|(source, count)| {
            format!(
                "{:<12} {:<14} {:>5.1}%",
                truncate(source, 12),
                bar(*count, max, 14),
                *count as f64 / total as f64 * 100.0
            )
        })
        .collect::<Vec<_>>();
    if lines.is_empty() {
        vec!["No source data".into()]
    } else {
        lines
    }
}

fn value_trend_lines(jobs: &[Job]) -> Vec<String> {
    let mut totals = BTreeMap::<u64, f64>::new();
    for job in jobs {
        if job.timestamp.is_finite() && job.timestamp >= 0.0 {
            *totals.entry(job.timestamp as u64 / 86_400).or_default() += job.reward;
        }
    }
    let recent = totals.into_iter().rev().take(7).collect::<Vec<_>>();
    let max = recent
        .iter()
        .map(|(_, value)| *value)
        .fold(0.0_f64, f64::max)
        .max(1.0);
    if recent.is_empty() {
        return vec!["No value history".into()];
    }
    recent
        .into_iter()
        .rev()
        .map(|(day, value)| {
            let width = ((value / max) * 18.0).round() as usize;
            format!("D{:<5} {:<18} ${value:.2}", day % 10_000, "█".repeat(width))
        })
        .collect()
}

fn top_job_type_lines(jobs: &[Job]) -> Vec<String> {
    let mut counts = BTreeMap::<String, (usize, f64)>::new();
    for job in jobs {
        let label = job
            .display_title()
            .split('·')
            .next()
            .unwrap_or("Other")
            .trim();
        let entry = counts.entry(truncate(label, 22)).or_default();
        entry.0 += 1;
        entry.1 += job.reward;
    }
    let mut values = counts.into_iter().collect::<Vec<_>>();
    values.sort_by_key(|(_, (count, _))| std::cmp::Reverse(*count));
    let lines = values
        .into_iter()
        .take(8)
        .map(|(label, (count, value))| format!("{label:<22} {count:>3}  ${value:>8.2}"))
        .collect::<Vec<_>>();
    if lines.is_empty() {
        vec!["No job type data".into()]
    } else {
        lines
    }
}

fn bar(value: usize, max: usize, width: usize) -> String {
    let filled = value.saturating_mul(width) / max.max(1);
    "█".repeat(filled)
}

fn mini_bar(value: usize, width: usize) -> String {
    "▪".repeat(value.min(width).max(1))
}

fn truncate(value: &str, max_chars: usize) -> String {
    let count = value.chars().count();
    if count <= max_chars {
        return value.to_owned();
    }
    let keep = max_chars.saturating_sub(1);
    format!("{}…", value.chars().take(keep).collect::<String>())
}

fn title_case(value: &str) -> String {
    let mut chars = value.chars();
    chars.next().map_or_else(String::new, |first| {
        first.to_uppercase().collect::<String>() + chars.as_str()
    })
}

fn format_age(seconds: f64) -> String {
    if !seconds.is_finite() || seconds < 0.0 {
        return "—".into();
    }
    let seconds = seconds as u64;
    if seconds < 60 {
        format!("{seconds}s ago")
    } else if seconds < 3_600 {
        format!("{}m ago", seconds / 60)
    } else if seconds < 86_400 {
        format!("{}h ago", seconds / 3_600)
    } else {
        format!("{}d ago", seconds / 86_400)
    }
}

fn format_duration(seconds: u64) -> String {
    if seconds >= 3_600 {
        format!(
            "{:02}:{:02}:{:02}",
            seconds / 3_600,
            seconds / 60 % 60,
            seconds % 60
        )
    } else {
        format!("{:02}:{:02}", seconds / 60, seconds % 60)
    }
}

fn seconds_until(timestamp: f64, now: f64) -> u64 {
    if !timestamp.is_finite() || timestamp <= now {
        0
    } else {
        (timestamp - now) as u64
    }
}

fn format_clock(timestamp: f64) -> String {
    if !timestamp.is_finite() || timestamp < 0.0 {
        return "--:--:--".into();
    }
    let seconds = timestamp as u64 % 86_400;
    format!(
        "{:02}:{:02}:{:02}",
        seconds / 3_600,
        seconds / 60 % 60,
        seconds % 60
    )
}

fn current_unix_timestamp() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}

fn connection_label(connection: &ConnectionState) -> String {
    match connection {
        ConnectionState::Demo => "Demo".into(),
        ConnectionState::Connecting => "Connecting".into(),
        ConnectionState::Live => "Connected".into(),
        ConnectionState::Reconnecting(message) => {
            format!("Reconnecting: {}", truncate(message, 24))
        }
    }
}

fn centered_rect(width: u16, height: u16, area: Rect) -> Rect {
    let width = width.min(area.width);
    let height = height.min(area.height);
    Rect::new(
        area.x + area.width.saturating_sub(width) / 2,
        area.y + area.height.saturating_sub(height) / 2,
        width,
        height,
    )
}

const fn inset_right(area: Rect) -> Rect {
    Rect::new(area.x, area.y, area.width.saturating_sub(1), area.height)
}
const fn inset_left(area: Rect) -> Rect {
    Rect::new(
        area.x.saturating_add(1),
        area.y,
        area.width.saturating_sub(1),
        area.height,
    )
}
const fn inset_both(area: Rect) -> Rect {
    Rect::new(
        area.x.saturating_add(1),
        area.y,
        area.width.saturating_sub(2),
        area.height,
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crossterm::event::KeyModifiers;
    use ratatui::{Terminal, backend::TestBackend};

    fn key(code: KeyCode) -> KeyEvent {
        KeyEvent::new(code, KeyModifiers::NONE)
    }

    #[test]
    fn number_keys_switch_all_workspaces() {
        let mut app = App::default();
        for (code, expected) in [
            ('1', View::Overview),
            ('2', View::Jobs),
            ('3', View::Work),
            ('4', View::History),
            ('5', View::Analytics),
            ('6', View::System),
            ('7', View::Translate),
        ] {
            let _ = app.handle_key(key(KeyCode::Char(code)));
            assert_eq!(app.view, expected);
        }
    }

    #[test]
    fn job_selection_is_bounded_and_actions_report_selected_order() {
        let mut app = App::new(View::Jobs);
        let _ = app.handle_key(key(KeyCode::Up));
        assert_eq!(app.selected_job, 0);
        for _ in 0..10 {
            let _ = app.handle_key(key(KeyCode::Down));
        }
        assert_eq!(app.selected_job, app.visible_available_jobs().len() - 1);
        let _ = app.handle_key(key(KeyCode::Char('a')));
        let action = app.handle_key(key(KeyCode::Char('y')));
        assert_eq!(action, Some(UiAction::AcceptJob("481519".into())));
        assert_eq!(app.handle_key(key(KeyCode::Char('a'))), None);
        assert!(app.confirmation.is_none());
        assert!(app.pending_destructive.is_some());
        app.apply_action_result_for(&action.expect("submitted action"), Ok("accepted".into()));
        assert!(app.pending_destructive.is_none());
    }

    #[test]
    fn unknown_health_states_are_not_green() {
        for state in ["", "unknown", "offline", "disconnected", "disabled"] {
            assert_eq!(state_color(state), ORANGE, "state {state:?}");
        }
        for state in ["Live", "Watching", "healthy", "running", "ok", "Connected"] {
            assert_eq!(state_color(state), LEAF, "state {state:?}");
        }
    }

    #[test]
    fn pause_alert_and_quit_controls_update_state() {
        let mut app = App::default();
        let action = app.handle_key(key(KeyCode::Char('p')));
        assert_eq!(action, Some(UiAction::Command("pause")));
        assert!(!app.paused);
        let _ = app.handle_key(key(KeyCode::Char('d')));
        assert!(!app.alert_visible);
        let _ = app.handle_key(key(KeyCode::Char('q')));
        assert!(app.should_quit);
    }

    #[test]
    fn acceptance_confirmation_renders_question_and_consequence() {
        let backend = TestBackend::new(150, 44);
        let mut terminal = Terminal::new(backend).expect("test terminal");
        let mut app = App::new(View::Jobs);
        let _ = app.handle_key(key(KeyCode::Char('a')));

        terminal
            .draw(|frame| render(frame, &mut app))
            .expect("render succeeds");

        let content = terminal
            .backend()
            .buffer()
            .content()
            .iter()
            .map(|cell| cell.symbol())
            .collect::<String>();
        assert!(content.contains("Accept order 481516?"));
        assert!(content.contains("This sends an acceptance request"));
    }

    #[test]
    fn every_workspace_renders_at_reference_and_compact_sizes() {
        for view in View::ALL {
            for (width, height) in [(150, 44), (75, 24)] {
                let backend = TestBackend::new(width, height);
                let mut terminal = Terminal::new(backend).expect("test terminal");
                let mut app = App::new(view);
                terminal
                    .draw(|frame| render(frame, &mut app))
                    .expect("render succeeds");
                let buffer = terminal.backend().buffer();
                assert!(
                    buffer
                        .content()
                        .iter()
                        .any(|cell| !cell.symbol().trim().is_empty())
                );
            }
        }
    }

    #[test]
    fn every_layout_renders_every_workspace() {
        for layout in [LayoutKind::Classic, LayoutKind::Beacon, LayoutKind::Dense] {
            for view in View::ALL {
                let backend = TestBackend::new(150, 44);
                let mut terminal = Terminal::new(backend).expect("test terminal");
                let mut app = App::with_layout(view, layout);
                terminal
                    .draw(|frame| render(frame, &mut app))
                    .expect("render succeeds");
                let content = terminal
                    .backend()
                    .buffer()
                    .content()
                    .iter()
                    .map(|cell| cell.symbol())
                    .collect::<String>();
                assert!(content.contains(view.label()));
            }
        }
    }

    #[test]
    fn beacon_ops_screen_shows_hero_queue_and_rail() {
        let backend = TestBackend::new(150, 44);
        let mut terminal = Terminal::new(backend).expect("test terminal");
        let mut app = App::with_layout(View::Overview, LayoutKind::Beacon);
        terminal
            .draw(|frame| render(frame, &mut app))
            .expect("render succeeds");
        let content = terminal
            .backend()
            .buffer()
            .content()
            .iter()
            .map(|cell| cell.symbol())
            .collect::<String>();
        assert!(content.contains("BEST OPPORTUNITY"));
        assert!(content.contains("QUEUE"));
        assert!(content.contains("ACT"));
        assert!(content.contains("HEALTH"));
        assert!(!content.contains("WORKSPACES"));
    }

    #[test]
    fn tabbed_layouts_replace_sidebar_with_tab_bar() {
        for layout in [LayoutKind::Beacon, LayoutKind::Dense] {
            let backend = TestBackend::new(150, 44);
            let mut terminal = Terminal::new(backend).expect("test terminal");
            let mut app = App::with_layout(View::Jobs, layout);
            terminal
                .draw(|frame| render(frame, &mut app))
                .expect("render succeeds");
            assert_eq!(app.nav_hitboxes.len(), View::ALL.len());
            assert!(app.nav_hitboxes.iter().any(|(_, view)| *view == View::Jobs));
        }
    }

    #[test]
    fn layout_slugs_round_trip() {
        for layout in [LayoutKind::Classic, LayoutKind::Beacon, LayoutKind::Dense] {
            assert_eq!(LayoutKind::from_slug(layout.slug()), Some(layout));
        }
        assert_eq!(LayoutKind::from_slug("nope"), None);
    }

    #[test]
    fn layout_key_cycles_classic_beacon_dense() {
        let mut app = App::new(View::Overview);
        assert_eq!(app.layout, LayoutKind::Classic);
        let _ = app.handle_key(key(KeyCode::Char('v')));
        assert_eq!(app.layout, LayoutKind::Beacon);
        assert!(app.status_message.contains("Beacon"));
        let _ = app.handle_key(key(KeyCode::Char('v')));
        assert_eq!(app.layout, LayoutKind::Dense);
        let _ = app.handle_key(key(KeyCode::Char('v')));
        assert_eq!(app.layout, LayoutKind::Classic);
    }

    #[test]
    fn time_left_encodes_urgency() {
        let mut job = available_job("1");
        job.accepted_seconds_left = None;
        assert_eq!(time_left_span(&job).style.fg, Some(MUTED));
        job.accepted_seconds_left = Some(2400);
        assert_eq!(time_left_span(&job).style.fg, Some(MUTED));
        job.accepted_seconds_left = Some(600);
        assert_eq!(time_left_span(&job).style.fg, Some(ORANGE));
        job.accepted_seconds_left = Some(60);
        assert_eq!(time_left_span(&job).style.fg, Some(RED));
        job.accepted_expired = Some(true);
        assert_eq!(time_left_span(&job).style.fg, Some(RED));
    }

    #[test]
    fn compact_terminal_uses_resize_message_instead_of_clipping_dashboard() {
        let backend = TestBackend::new(80, 24);
        let mut terminal = Terminal::new(backend).expect("test terminal");
        let mut app = App::new(View::Analytics);
        terminal
            .draw(|frame| render(frame, &mut app))
            .expect("render succeeds");
        let content = terminal
            .backend()
            .buffer()
            .content()
            .iter()
            .map(|cell| cell.symbol())
            .collect::<String>();
        assert!(content.contains("Terminal is too small"));
        assert!(!content.contains("JOBS BY HOUR"));
    }

    #[test]
    fn mouse_click_uses_rendered_navigation_hitboxes() {
        let backend = TestBackend::new(150, 44);
        let mut terminal = Terminal::new(backend).expect("test terminal");
        let mut app = App::default();
        terminal
            .draw(|frame| render(frame, &mut app))
            .expect("render succeeds");
        let (area, expected) = app.nav_hitboxes[4];
        app.handle_mouse(MouseEvent {
            kind: MouseEventKind::Down(MouseButton::Left),
            column: area.x,
            row: area.y,
            modifiers: KeyModifiers::NONE,
        });
        assert_eq!(app.view, expected);
    }

    fn available_job(id: &str) -> Job {
        Job {
            id: id.into(),
            title: "Japanese → English".into(),
            reward: 12.5,
            currency: "USD".into(),
            source: "WebSocket".into(),
            timestamp: 1_750_000_000.0,
            ..Job::default()
        }
    }

    fn key_repeat(code: KeyCode) -> KeyEvent {
        KeyEvent {
            kind: KeyEventKind::Repeat,
            ..key(code)
        }
    }

    #[test]
    fn apply_error_clears_pending_destructive_action() {
        let mut app = App::new(View::Jobs);
        let _ = app.handle_key(key(KeyCode::Char('a')));
        let action = app.handle_key(key(KeyCode::Char('y')));
        assert_eq!(action, Some(UiAction::AcceptJob("481516".into())));
        assert!(app.pending_destructive.is_some());

        app.apply_error("timed out");

        assert!(app.pending_destructive.is_none());
        let _ = app.handle_key(key(KeyCode::Char('a')));
        assert!(app.confirmation.is_some());
    }

    #[test]
    fn apply_snapshot_restores_alert_for_newly_available_jobs() {
        let mut app = App::default();
        let _ = app.handle_key(key(KeyCode::Char('d')));
        assert!(!app.alert_visible);

        let mut data = app.data.clone();
        app.apply_snapshot(data.clone());
        assert!(!app.alert_visible);

        data.jobs.push(available_job("481700"));
        app.apply_snapshot(data);
        assert!(app.alert_visible);
    }

    #[test]
    fn apply_snapshot_does_not_restore_alert_for_ignored_jobs() {
        let mut app = App::new(View::Jobs);
        let ignored_id = app.selected_available_job().expect("demo job").id.clone();
        let _ = app.handle_key(key(KeyCode::Char('i')));
        app.switch_to(View::Overview);
        let _ = app.handle_key(key(KeyCode::Char('d')));
        assert!(!app.alert_visible);

        let mut data = DashboardData::default();
        data.jobs.push(available_job(&ignored_id));
        app.apply_snapshot(data);
        assert!(!app.alert_visible);
    }

    #[test]
    fn key_repeat_moves_selection_but_does_not_fire_actions() {
        let mut app = App::new(View::Jobs);
        assert_eq!(app.handle_key(key_repeat(KeyCode::Char('c'))), None);
        assert_eq!(app.handle_key(key_repeat(KeyCode::Char('p'))), None);
        assert_eq!(app.handle_key(key_repeat(KeyCode::Char('a'))), None);
        assert!(app.confirmation.is_none());

        let _ = app.handle_key(key_repeat(KeyCode::Down));
        assert_eq!(app.selected_job, 1);
        let _ = app.handle_key(key_repeat(KeyCode::Char('2')));
        assert_eq!(app.view, View::Jobs);
    }

    #[test]
    fn translate_workspace_loads_demo_list_and_detail() {
        let mut app = App::new(View::Translate);
        assert_eq!(app.translate_runs.len(), 2);
        assert!(app.translate_detail.is_some());

        let _ = app.handle_key(key(KeyCode::Down));
        assert_eq!(app.selected_translate, 1);
        assert!(app.translate_detail.is_none());

        let action = app.handle_key(key(KeyCode::Enter));
        assert!(action.is_none(), "demo detail loads without worker");
        assert!(app.translate_detail.is_some());
    }

    #[test]
    fn translate_shortcut_from_jobs_is_read_only() {
        let mut app = App::new(View::Jobs);
        let action = app.handle_key(key(KeyCode::Char('t')));
        assert_eq!(app.view, View::Translate);
        assert!(
            action.is_none(),
            "demo mode must not emit worker actions for read-only view"
        );
        assert!(app.status_message.contains("Demo"));
    }

    #[test]
    fn translate_shortcut_fills_draft_without_accepting() {
        let mut app = App::live(View::Jobs);
        app.data.jobs = DashboardData::demo().jobs;
        let action = app.handle_key(key(KeyCode::Char('s')));
        assert!(action.is_none(), "unrelated key sends nothing");

        let action = app.handle_key(key(KeyCode::Char('t')));
        assert_eq!(action, Some(UiAction::RefreshTranslate));
        assert_eq!(app.view, View::Translate);
        assert!(
            !app.translate_draft.is_empty(),
            "draft prefilled from the selected job title"
        );
        assert!(
            app.status_message.contains("NOT accepted"),
            "prefill must never imply job acceptance"
        );
        assert!(app.pending_destructive.is_none());
        assert!(app.confirmation.is_none());
    }

    #[test]
    fn draft_editing_types_deletes_and_exits() {
        let mut app = App::live(View::Translate);
        assert_eq!(app.handle_key(key(KeyCode::Char('e'))), None);
        assert!(app.editing_draft);
        for character in ['h', 'i'] {
            assert_eq!(app.handle_key(key(KeyCode::Char(character))), None);
        }
        assert_eq!(app.translate_draft, "hi");
        // The quit key types text while editing instead of quitting.
        assert_eq!(app.handle_key(key(KeyCode::Char('q'))), None);
        assert!(!app.should_quit);
        assert_eq!(app.translate_draft, "hiq");
        assert_eq!(app.handle_key(key(KeyCode::Backspace)), None);
        assert_eq!(app.translate_draft, "hi");
        assert_eq!(app.handle_key(key(KeyCode::Enter)), None);
        assert!(!app.editing_draft);
        assert!(app.status_message.contains("2 chars"));
    }

    #[test]
    fn held_editing_keys_repeat_while_modal_toggles_do_not() {
        let mut app = App::live(View::Translate);
        app.translate_draft = "hey".into();
        let _ = app.handle_key(key(KeyCode::Char('e')));

        let mut repeat_backspace = key(KeyCode::Backspace);
        repeat_backspace.kind = KeyEventKind::Repeat;
        assert_eq!(app.handle_key(repeat_backspace), None);
        assert_eq!(app.translate_draft, "he");

        let mut repeat_char = key(KeyCode::Char('y'));
        repeat_char.kind = KeyEventKind::Repeat;
        assert_eq!(app.handle_key(repeat_char), None);
        assert_eq!(app.translate_draft, "hey");

        let _ = app.handle_key(key(KeyCode::Enter));
        app.translate_modal = true;
        app.apply_translate_models(vec!["grok".into(), "opencode".into()]);
        let mut repeat_digit = key(KeyCode::Char('1'));
        repeat_digit.kind = KeyEventKind::Repeat;
        assert_eq!(app.handle_key(repeat_digit), None);
        match app.handle_key(key(KeyCode::Char('q'))) {
            None => assert!(!app.translate_modal, "q cancels like the confirm modal"),
            other => panic!("expected cancel, got {other:?}"),
        }
    }
    #[test]
    fn submit_modal_requires_nonempty_draft() {
        let mut app = App::live(View::Translate);
        assert_eq!(app.handle_key(key(KeyCode::Char('s'))), None);
        assert!(!app.translate_modal);
        assert!(app.status_message.contains("empty"));
    }

    #[test]
    fn submit_flow_toggles_models_review_and_posts() {
        let mut app = App::live(View::Translate);
        app.translate_draft = "hello".into();
        let action = app.handle_key(key(KeyCode::Char('s')));
        assert_eq!(action, Some(UiAction::FetchTranslateModels));
        assert!(app.translate_modal);

        app.apply_translate_models(vec![
            "grok".into(),
            "opencode".into(),
            "codex".into(),
            "claude".into(),
        ]);
        // First load selects every model.
        assert_eq!(app.handle_key(key(KeyCode::Char('1'))), None);
        assert_eq!(app.handle_key(key(KeyCode::Char('r'))), None);
        assert!(!app.translate_with_review);

        match app.handle_key(key(KeyCode::Enter)) {
            Some(UiAction::StartTranslate {
                text,
                models,
                with_review,
            }) => {
                assert_eq!(text, "hello");
                assert_eq!(
                    models,
                    Some(vec!["opencode".into(), "codex".into(), "claude".into()])
                );
                assert!(!with_review);
            }
            other => panic!("expected StartTranslate, got {other:?}"),
        }
        assert!(!app.translate_modal);
        assert!(app.submit_pending);
    }

    #[test]
    fn submit_with_all_models_selected_sends_server_default() {
        let mut app = App::live(View::Translate);
        app.translate_draft = "hello".into();
        let _ = app.handle_key(key(KeyCode::Char('s')));
        app.apply_translate_models(vec!["grok".into(), "opencode".into()]);
        match app.handle_key(key(KeyCode::Char('y'))) {
            Some(UiAction::StartTranslate { models, .. }) => {
                assert_eq!(models, None);
            }
            other => panic!("expected StartTranslate, got {other:?}"),
        }
    }

    #[test]
    fn submit_requires_at_least_one_model() {
        let mut app = App::live(View::Translate);
        app.translate_draft = "hello".into();
        let _ = app.handle_key(key(KeyCode::Char('s')));
        app.apply_translate_models(vec!["grok".into()]);
        let _ = app.handle_key(key(KeyCode::Char('1')));
        assert_eq!(app.handle_key(key(KeyCode::Enter)), None);
        assert!(app.translate_modal, "modal stays open");
        assert!(app.status_message.contains("at least one model"));
    }

    #[test]
    fn submit_modal_cancel_and_demo_guard() {
        let mut app = App::live(View::Translate);
        app.translate_draft = "hello".into();
        let _ = app.handle_key(key(KeyCode::Char('s')));
        assert_eq!(app.handle_key(key(KeyCode::Esc)), None);
        assert!(!app.translate_modal);

        let mut demo = App::new(View::Translate);
        demo.translate_draft = "hello".into();
        assert_eq!(demo.handle_key(key(KeyCode::Char('s'))), None);
        assert!(demo.translate_modal, "demo still previews the modal");
        assert_eq!(demo.handle_key(key(KeyCode::Enter)), None);
        assert!(!demo.translate_modal);
        assert!(demo.status_message.contains("Demo"));
    }

    #[test]
    fn submit_selects_new_run_when_list_arrives() {
        let mut app = App::live(View::Translate);
        app.apply_translate_list(TranslateRunSummary::demo_list());
        app.apply_translate_started("20260911-120000-newrun".into());
        assert!(!app.submit_pending);
        assert!(app.status_message.contains("20260911-120000-newrun"));

        let mut runs = TranslateRunSummary::demo_list();
        let mut extra = runs[0].clone();
        extra.run_id = "20260911-120000-newrun".into();
        runs.push(extra);
        app.apply_translate_list(runs);
        assert_eq!(
            app.translate_runs[app.selected_translate].run_id,
            "20260911-120000-newrun"
        );
    }

    #[test]
    fn submit_failure_clears_pending_flags() {
        let mut app = App::live(View::Translate);
        app.submit_pending = true;
        app.translate_loading = true;
        let action = UiAction::StartTranslate {
            text: "hello".into(),
            models: None,
            with_review: true,
        };
        app.apply_action_result_for(&action, Err("busy".into()));
        assert!(!app.submit_pending);
        assert!(!app.translate_loading);
        assert!(app.status_message.contains("busy"));
    }

    #[test]
    fn translate_auto_poll_covers_view_mode_and_progress() {
        let demo = App::new(View::Translate);
        assert!(demo.translate_auto_poll().is_empty(), "demo never polls");

        let other = App::live(View::Overview);
        assert!(
            other.translate_auto_poll().is_empty(),
            "other views never poll"
        );

        let mut loading = App::live(View::Translate);
        loading.translate_loading = true;
        assert!(
            loading.translate_auto_poll().is_empty(),
            "in-flight requests are not stacked"
        );

        let mut finished = App::live(View::Translate);
        let mut runs = TranslateRunSummary::demo_list();
        for run in &mut runs {
            run.finished = true;
        }
        finished.apply_translate_list(runs);
        assert_eq!(
            finished.translate_auto_poll(),
            vec![UiAction::RefreshTranslate]
        );

        let mut running = App::live(View::Translate);
        let mut runs = TranslateRunSummary::demo_list();
        for run in &mut runs {
            run.finished = false;
        }
        running.apply_translate_list(runs);
        let run_id = running.translate_runs[0].run_id.clone();
        assert_eq!(
            running.translate_auto_poll(),
            vec![
                UiAction::RefreshTranslate,
                UiAction::GetTranslateDetail(run_id.clone()),
            ]
        );
        // Once the detail is current, the unfinished run still refetches
        // each poll (the list refresh never updates cached detail).
        running.apply_translate_detail(TranslateRunDetail::demo(&run_id));
        assert_eq!(
            running.translate_auto_poll(),
            vec![
                UiAction::RefreshTranslate,
                UiAction::GetTranslateDetail(run_id.clone()),
            ]
        );
    }

    #[test]
    fn draft_editing_inserts_newline_on_alt_enter() {
        let mut app = App::live(View::Translate);
        let _ = app.handle_key(key(KeyCode::Char('e')));
        let _ = app.handle_key(key(KeyCode::Char('a')));
        let mut alt_enter = key(KeyCode::Enter);
        alt_enter.modifiers = KeyModifiers::ALT;
        assert_eq!(app.handle_key(alt_enter), None);
        assert!(app.editing_draft, "newline must not exit editing");
        assert_eq!(app.translate_draft, "a\n");
        assert_eq!(app.handle_key(key(KeyCode::Enter)), None);
        assert!(!app.editing_draft);
    }

    #[test]
    fn translate_list_update_clamps_selection_and_clears_stale_detail() {
        let mut app = App::new(View::Translate);
        let _ = app.handle_key(key(KeyCode::Down));
        assert_eq!(app.selected_translate, 1);

        app.apply_translate_list(vec![]);
        assert_eq!(app.selected_translate, 0);
        assert!(app.translate_detail.is_none());
        assert!(app.status_message.contains('0'));
    }
    #[test]
    fn translate_refresh_failure_clears_loading_flag() {
        let mut app = App::live(View::Translate);
        app.translate_loading = true;
        app.apply_action_result_for(&UiAction::RefreshTranslate, Err("offline".into()));
        assert!(!app.translate_loading);
        assert!(app.status_message.contains("Translate failed"));
    }

    #[test]
    fn stale_translate_detail_response_is_ignored() {
        let mut app = App::live(View::Translate);
        app.apply_translate_list(TranslateRunSummary::demo_list());
        let first_id = app.translate_runs[0].run_id.clone();
        let second_id = app.translate_runs[1].run_id.clone();

        // Request detail for the first run, then move selection away.
        app.pending_translate_detail = Some(first_id.clone());
        app.translate_loading = true;
        app.selected_translate = 1;
        app.clear_translate_selection_state();

        // Late response for the deselected run must not clobber state.
        app.apply_translate_detail(TranslateRunDetail::demo(&first_id));
        assert!(app.translate_detail.is_none());
        assert!(!app.translate_loading);

        // A response matching the current selection still applies.
        app.pending_translate_detail = Some(second_id.clone());
        app.translate_loading = true;
        app.apply_translate_detail(TranslateRunDetail::demo(&second_id));
        assert_eq!(
            app.translate_detail
                .as_ref()
                .expect("detail")
                .summary
                .run_id,
            second_id
        );
        assert!(!app.translate_loading);
    }

    #[test]
    fn translate_view_renders_runs_and_selected_detail() {
        let backend = TestBackend::new(150, 44);
        let mut terminal = Terminal::new(backend).expect("test terminal");
        let mut app = App::new(View::Translate);
        terminal
            .draw(|frame| render(frame, &mut app))
            .expect("render succeeds");
        let content = terminal
            .backend()
            .buffer()
            .content()
            .iter()
            .map(|cell| cell.symbol())
            .collect::<String>();
        assert!(content.contains("TRANSLATE"));
        assert!(content.contains("20260911-120000-a1b2c3d4"));
        assert!(content.contains("SELECTED RUN"));
    }

    #[test]
    fn translate_compose_and_modal_render_without_panic() {
        let backend = TestBackend::new(150, 44);
        let mut terminal = Terminal::new(backend).expect("test terminal");
        let mut app = App::new(View::Translate);
        app.translate_draft = "hello world".into();
        app.editing_draft = true;
        terminal
            .draw(|frame| render(frame, &mut app))
            .expect("compose renders");
        let content = terminal
            .backend()
            .buffer()
            .content()
            .iter()
            .map(|cell| cell.symbol())
            .collect::<String>();
        assert!(content.contains("COMPOSE"));
        assert!(content.contains("hello world"));

        app.editing_draft = false;
        app.apply_translate_models(vec!["grok".into(), "opencode".into()]);
        app.translate_modal = true;
        terminal
            .draw(|frame| render(frame, &mut app))
            .expect("modal renders");
        let content = terminal
            .backend()
            .buffer()
            .content()
            .iter()
            .map(|cell| cell.symbol())
            .collect::<String>();
        assert!(content.contains("SUBMIT TRANSLATE RUN"));
        assert!(content.contains("grok"));
    }
}

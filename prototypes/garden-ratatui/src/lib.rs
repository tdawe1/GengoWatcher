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

use model::{DashboardData, Job, WorkStage};
use theme::*;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum View {
    Overview,
    Jobs,
    Work,
    History,
    Analytics,
    System,
}

impl View {
    pub const ALL: [Self; 6] = [
        Self::Overview,
        Self::Jobs,
        Self::Work,
        Self::History,
        Self::Analytics,
        Self::System,
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
        }
    }

    const fn previous(self) -> Self {
        Self::ALL[(self.index() + Self::ALL.len() - 1) % Self::ALL.len()]
    }

    const fn next(self) -> Self {
        Self::ALL[(self.index() + 1) % Self::ALL.len()]
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum UiAction {
    Refresh,
    Command(&'static str),
    AcceptJob(String),
    CancelCurrentJob,
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
    pub should_quit: bool,
    pub paused: bool,
    pub alert_visible: bool,
    pub selected_job: usize,
    pub selected_history: usize,
    pub status_message: String,
    pub data: DashboardData,
    pub connection: ConnectionState,
    ignored_job_ids: HashSet<String>,
    confirmation: Option<Confirmation>,
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
    pub fn live(view: View) -> Self {
        Self::with_data(view, DashboardData::default(), ConnectionState::Connecting)
    }

    fn with_data(view: View, data: DashboardData, connection: ConnectionState) -> Self {
        let paused = data.status.is_paused;
        Self {
            view,
            should_quit: false,
            paused,
            alert_visible: true,
            selected_job: 0,
            selected_history: 0,
            status_message: if connection == ConnectionState::Demo {
                "Demo data · no API actions are sent".into()
            } else {
                "Connecting to GengoWatcher API…".into()
            },
            data,
            connection,
            ignored_job_ids: HashSet::new(),
            confirmation: None,
            nav_hitboxes: Vec::with_capacity(View::ALL.len()),
        }
    }

    pub fn apply_snapshot(&mut self, data: DashboardData) {
        self.paused = data.status.is_paused;
        self.data = data;
        self.connection = ConnectionState::Live;
        self.clamp_selection();
        self.status_message = "Live data updated".into();
    }

    pub fn apply_error(&mut self, message: impl Into<String>) {
        let message = message.into();
        self.connection = ConnectionState::Reconnecting(message.clone());
        self.status_message = format!("API unavailable · {message}");
    }

    pub fn apply_action_result(&mut self, result: Result<String, String>) {
        self.confirmation = None;
        match result {
            Ok(message) => self.status_message = message,
            Err(message) => self.status_message = format!("Action failed · {message}"),
        }
    }

    #[must_use]
    pub fn handle_key(&mut self, key: KeyEvent) -> Option<UiAction> {
        if key.kind != KeyEventKind::Press && key.kind != KeyEventKind::Repeat {
            return None;
        }
        if key.code == KeyCode::Char('c') && key.modifiers.contains(KeyModifiers::CONTROL) {
            self.should_quit = true;
            return None;
        }
        if let Some(confirmation) = self.confirmation.clone() {
            return match key.code {
                KeyCode::Char('y') | KeyCode::Enter => {
                    self.confirmation = None;
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
            KeyCode::Char('a') if self.view == View::Jobs => {
                if let Some(job) = self.selected_available_job() {
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
                self.confirmation = Some(Confirmation::CancelCurrent);
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
    }
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
    let shell = Layout::vertical([
        Constraint::Length(4),
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
    if app.confirmation.is_some() {
        render_confirmation(frame, app);
    }
}

fn render_header(frame: &mut Frame<'_>, area: Rect, app: &App) {
    let columns = Layout::horizontal([Constraint::Percentage(55), Constraint::Percentage(45)])
        .split(area.inner(Margin::new(2, 0)));
    frame.render_widget(Block::default().style(Style::default().bg(CANOPY)), area);
    frame.render_widget(
        Paragraph::new(vec![
            Line::from(Span::styled(
                "GENGOWATCHER",
                Style::default().fg(INK).add_modifier(Modifier::BOLD),
            )),
            Line::from(Span::styled(
                "translation operations",
                Style::default().fg(MUTED),
            )),
        ]),
        columns[0],
    );
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
            Line::from(Span::styled(
                state,
                Style::default()
                    .fg(state_color)
                    .add_modifier(Modifier::BOLD),
            )),
            Line::from(Span::styled(
                format!(
                    "{} jobs loaded · next check {}",
                    app.data.jobs.len(),
                    format_duration(next_check)
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
        let style = if selected {
            Style::default()
                .fg(GROUND)
                .bg(LAVENDER)
                .add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(INK).bg(NAV_BG)
        };
        frame.render_widget(
            Paragraph::new(format!(" {}  {}", index + 1, view.label()))
                .style(style)
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
                Span::raw(" detected"),
            ]),
            Line::from(vec![
                Span::styled(app.data.accepted_count().to_string(), value_style()),
                Span::raw(" accepted"),
            ]),
            Line::from(vec![
                Span::styled(
                    format!("${:.2}", app.data.status.session_stats.total_value),
                    value_style(),
                ),
                Span::raw(" value"),
            ]),
        ])
        .block(panel_block())
        .style(Style::default().fg(MUTED).bg(PAPER)),
        rows[8],
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
                "CONFIRM ACTION",
                Style::default().fg(ORANGE).add_modifier(Modifier::BOLD),
            )),
            Line::from(""),
            Line::from(question),
            Line::from(detail),
            Line::from(""),
            Line::from(vec![
                Span::styled(" y / enter  confirm ", Style::default().fg(GROUND).bg(LEAF)),
                Span::raw("   "),
                Span::styled(" n / esc  cancel ", Style::default().fg(INK).bg(CANOPY)),
            ]),
        ])
        .block(
            Block::default()
                .borders(Borders::ALL)
                .border_type(BorderType::Double)
                .border_style(Style::default().fg(ORANGE)),
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
    }
}

fn render_overview(frame: &mut Frame<'_>, area: Rect, app: &App) {
    let alert_height = if app.alert_visible { 6 } else { 3 };
    let rows = Layout::vertical([
        Constraint::Length(alert_height),
        Constraint::Length(1),
        Constraint::Min(12),
    ])
    .split(area);
    let available = app.visible_available_jobs();
    let alert_job = available.first().copied();
    if let (true, Some(job)) = (app.alert_visible, alert_job) {
        let alert = Layout::horizontal([Constraint::Min(40), Constraint::Length(31)])
            .split(rows[0].inner(Margin::new(2, 1)));
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
                    "NEW JOB AVAILABLE",
                    Style::default().fg(PINK).add_modifier(Modifier::BOLD),
                )),
                Line::from(Span::styled(
                    format!("{}  ·  {}", job.display_value(), job.display_title()),
                    Style::default().fg(INK).add_modifier(Modifier::BOLD),
                )),
                Line::from(Span::styled(
                    format!(
                        "Order {}  ·  {}  ·  {} remaining",
                        job.id,
                        job.source,
                        job.display_time_left()
                    ),
                    Style::default().fg(MUTED),
                )),
            ]),
            alert[0],
        );
        frame.render_widget(
            Paragraph::new("[o] VIEW   [d] DISMISS")
                .style(
                    Style::default()
                        .fg(WHITE)
                        .bg(ORANGE)
                        .add_modifier(Modifier::BOLD),
                )
                .alignment(Alignment::Center),
            centered_line(alert[1]),
        );
    } else {
        frame.render_widget(
            Paragraph::new(format!(
                "No current alert · {} jobs remain available",
                available.len()
            ))
            .style(Style::default().fg(MUTED).bg(PAPER))
            .block(panel_block()),
            rows[0],
        );
    }
    let grid_rows =
        Layout::vertical([Constraint::Percentage(50), Constraint::Percentage(50)]).split(rows[2]);
    let top = Layout::horizontal([Constraint::Percentage(60), Constraint::Percentage(40)])
        .split(grid_rows[0]);
    let bottom = Layout::horizontal([Constraint::Percentage(60), Constraint::Percentage(40)])
        .split(grid_rows[1]);
    render_available_summary(frame, inset_right(top[0]), app);
    render_work_summary(frame, inset_left(top[1]), app);
    render_metric_summary(frame, inset_right(bottom[0]), app);
    render_system_summary(frame, inset_left(bottom[1]), app);
}

fn render_available_summary(frame: &mut Frame<'_>, area: Rect, app: &App) {
    let jobs = app.visible_available_jobs();
    let items = jobs
        .iter()
        .take(area.height.saturating_sub(2).into())
        .map(|job| {
            ListItem::new(format!(
                "{:<9} {:<28} {:>7}  {}",
                job.display_value(),
                truncate(job.display_title(), 28),
                job.display_time_left(),
                job.source
            ))
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
    frame.render_widget(
        Paragraph::new(vec![
            Line::from(format!("READY TO START     {}", count(WorkStage::Ready))),
            Line::from(""),
            Line::from(format!(
                "IN PROGRESS        {}",
                count(WorkStage::InProgress)
            )),
            Line::from(""),
            Line::from(format!("REVIEW REQUIRED    {}", count(WorkStage::Review))),
        ])
        .block(counted_panel("ACTIVE WORK", active.len()))
        .style(Style::default().fg(INK).bg(PAPER)),
        area,
    );
}

fn render_metric_summary(frame: &mut Frame<'_>, area: Rect, app: &App) {
    let total = app.data.jobs.len();
    let accepted = app.data.accepted_count();
    let accept_rate = if total == 0 {
        0.0
    } else {
        accepted as f64 / total as f64 * 100.0
    };
    let uptime_hours = (app.data.status.session_stats.uptime / 3600.0).max(1.0 / 60.0);
    let pace = f64::from(app.data.status.session_stats.new_entries as u32) / uptime_hours;
    frame.render_widget(
        Paragraph::new(vec![
            Line::from(vec![
                Span::raw("VALUE   "),
                Span::styled(
                    format!("${:.2}", app.data.status.session_stats.total_value),
                    value_style(),
                ),
                Span::raw("      ACCEPT RATE   "),
                Span::styled(format!("{accept_rate:.1}%"), value_style()),
            ]),
            Line::from(vec![
                Span::raw("PACE    "),
                Span::styled(format!("{pace:.1}/h"), value_style()),
                Span::raw("        AVG VALUE     "),
                Span::styled(
                    format!("${:.2}", app.data.stats.average_reward),
                    value_style(),
                ),
            ]),
            Line::from(""),
            Line::from(source_sparkline(&app.data)),
        ])
        .block(titled_panel("SESSION ANALYTICS"))
        .style(Style::default().fg(BLUE).bg(PAPER)),
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
    let columns = Layout::horizontal([Constraint::Min(62), Constraint::Length(36)]).split(area);
    let header = Row::new(["ORDER", "JOB", "VALUE", "SOURCE", "STATUS", "TIME"])
        .style(
            Style::default()
                .fg(WHITE)
                .bg(BLUE)
                .add_modifier(Modifier::BOLD),
        )
        .height(2);
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
                Cell::from(job.display_time_left()),
            ])
            .height(2)
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
    .row_highlight_style(
        Style::default()
            .bg(SELECTION)
            .fg(INK)
            .add_modifier(Modifier::BOLD),
    )
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
                    Span::styled(
                        "[a] ACCEPT",
                        Style::default()
                            .fg(GROUND)
                            .bg(LEAF)
                            .add_modifier(Modifier::BOLD),
                    ),
                    Span::raw("   "),
                    Span::styled(
                        "[i] IGNORE",
                        Style::default().fg(RED).add_modifier(Modifier::BOLD),
                    ),
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
            "No jobs in this stage",
            Style::default().fg(MUTED),
        )));
    }
    for job in jobs.iter().take(4) {
        lines.extend([
            Line::from(Span::styled(
                format!("Order {}", job.id),
                Style::default().fg(accent).add_modifier(Modifier::BOLD),
            )),
            Line::from(format!(
                "{} · {}",
                truncate(job.display_title(), 24),
                job.display_value()
            )),
            Line::from(format!(
                "{} · {}",
                job.display_status(),
                job.display_time_left()
            )),
            Line::from(""),
        ]);
    }
    frame.render_widget(
        Paragraph::new(lines)
            .block(counted_panel(title, jobs.len()).border_style(Style::default().fg(accent)))
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
    let header = Row::new(["ORDER", "JOB", "VALUE", "SOURCE", "STATUS", "SEEN"]).style(
        Style::default()
            .fg(WHITE)
            .bg(BLUE)
            .add_modifier(Modifier::BOLD),
    );
    let data = app.data.jobs.iter().map(|job| {
        Row::new([
            job.id.clone(),
            truncate(job.display_title(), 42),
            job.display_value(),
            job.source.clone(),
            job.display_status().to_owned(),
            format_age(app.data.fetched_at - job.timestamp),
        ])
        .height(2)
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
    .row_highlight_style(
        Style::default()
            .bg(SELECTION)
            .fg(INK)
            .add_modifier(Modifier::BOLD),
    )
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
            .style(Style::default().fg(BLUE).bg(PAPER)),
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
            let style = if view == app.view {
                Style::default()
                    .fg(GROUND)
                    .bg(LAVENDER)
                    .add_modifier(Modifier::BOLD)
            } else {
                Style::default().fg(INK).bg(NAV_BG)
            };
            Span::styled(format!(" {} {} ", i + 1, view.label()), style)
        })
        .collect::<Vec<_>>();
    frame.render_widget(
        Paragraph::new(Line::from(tabs)).wrap(Wrap { trim: true }),
        rows[0],
    );
    frame.render_widget(Paragraph::new(format!("{}\n\nTerminal is too small for the full dashboard. Resize to at least 110 × 30.\nKeyboard navigation remains available: 1–6, ←/→, q.", app.view.label().to_uppercase())).block(panel_block()).style(Style::default().fg(INK).bg(PAPER)).wrap(Wrap { trim: true }), rows[1]);
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
    frame.render_widget(
        Paragraph::new(
            "  1–6 workspace   ←/→ switch   ↑/↓ select   a accept   i ignore   c check   p pause   x cancel   q quit",
        )
        .style(Style::default().fg(MUTED).bg(GROUND)),
        area,
    );
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
    panel_block().title(Span::styled(
        format!(" {title} · {count} "),
        Style::default().fg(MUTED).add_modifier(Modifier::BOLD),
    ))
}

fn value_style() -> Style {
    Style::default().fg(INK).add_modifier(Modifier::BOLD)
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
    } else if state.contains("stale")
        || state.contains("connect")
        || state.contains("check")
        || state.contains("pause")
        || state.contains("warn")
    {
        ORANGE
    } else {
        LEAF
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
const fn centered_line(area: Rect) -> Rect {
    Rect::new(
        area.x,
        area.y.saturating_add(area.height / 2),
        area.width,
        1,
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
        assert_eq!(app.handle_key(key(KeyCode::Char('y'))), None);
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
}

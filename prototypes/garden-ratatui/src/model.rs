//! API models and view-oriented helpers for the live dashboard.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Default, Deserialize)]
pub struct Job {
    pub id: String,
    pub title: String,
    pub reward: f64,
    pub currency: String,
    pub url: String,
    pub timestamp: f64,
    pub source: String,
    #[serde(default)]
    pub accepted: bool,
    pub accepted_at: Option<f64>,
    pub accepted_seconds_left: Option<i64>,
    pub accepted_time_left: Option<String>,
    pub accepted_expired: Option<bool>,
    pub accepted_segment_count: Option<usize>,
    pub accepted_source_char_count: Option<usize>,
    pub lifecycle_state: Option<String>,
    pub acceptance_state: Option<String>,
    pub file_state: Option<String>,
    pub workflow_state: Option<String>,
    pub workflow_file_mode: Option<String>,
    pub translation_workflow: Option<Value>,
}

impl Job {
    #[must_use]
    pub fn display_title(&self) -> &str {
        if self.title.trim().is_empty() {
            "Untitled job"
        } else {
            self.title.trim()
        }
    }

    #[must_use]
    pub fn display_value(&self) -> String {
        let symbol = match self.currency.as_str() {
            "USD" => "$",
            "EUR" => "€",
            "GBP" => "£",
            _ => "",
        };
        if symbol.is_empty() {
            format!("{:.2} {}", self.reward, self.currency)
        } else {
            format!("{symbol}{:.2}", self.reward)
        }
    }

    #[must_use]
    pub fn display_status(&self) -> &str {
        self.workflow_state
            .as_deref()
            .filter(|value| !value.is_empty())
            .or_else(|| {
                self.acceptance_state
                    .as_deref()
                    .filter(|value| !value.is_empty())
            })
            .or_else(|| {
                self.lifecycle_state
                    .as_deref()
                    .filter(|value| !value.is_empty())
            })
            .unwrap_or(if self.accepted {
                "accepted"
            } else {
                "available"
            })
    }

    #[must_use]
    pub fn display_time_left(&self) -> String {
        if self.accepted_expired == Some(true) {
            return "expired".into();
        }
        if let Some(value) = self
            .accepted_time_left
            .as_deref()
            .filter(|value| !value.is_empty())
        {
            return value.into();
        }
        self.accepted_seconds_left.map_or_else(
            || "—".into(),
            |seconds| {
                let seconds = seconds.max(0);
                format!("{:02}:{:02}", seconds / 60, seconds % 60)
            },
        )
    }

    #[must_use]
    pub fn is_available(&self) -> bool {
        !self.accepted
            && self.accepted_expired != Some(true)
            && !matches!(
                self.display_status().to_ascii_lowercase().as_str(),
                "expired"
                    | "cancelled"
                    | "rejected"
                    | "completed"
                    | "gone"
                    | "unavailable"
                    | "missed"
            )
    }

    #[must_use]
    pub fn is_active(&self) -> bool {
        self.accepted
            && self.accepted_expired != Some(true)
            && !matches!(
                self.display_status().to_ascii_lowercase().as_str(),
                "completed" | "cancelled" | "expired" | "failed"
            )
    }

    #[must_use]
    pub fn work_stage(&self) -> WorkStage {
        let status = self.display_status().to_ascii_lowercase();
        if status.contains("review") || status.contains("qa") {
            WorkStage::Review
        } else if status.contains("progress")
            || status.contains("translat")
            || status.contains("started")
        {
            WorkStage::InProgress
        } else {
            WorkStage::Ready
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WorkStage {
    Ready,
    InProgress,
    Review,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct WatcherStatus {
    pub is_running: bool,
    #[serde(default)]
    pub is_paused: bool,
    pub websocket_status: String,
    pub rss_status: String,
    pub last_check_time: Option<f64>,
    pub next_check_time: f64,
    pub session_stats: SessionStats,
    pub failure_count: u64,
    pub cancellation_stats: Option<Value>,
    #[serde(default)]
    pub health: BTreeMap<String, Value>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct SessionStats {
    pub new_entries: u64,
    pub total_value: f64,
    pub uptime: f64,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct Stats {
    pub total_jobs: usize,
    pub total_value: f64,
    pub average_reward: f64,
    pub jobs_by_source: BTreeMap<String, usize>,
    pub session_stats: SessionStats,
    pub uptime: f64,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct ApiEvent {
    #[serde(alias = "event_type")]
    pub event_type: String,
    pub event_id: String,
    pub timestamp: f64,
    pub data: Value,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct JobsResponse {
    pub jobs: Vec<Job>,
    pub pagination: Pagination,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct Pagination {
    pub page: usize,
    pub limit: usize,
    pub total: usize,
    pub pages: usize,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct EventsResponse {
    pub events: Vec<ApiEvent>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct TranslatePerModel {
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub bytes: usize,
    #[serde(default)]
    pub ms: u64,
    #[serde(default)]
    pub error: String,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct TranslateRunSummary {
    pub run_id: String,
    #[serde(default)]
    pub kind: String,
    #[serde(default)]
    pub char_count: usize,
    #[serde(default)]
    pub with_review: bool,
    #[serde(default)]
    pub models: Vec<String>,
    #[serde(default)]
    pub created_at: f64,
    #[serde(default)]
    pub finished_at: Option<f64>,
    #[serde(default)]
    pub finished: bool,
    #[serde(default)]
    pub per_model: BTreeMap<String, TranslatePerModel>,
    #[serde(default)]
    pub input_preview: String,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct TranslateResult {
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub translation: String,
    #[serde(default)]
    pub error: String,
    #[serde(default, alias = "final")]
    pub final_text: String,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct TranslateRunDetail {
    #[serde(flatten)]
    pub summary: TranslateRunSummary,
    #[serde(default)]
    pub source_text: String,
    #[serde(default)]
    pub original_name: String,
    #[serde(default)]
    pub results: BTreeMap<String, TranslateResult>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct TranslateListResponse {
    #[serde(default)]
    pub runs: Vec<TranslateRunSummary>,
}

impl TranslateRunSummary {
    #[must_use]
    pub fn display_status(&self) -> &str {
        if !self.finished {
            return "running";
        }
        if self.per_model.values().any(|state| state.status == "ok") {
            "ok"
        } else if self
            .per_model
            .values()
            .any(|state| state.status == "skipped")
        {
            "skipped"
        } else if self
            .per_model
            .values()
            .any(|state| state.status == "failed")
        {
            "failed"
        } else {
            "done"
        }
    }

    #[must_use]
    pub fn demo_list() -> Vec<Self> {
        vec![
            Self {
                run_id: "20260911-120000-a1b2c3d4".into(),
                kind: "text".into(),
                char_count: 42,
                with_review: true,
                models: vec!["opencode".into(), "claude".into()],
                created_at: 1_750_000_000.0,
                finished_at: Some(1_750_000_120.0),
                finished: true,
                per_model: BTreeMap::from([
                    (
                        "opencode".into(),
                        TranslatePerModel {
                            status: "ok".into(),
                            bytes: 128,
                            ms: 12_000,
                            error: String::new(),
                        },
                    ),
                    (
                        "claude".into(),
                        TranslatePerModel {
                            status: "skipped".into(),
                            bytes: 0,
                            ms: 800,
                            error: "no sub / auth / quota".into(),
                        },
                    ),
                ]),
                input_preview: "こんにちは、製品アップデートのお知らせ…".into(),
            },
            Self {
                run_id: "20260911-121500-e5f6a7b8".into(),
                kind: "file".into(),
                char_count: 1_240,
                with_review: true,
                models: vec!["grok".into(), "opencode".into()],
                created_at: 1_750_000_100.0,
                finished_at: None,
                finished: false,
                per_model: BTreeMap::from([
                    (
                        "grok".into(),
                        TranslatePerModel {
                            status: "running".into(),
                            bytes: 0,
                            ms: 0,
                            error: String::new(),
                        },
                    ),
                    (
                        "opencode".into(),
                        TranslatePerModel {
                            status: "queued".into(),
                            bytes: 0,
                            ms: 0,
                            error: String::new(),
                        },
                    ),
                ]),
                input_preview: "ReleaseNotes.txt · 1,240 chars…".into(),
            },
        ]
    }
}

impl TranslateRunDetail {
    #[must_use]
    pub fn demo(run_id: &str) -> Self {
        let summary = Self::demo_summaries()
            .into_iter()
            .find(|item| item.run_id == run_id)
            .unwrap_or_else(|| Self::demo_summaries().remove(0));
        let results = BTreeMap::from([
            (
                "opencode".into(),
                TranslateResult {
                    status: "ok".into(),
                    translation: "Hello, product update notice…".into(),
                    final_text: "Hello, product update notice…".into(),
                    error: String::new(),
                },
            ),
            (
                "claude".into(),
                TranslateResult {
                    status: "skipped".into(),
                    translation: String::new(),
                    final_text: "SKIPPED: claude has no active subscription.".into(),
                    error: "no sub / auth / quota".into(),
                },
            ),
        ]);
        Self {
            summary,
            source_text: "こんにちは、製品アップデートのお知らせ…".into(),
            original_name: String::new(),
            results,
        }
    }

    fn demo_summaries() -> Vec<TranslateRunSummary> {
        TranslateRunSummary::demo_list()
    }
}

#[derive(Debug, Clone, Default)]
pub struct DashboardData {
    pub status: WatcherStatus,
    pub jobs: Vec<Job>,
    pub events: Vec<ApiEvent>,
    pub stats: Stats,
    pub fetched_at: f64,
}

impl DashboardData {
    #[must_use]
    pub fn available_jobs(&self) -> Vec<&Job> {
        self.jobs.iter().filter(|job| job.is_available()).collect()
    }

    #[must_use]
    pub fn active_jobs(&self) -> Vec<&Job> {
        self.jobs.iter().filter(|job| job.is_active()).collect()
    }

    #[must_use]
    pub fn accepted_count(&self) -> usize {
        self.jobs.iter().filter(|job| job.accepted).count()
    }

    #[must_use]
    pub fn demo() -> Self {
        let jobs = vec![
            Job {
                id: "481516".into(),
                title: "Japanese → English · Product localization".into(),
                reward: 18.40,
                currency: "USD".into(),
                source: "WebSocket".into(),
                timestamp: 1_750_000_000.0,
                accepted_seconds_left: Some(243),
                ..Job::default()
            },
            Job {
                id: "481519".into(),
                title: "English → Japanese · Help centre".into(),
                reward: 31.00,
                currency: "USD".into(),
                source: "Website".into(),
                timestamp: 1_749_999_984.0,
                accepted_seconds_left: Some(90),
                ..Job::default()
            },
            Job {
                id: "481501".into(),
                title: "Japanese → English · App strings".into(),
                reward: 42.00,
                currency: "USD".into(),
                source: "WebSocket".into(),
                timestamp: 1_749_999_900.0,
                accepted: true,
                workflow_state: Some("in_progress".into()),
                accepted_segment_count: Some(32),
                accepted_seconds_left: Some(1664),
                ..Job::default()
            },
            Job {
                id: "481477".into(),
                title: "German → English · Support article".into(),
                reward: 16.80,
                currency: "USD".into(),
                source: "Email".into(),
                timestamp: 1_749_999_800.0,
                accepted: true,
                workflow_state: Some("review_required".into()),
                ..Job::default()
            },
            Job {
                id: "481518".into(),
                title: "French → English · Product update".into(),
                reward: 8.20,
                currency: "USD".into(),
                source: "RSS".into(),
                timestamp: 1_749_999_700.0,
                accepted: true,
                acceptance_state: Some("accepted".into()),
                accepted_seconds_left: Some(3_010),
                ..Job::default()
            },
        ];
        let status = WatcherStatus {
            is_running: true,
            websocket_status: "Live".into(),
            rss_status: "Watching".into(),
            next_check_time: 1_750_000_022.0,
            session_stats: SessionStats {
                new_entries: 14,
                total_value: 71.45,
                uptime: 6_138.0,
            },
            ..WatcherStatus::default()
        };
        let stats = Stats {
            total_jobs: 1_284,
            total_value: 9_412.60,
            average_reward: 17.86,
            jobs_by_source: BTreeMap::from([
                ("WebSocket".into(), 668),
                ("Email".into(), 308),
                ("RSS".into(), 205),
                ("Website".into(), 103),
            ]),
            session_stats: status.session_stats.clone(),
            uptime: status.session_stats.uptime,
        };
        let events = vec![
            ApiEvent {
                event_type: "job.visible".into(),
                timestamp: 1_750_000_000.0,
                data: serde_json::json!({"id": "481516"}),
                ..ApiEvent::default()
            },
            ApiEvent {
                event_type: "browser.synced".into(),
                timestamp: 1_749_999_984.0,
                ..ApiEvent::default()
            },
        ];
        Self {
            status,
            jobs,
            events,
            stats,
            fetched_at: 1_750_000_004.0,
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct CommandRequest<'a> {
    pub command: &'a str,
    pub args: &'a [String],
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct CommandResponse {
    pub status: String,
    pub message: String,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn demo_data_covers_available_active_and_review_states() {
        let data = DashboardData::demo();
        assert_eq!(data.available_jobs().len(), 2);
        assert_eq!(data.active_jobs().len(), 3);
        assert!(
            data.active_jobs()
                .iter()
                .any(|job| job.work_stage() == WorkStage::Review)
        );
    }

    #[test]
    fn missing_required_api_fields_fail_deserialization() {
        assert!(serde_json::from_str::<Job>(r#"{"title":"Missing id"}"#).is_err());
        assert!(serde_json::from_str::<WatcherStatus>(r#"{}"#).is_err());
        assert!(serde_json::from_str::<JobsResponse>(r#"{}"#).is_err());
        assert!(serde_json::from_str::<EventsResponse>(r#"{}"#).is_err());
        assert!(serde_json::from_str::<CommandResponse>(r#"{}"#).is_err());
    }

    #[test]
    fn time_left_is_formatted_and_clamped() {
        let mut job = Job {
            accepted_seconds_left: Some(243),
            ..Job::default()
        };
        assert_eq!(job.display_time_left(), "04:03");
        job.accepted_seconds_left = Some(-4);
        assert_eq!(job.display_time_left(), "00:00");
        job.accepted_expired = Some(true);
        assert_eq!(job.display_time_left(), "expired");
    }

    #[test]
    fn gone_jobs_are_not_available() {
        let available = Job {
            id: "1".into(),
            title: "Open".into(),
            ..Job::default()
        };
        let gone = Job {
            id: "2".into(),
            title: "Left the board".into(),
            lifecycle_state: Some("gone".into()),
            workflow_state: Some("gone".into()),
            ..Job::default()
        };
        assert!(available.is_available());
        assert!(!gone.is_available());
        assert_eq!(gone.display_status(), "gone");
    }

    #[test]
    fn translate_demo_list_covers_finished_and_running() {
        let runs = TranslateRunSummary::demo_list();
        assert_eq!(runs.len(), 2);
        assert!(runs.iter().any(|run| run.finished));
        assert!(runs.iter().any(|run| !run.finished));
        assert_eq!(runs[0].display_status(), "ok");
        assert_eq!(runs[1].display_status(), "running");
    }

    #[test]
    fn translate_list_response_tolerates_missing_fields() {
        let response: TranslateListResponse =
            serde_json::from_str(r#"{"runs":[]}"#).expect("empty list");
        assert!(response.runs.is_empty());
        let run: TranslateRunSummary =
            serde_json::from_str(r#"{"run_id":"20260911-120000-a1b2c3d4"}"#).expect("minimal run");
        assert_eq!(run.run_id, "20260911-120000-a1b2c3d4");
        assert_eq!(run.display_status(), "running");
    }

    #[test]
    fn translate_detail_deserializes_final_alias() {
        let detail: TranslateRunDetail = serde_json::from_str(
            r#"{"run_id":"r1","results":{"opencode":{"status":"ok","final":"done"}}}"#,
        )
        .expect("detail with final alias");
        assert_eq!(
            detail.results["opencode"].final_text, "done",
            "serde `final` alias must map to final_text"
        );
    }

    #[test]
    fn all_skipped_models_display_as_skipped() {
        let run = TranslateRunSummary {
            run_id: "20260911-120000-a1b2c3d4".into(),
            finished: true,
            per_model: BTreeMap::from([
                (
                    "grok".into(),
                    TranslatePerModel {
                        status: "skipped".into(),
                        ..TranslatePerModel::default()
                    },
                ),
                (
                    "claude".into(),
                    TranslatePerModel {
                        status: "skipped".into(),
                        ..TranslatePerModel::default()
                    },
                ),
            ]),
            ..TranslateRunSummary::default()
        };
        assert_eq!(run.display_status(), "skipped");
    }
}

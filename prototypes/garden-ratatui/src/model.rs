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
                "expired" | "cancelled" | "rejected" | "completed"
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
}

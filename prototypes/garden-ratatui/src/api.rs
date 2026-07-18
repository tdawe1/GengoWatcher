//! Authenticated blocking client for GengoWatcher's local FastAPI service.

use std::{
    fmt,
    net::IpAddr,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use reqwest::{StatusCode, Url, blocking::Client};
use serde::{Serialize, de::DeserializeOwned};
use serde_json::Value;

use crate::model::{
    CommandRequest, CommandResponse, DashboardData, EventsResponse, JobsResponse, Stats,
    WatcherStatus,
};

const DEFAULT_TIMEOUT: Duration = Duration::from_secs(4);

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ApiError {
    message: String,
}

impl ApiError {
    fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl fmt::Display for ApiError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl std::error::Error for ApiError {}

#[derive(Debug, Clone)]
pub struct ApiClient {
    client: Client,
    base_url: String,
    token: String,
}

impl ApiClient {
    pub fn new(base_url: &str, token: &str) -> Result<Self, ApiError> {
        if token.trim().is_empty() {
            return Err(ApiError::new(
                "GENGOWATCHER_API_TOKEN is empty; refusing unauthenticated startup",
            ));
        }
        let mut url = Url::parse(base_url.trim())
            .map_err(|error| ApiError::new(format!("invalid API URL: {error}")))?;
        if url.scheme() != "http" {
            return Err(ApiError::new(
                "API URL must use the local GengoWatcher HTTP service",
            ));
        }
        if url.username() != "" || url.password().is_some() {
            return Err(ApiError::new("API URL must not contain credentials"));
        }
        if url.query().is_some() || url.fragment().is_some() {
            return Err(ApiError::new(
                "API URL must not contain a query string or fragment",
            ));
        }
        if !is_loopback_host(url.host_str()) {
            return Err(ApiError::new(
                "API URL must use a localhost or loopback address",
            ));
        }
        let path = url.path().trim_end_matches('/').to_owned();
        url.set_path(&path);
        let client = Client::builder()
            .connect_timeout(DEFAULT_TIMEOUT)
            .timeout(DEFAULT_TIMEOUT)
            .build()
            .map_err(|error| ApiError::new(format!("failed to build API client: {error}")))?;
        Ok(Self {
            client,
            base_url: url.to_string().trim_end_matches('/').to_owned(),
            token: token.trim().to_owned(),
        })
    }

    pub fn fetch_snapshot(&self) -> Result<DashboardData, ApiError> {
        let status = self.get::<WatcherStatus>("/api/status")?;
        let jobs = self.get::<JobsResponse>("/api/jobs?limit=100&page=1")?;
        let events = self.get::<EventsResponse>("/api/events?limit=100")?;
        let stats = self.get::<Stats>("/api/stats")?;
        Ok(DashboardData {
            status,
            jobs: jobs.jobs,
            events: events.events,
            stats,
            fetched_at: unix_timestamp(),
        })
    }

    pub fn command(&self, command: &str) -> Result<CommandResponse, ApiError> {
        self.post_json("/api/commands", &CommandRequest { command, args: &[] })
    }

    pub fn accept_job(&self, job_id: &str) -> Result<CommandResponse, ApiError> {
        if job_id.is_empty()
            || !job_id
                .chars()
                .all(|character| character.is_ascii_alphanumeric() || "-_.".contains(character))
        {
            return Err(ApiError::new("job ID contains unsupported characters"));
        }
        self.post_json(&format!("/api/jobs/{job_id}/accept"), &Value::Null)
    }

    pub fn cancel_current_job(&self) -> Result<CommandResponse, ApiError> {
        self.post_json("/api/jobs/cancel", &Value::Null)
    }

    fn get<T: DeserializeOwned>(&self, path: &str) -> Result<T, ApiError> {
        let response = self
            .client
            .get(self.endpoint(path))
            .bearer_auth(&self.token)
            .send()
            .map_err(|error| ApiError::new(format!("API request failed: {error}")))?;
        decode_response(response)
    }

    fn post_json<T: DeserializeOwned, B: Serialize>(
        &self,
        path: &str,
        body: &B,
    ) -> Result<T, ApiError> {
        let response = self
            .client
            .post(self.endpoint(path))
            .bearer_auth(&self.token)
            .json(body)
            .send()
            .map_err(|error| ApiError::new(format!("API request failed: {error}")))?;
        decode_response(response)
    }

    fn endpoint(&self, path: &str) -> String {
        format!("{}{path}", self.base_url)
    }
}

fn decode_response<T: DeserializeOwned>(
    response: reqwest::blocking::Response,
) -> Result<T, ApiError> {
    let status = response.status();
    if status.is_success() {
        return response
            .json::<T>()
            .map_err(|error| ApiError::new(format!("invalid API response: {error}")));
    }
    let body = response.text().unwrap_or_default();
    let detail = serde_json::from_str::<Value>(&body)
        .ok()
        .and_then(|value| {
            value
                .get("detail")
                .and_then(Value::as_str)
                .map(str::to_owned)
        })
        .unwrap_or_else(|| status_label(status));
    Err(ApiError::new(format!("API returned {status}: {detail}")))
}

fn status_label(status: StatusCode) -> String {
    status
        .canonical_reason()
        .map_or_else(|| "request failed".into(), str::to_owned)
}

fn is_loopback_host(host: Option<&str>) -> bool {
    match host {
        Some("localhost") => true,
        Some(value) => value
            .trim_matches(['[', ']'])
            .parse::<IpAddr>()
            .is_ok_and(|address| address.is_loopback()),
        None => false,
    }
}

fn unix_timestamp() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        io::{Read, Write},
        net::TcpListener,
        thread,
    };

    #[test]
    fn rejects_empty_tokens_and_insecure_remote_http() {
        assert!(ApiClient::new("http://127.0.0.1:8000", "").is_err());
        assert!(ApiClient::new("http://example.com", "token").is_err());
        assert!(ApiClient::new("https://example.com", "token").is_err());
    }

    #[test]
    fn accepts_ipv4_ipv6_and_named_loopback_urls() {
        assert!(ApiClient::new("http://127.0.0.1:8000", "token").is_ok());
        assert!(ApiClient::new("http://[::1]:8000", "token").is_ok());
        assert!(ApiClient::new("http://localhost:8000", "token").is_ok());
    }

    #[test]
    fn job_ids_are_restricted_before_becoming_url_paths() {
        let client = ApiClient::new("http://127.0.0.1:9", "token").expect("valid client");
        let error = client.accept_job("../../config").expect_err("invalid ID");
        assert_eq!(error.to_string(), "job ID contains unsupported characters");
    }

    #[test]
    fn fetch_snapshot_reads_all_dashboard_endpoints_with_bearer_auth() {
        let responses = [
            (
                "/api/status",
                r#"{"is_running":true,"is_paused":false,"websocket_status":"Live","rss_status":"Watching","next_check_time":2000,"session_stats":{"new_entries":3,"total_value":44.2,"uptime":90},"failure_count":0}"#,
            ),
            (
                "/api/jobs?limit=100&page=1",
                r#"{"jobs":[{"id":"42","title":"JA → EN","reward":12.5,"currency":"USD","url":"https://example.invalid/42","timestamp":1000,"source":"WebSocket"}],"pagination":{"page":1,"limit":100,"total":1,"pages":1}}"#,
            ),
            (
                "/api/events?limit=100",
                r#"{"events":[{"event_type":"job.visible","event_id":"event-1","timestamp":1000,"data":{"id":"42"}}]}"#,
            ),
            (
                "/api/stats",
                r#"{"total_jobs":1,"total_value":12.5,"average_reward":12.5,"jobs_by_source":{"WebSocket":1},"session_stats":{"new_entries":3,"total_value":44.2,"uptime":90},"uptime":90}"#,
            ),
        ];
        let (base_url, server) = start_test_server(responses);
        let client = ApiClient::new(&base_url, "test-token").expect("valid client");

        let snapshot = client.fetch_snapshot().expect("snapshot fetched");

        assert!(snapshot.status.is_running);
        assert_eq!(snapshot.jobs[0].id, "42");
        assert_eq!(snapshot.events[0].event_type, "job.visible");
        assert_eq!(snapshot.stats.average_reward, 12.5);
        server.join().expect("test server joined");
    }

    #[test]
    fn command_posts_authenticated_json_and_decodes_result() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind test server");
        let address = listener.local_addr().expect("test address");
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept request");
            let mut request = vec![0_u8; 8_192];
            let bytes = stream.read(&mut request).expect("read request");
            let request = String::from_utf8_lossy(&request[..bytes]);
            assert!(request.starts_with("POST /api/commands HTTP/1.1"));
            assert!(
                request
                    .to_ascii_lowercase()
                    .contains("authorization: bearer test-token")
            );
            assert!(request.contains(r#""command":"pause""#));
            let body = r#"{"status":"success","message":"Watcher paused"}"#;
            write!(
                stream,
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                body.len(),
                body
            )
            .expect("write response");
        });
        let client =
            ApiClient::new(&format!("http://{address}"), "test-token").expect("valid client");

        let response = client.command("pause").expect("command succeeds");

        assert_eq!(response.status, "success");
        assert_eq!(response.message, "Watcher paused");
        server.join().expect("test server joined");
    }

    fn start_test_server<const N: usize>(
        responses: [(&'static str, &'static str); N],
    ) -> (String, thread::JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind test server");
        let address = listener.local_addr().expect("test address");
        let server = thread::spawn(move || {
            for (expected_path, body) in responses {
                let (mut stream, _) = listener.accept().expect("accept request");
                let mut request = vec![0_u8; 8_192];
                let bytes = stream.read(&mut request).expect("read request");
                let request = String::from_utf8_lossy(&request[..bytes]);
                let request_line = request.lines().next().unwrap_or_default();
                assert!(
                    request_line.contains(expected_path),
                    "expected {expected_path:?} in {request_line:?}"
                );
                assert!(
                    request
                        .to_ascii_lowercase()
                        .contains("authorization: bearer test-token")
                );
                write!(
                    stream,
                    "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                    body.len(),
                    body
                )
                .expect("write response");
            }
        });
        (format!("http://{address}"), server)
    }
}

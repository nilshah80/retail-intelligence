use std::collections::BTreeMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde::Serialize;
use tokio::sync::watch;

#[derive(Debug, Clone, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct StageMeasurement {
    pub calls: u64,
    pub cumulative_seconds: f64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TelemetrySnapshot {
    pub wall_seconds: f64,
    pub peak_process_tree_rss_bytes: u64,
    pub logical_cpu_count: usize,
    pub stages: BTreeMap<String, StageMeasurement>,
}

#[derive(Clone)]
pub struct Telemetry {
    started: Instant,
    stages: Arc<Mutex<BTreeMap<String, StageMeasurement>>>,
    peak_rss: Arc<Mutex<u64>>,
}

impl Telemetry {
    #[must_use]
    pub fn new() -> Self {
        Self {
            started: Instant::now(),
            stages: Arc::new(Mutex::new(BTreeMap::new())),
            peak_rss: Arc::new(Mutex::new(0)),
        }
    }

    pub fn measure(&self, stage: impl Into<String>) -> StageGuard {
        StageGuard {
            telemetry: self.clone(),
            stage: stage.into(),
            started: Instant::now(),
        }
    }

    pub fn spawn_sampler(&self) -> SamplerHandle {
        let (stop_tx, mut stop_rx) = watch::channel(false);
        let peak = Arc::clone(&self.peak_rss);
        let join = tokio::spawn(async move {
            let mut system = sysinfo::System::new_all();
            let root = sysinfo::Pid::from_u32(std::process::id());
            loop {
                system.refresh_all();
                let mut total = 0_u64;
                for (pid, process) in system.processes() {
                    if *pid == root || is_descendant(&system, *pid, root) {
                        total = total.saturating_add(process.memory());
                    }
                }
                if let Ok(mut value) = peak.lock() {
                    *value = (*value).max(total);
                }
                tokio::select! {
                    result = stop_rx.changed() => {
                        if result.is_err() || *stop_rx.borrow() {
                            break;
                        }
                    }
                    () = tokio::time::sleep(Duration::from_millis(250)) => {}
                }
            }
        });
        SamplerHandle { stop_tx, join }
    }

    #[must_use]
    pub fn snapshot(&self) -> TelemetrySnapshot {
        TelemetrySnapshot {
            wall_seconds: self.started.elapsed().as_secs_f64(),
            peak_process_tree_rss_bytes: self.peak_rss.lock().map_or(0, |value| *value),
            logical_cpu_count: std::thread::available_parallelism().map_or(1, usize::from),
            stages: self
                .stages
                .lock()
                .map_or_else(|_| BTreeMap::new(), |value| value.clone()),
        }
    }
}

impl Default for Telemetry {
    fn default() -> Self {
        Self::new()
    }
}

fn is_descendant(system: &sysinfo::System, mut pid: sysinfo::Pid, root: sysinfo::Pid) -> bool {
    for _ in 0..64 {
        let Some(process) = system.process(pid) else {
            return false;
        };
        let Some(parent) = process.parent() else {
            return false;
        };
        if parent == root {
            return true;
        }
        if parent == pid {
            return false;
        }
        pid = parent;
    }
    false
}

pub struct StageGuard {
    telemetry: Telemetry,
    stage: String,
    started: Instant,
}

impl Drop for StageGuard {
    fn drop(&mut self) {
        let elapsed = self.started.elapsed().as_secs_f64();
        if let Ok(mut stages) = self.telemetry.stages.lock() {
            let entry = stages.entry(self.stage.clone()).or_default();
            entry.calls += 1;
            entry.cumulative_seconds += elapsed;
        }
    }
}

pub struct SamplerHandle {
    stop_tx: watch::Sender<bool>,
    join: tokio::task::JoinHandle<()>,
}

impl SamplerHandle {
    pub async fn stop(self) {
        let _ = self.stop_tx.send(true);
        let _ = self.join.await;
    }
}

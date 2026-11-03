//! Optional phase timings contain no source identities or recorded content.
use std::time::Instant;

pub(crate) struct Profile(Option<Instant>);

impl Profile {
    pub fn new() -> Self {
        Self(std::env::var_os("ASR_CONVERT_PROFILE").map(|_| Instant::now()))
    }

    pub fn mark(&mut self, phase: &str) {
        if let Some(start) = &mut self.0 {
            let seconds = start.elapsed().as_secs_f64();
            *start = Instant::now();
            eprintln!("{}", serde_json::json!({"phase":phase,"seconds":seconds}));
        }
    }
}

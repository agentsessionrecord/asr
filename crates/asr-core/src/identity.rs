use sha2::{Digest, Sha256};

pub fn valid_id(id: &str) -> bool {
    !id.is_empty() && id.chars().count() <= 256 && !id.chars().any(char::is_control)
}

/// Length framing prevents components with separators from aliasing each other.
pub fn derive_id(parts: &[&str]) -> String {
    let mut digest = Sha256::new();
    for part in parts {
        digest.update((part.len() as u64).to_be_bytes());
        digest.update(part.as_bytes());
    }
    format!("asr-{:x}", digest.finalize())
}

pub fn encode_component(value: &str) -> String {
    let mut out = String::new();
    for c in value.chars() {
        if matches!(c, '%' | ':' | '#' | ' ') || c.is_control() {
            for byte in c.to_string().as_bytes() {
                out.push_str(&format!("%{byte:02X}"));
            }
        } else {
            out.push(c);
        }
    }
    out
}

pub fn session_ref(agent: &str, namespace: Option<&str>, session: &str) -> String {
    let prefix = namespace
        .map(|n| format!("{}:", encode_component(n)))
        .unwrap_or_default();
    format!("{agent}:{prefix}{}", encode_component(session))
}

//! Starting repository facts come from native metadata, never the live filesystem.
use crate::{common, Agent};
use serde_json::{json, Value};

fn string<'a>(value: &'a Value, keys: &[&str]) -> Option<&'a str> {
    keys.iter()
        .find_map(|key| value.get(*key).and_then(common::nonempty))
}
fn head(value: &str) -> bool {
    matches!(value.len(), 40 | 64)
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn remote(value: &str) -> bool {
    !value.split_once("://").is_some_and(|(_, tail)| {
        tail.split('/')
            .next()
            .is_some_and(|host| host.contains('@'))
    }) && !value.contains('?')
        && !value.contains('#')
}
fn repo(native: &Value, path: &str) -> Value {
    let mut r = json!({"path":path});
    if let Some(branch) = string(
        native,
        &["branch", "gitBranch", "git_branch", "current_branch"],
    ) {
        r["branch"] = json!(branch);
    }
    if let Some(commit) = string(
        native,
        &["head", "commit_hash", "git_commit", "commit", "head_sha"],
    )
    .filter(|s| head(s))
    {
        r["head"] = json!(commit);
    }
    if let Some(url) = string(
        native,
        &["remote", "repository_url", "git_remote", "remote_url"],
    )
    .filter(|s| remote(s))
    {
        r["remote"] = json!(url);
    }
    r
}
pub fn capture(header: &mut Value, agent: Agent, native: &Value) {
    if agent == Agent::MistralVibe {
        if let Some(origin) = native["origin_directory"]
            .as_str()
            .filter(|p| common::absolute(p))
        {
            header["cwd"] = json!(origin);
        }
    }
    if header.get("cwd").is_none() {
        if let Some(cwd) = string(
            native,
            &[
                "cwd",
                "working_dir",
                "working_directory",
                "directory",
                "workspaceDirectory",
                "workspaceRoot",
                "workspace_root",
                "projectPath",
                "workDir",
            ],
        )
        .or_else(|| native.pointer("/context/cwd").and_then(common::nonempty))
        .filter(|p| common::absolute(p))
        {
            header["cwd"] = json!(cwd);
        }
    }
    // An explicit repository list establishes paths even when branch and HEAD are absent.
    let mut repos: Vec<Value> = native["repos"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|n| Some(repo(n, string(n, &["path"])?)))
        .filter(|r| common::absolute(r["path"].as_str().unwrap()))
        .collect();
    let git = match agent {
        Agent::ClaudeCode if common::nonempty(&native["gitBranch"]).is_some() => Some(native),
        Agent::MistralVibe
            if common::nonempty(&native["git_branch"]).is_some()
                || native["git_commit"].as_str().is_some_and(head) =>
        {
            Some(native)
        }
        _ => native
            .get("git")
            .filter(|v| v.is_object() && !v.as_object().unwrap().is_empty()),
    };
    if let Some(git) = git {
        if let Some(path) = string(git, &["path", "root", "worktree"])
            .or_else(|| header["cwd"].as_str())
            .filter(|p| common::absolute(p))
        {
            repos.push(repo(git, path));
        }
    }
    if agent == Agent::Zed {
        for worktree in native
            .pointer("/initial_project_snapshot/worktree_snapshots")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
        {
            if let (Some(path), Some(git)) = (
                worktree["worktree_path"]
                    .as_str()
                    .filter(|p| common::absolute(p)),
                worktree.get("git_state").filter(|v| v.is_object()),
            ) {
                repos.push(repo(git, path));
            }
        }
    }
    if !repos.is_empty() && header.get("repos").is_none() {
        header["repos"] = json!(repos);
    }
}

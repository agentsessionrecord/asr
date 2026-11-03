use super::*;
use clap::Args;
use regex::Regex;
use similar::{ChangeTag, TextDiff};
use std::{
    cell::RefCell,
    collections::{BTreeMap, BTreeSet},
    path::{Component, PathBuf},
};

#[derive(Args)]
pub struct Options {
    /// File in the selected Git repository.
    pub file: PathBuf,
    #[arg(long)]
    pub line: usize,
    #[arg(long, default_value = ".")]
    pub repo: PathBuf,
    /// ASR file or directory. May be repeated.
    #[arg(long, required = true)]
    pub sessions: Vec<PathBuf>,
    /// Optional annotation files containing exact rewrite evidence.
    #[arg(long)]
    pub annotations: Vec<PathBuf>,
}
struct Git {
    root: PathBuf,
    cache: RefCell<BTreeMap<Vec<String>, Option<Vec<u8>>>>,
}
impl Git {
    fn new(root: PathBuf) -> Self {
        Self {
            root,
            cache: RefCell::new(BTreeMap::new()),
        }
    }
    fn bytes(&self, args: &[&str]) -> Result<Vec<u8>> {
        let key: Vec<_> = args.iter().map(|s| (*s).to_owned()).collect();
        if let Some(cached) = self.cache.borrow().get(&key) {
            return cached
                .clone()
                .ok_or_else(|| "Git repository check failed".into());
        }
        let output = Command::new("git")
            .arg("--no-pager")
            .args([
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.quotePath=false",
                "-c",
                "protocol.allow=never",
                "-c",
                "log.showSignature=false",
            ])
            .arg("-C")
            .arg(&self.root)
            .args(args)
            .env_remove("GIT_EXTERNAL_DIFF")
            .env("GIT_NO_LAZY_FETCH", "1")
            .env("GIT_TERMINAL_PROMPT", "0")
            .output()?;
        let value = output.status.success().then_some(output.stdout);
        self.cache.borrow_mut().insert(key, value.clone());
        value.ok_or_else(|| "Git repository check failed".into())
    }
    fn run(&self, args: &[&str]) -> Result<String> {
        Ok(String::from_utf8(self.bytes(args)?).map_err(|_| "Git content is not UTF-8")?)
    }
    fn exists(&self, sha: &str) -> bool {
        full_id(sha)
            && self
                .run(&["cat-file", "-t", sha])
                .is_ok_and(|s| s.trim() == "commit")
    }
    fn blob(&self, sha: &str, path: &str) -> Option<String> {
        self.run(&["show", &format!("{sha}:{path}")]).ok()
    }
    fn parents(&self, sha: &str) -> Option<Vec<String>> {
        Some(
            self.run(&["show", "-s", "--format=%P", sha])
                .ok()?
                .split_whitespace()
                .map(str::to_owned)
                .collect(),
        )
    }
    fn added(&self, sha: &str, path: &str) -> BTreeSet<usize> {
        let Some(parents) = self.parents(sha) else {
            return BTreeSet::new();
        };
        if parents.is_empty() {
            return (1..=self.blob(sha, path).map_or(0, |s| s.lines().count())).collect();
        }
        let Ok(diff) = self.run(&[
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            "--unified=0",
            &parents[0],
            sha,
            "--",
            path,
        ]) else {
            return BTreeSet::new();
        };
        let header = Regex::new(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@").unwrap();
        let mut line = None;
        let mut added = BTreeSet::new();
        for s in diff.lines() {
            if let Some(c) = header.captures(s) {
                line = c[1].parse::<usize>().ok();
            } else if let Some(n) = line.as_mut() {
                if s.starts_with('+') {
                    added.insert(*n);
                    *n += 1;
                } else if s.starts_with(' ') {
                    *n += 1;
                }
            }
        }
        added
    }
}
fn full_id(s: &str) -> bool {
    matches!(s.len(), 40 | 64)
        && s.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn normalize(path: &Path) -> PathBuf {
    let mut out = PathBuf::new();
    for c in path.components() {
        match c {
            Component::ParentDir => {
                out.pop();
            }
            Component::CurDir => {}
            _ => out.push(c.as_os_str()),
        }
    }
    out
}
fn same_repo(git: &Git, path: &str) -> bool {
    Path::new(path).is_absolute()
        && !path.chars().any(char::is_control)
        && Path::new(path)
            .canonicalize()
            .is_ok_and(|p| p.starts_with(&git.root))
}
fn repos(stream: &Stream) -> Vec<Value> {
    stream.state().facts["repos"]
        .as_array()
        .cloned()
        .unwrap_or_default()
}
fn vcs_repo(git: &Git, stream: &Stream, r: &Value) -> bool {
    if let Some(repo) = text(r, "repo") {
        return same_repo(git, repo);
    }
    let repos = repos(stream);
    repos.len() == 1 && text(&repos[0], "path").is_some_and(|p| same_repo(git, p))
}
fn relative(git: &Git, stream: &Stream, path: &str) -> Option<String> {
    if path.chars().any(char::is_control) {
        return None;
    }
    let p = Path::new(path);
    let full = if p.is_absolute() {
        normalize(p)
    } else {
        normalize(&Path::new(text(&stream.records[0], "cwd")?).join(p))
    };
    let repos = repos(stream);
    let candidate = if repos.is_empty() {
        text(&stream.records[0], "cwd").is_some_and(|p| same_repo(git, p))
    } else {
        repos
            .iter()
            .any(|repo| text(repo, "path").is_some_and(|p| same_repo(git, p)))
    };
    if candidate {
        return full
            .strip_prefix(&git.root)
            .ok()?
            .to_str()
            .map(str::to_owned);
    }
    None
}
fn successful(stream: &Stream, r: &Value) -> bool {
    match text(r, "status") {
        Some("completed") => true,
        Some("unknown") => text(r, "callId")
            .and_then(|id| stream.result(id))
            .is_some_and(|r| r["status"] == "completed"),
        _ => false,
    }
}
fn rewrites(r: &Value) -> Vec<(String, String)> {
    let mut pairs = r["rewrites"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|p| Some((text(p, "from")?.into(), text(p, "to")?.into())))
        .collect::<Vec<_>>();
    if pairs.is_empty() && r["action"] == "amend" {
        if let (Some(a), Some(b)) = (text(r, "headBefore"), text(r, "commit")) {
            pairs.push((a.into(), b.into()));
        }
    }
    pairs
}
fn commit_match(git: &Git, stream: &Stream, r: &Value, sha: &str) -> bool {
    if text(r, "commit").is_some_and(|id| id != sha)
        && !r["rewrites"]
            .as_array()
            .into_iter()
            .flatten()
            .any(|p| text(p, "to") == Some(sha))
    {
        return false;
    }
    if !vcs_repo(git, stream, r)
        || !successful(stream, r)
        || !matches!(
            text(r, "action"),
            Some("commit" | "amend" | "merge" | "rebase" | "cherry_pick" | "revert")
        )
        || !matches!(text(r, "evidence"), Some("observed" | "parsed_output"))
    {
        return false;
    }
    let parents = match git.parents(sha) {
        Some(p) => p,
        None => return false,
    };
    if let Some(subject) = text(r, "subject") {
        if !git
            .run(&["show", "-s", "--format=%s", sha])
            .is_ok_and(|s| s.strip_suffix('\n') == Some(subject))
        {
            return false;
        }
    }
    if let Some(p) = r.get("parents") {
        if *p != json!(parents) {
            return false;
        }
    }
    if let Some(n) = r.get("parentCount") {
        if n.as_u64() != Some(parents.len() as u64) {
            return false;
        }
    }
    if text(r, "commit") == Some(sha)
        || r["rewrites"]
            .as_array()
            .into_iter()
            .flatten()
            .any(|p| text(p, "to") == Some(sha))
    {
        return true;
    }
    let Some(prefix) = text(r, "commitPrefix") else {
        return false;
    };
    if !(7..=39).contains(&prefix.len())
        || !sha.starts_with(prefix)
        || !prefix
            .bytes()
            .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
        || text(r, "subject").is_none()
        || r["action"] == "rebase"
    {
        return false;
    }
    let Ok(objects) = git.run(&["rev-parse", &format!("--disambiguate={prefix}")]) else {
        return false;
    };
    if objects.lines().collect::<Vec<_>>() != vec![sha] {
        return false;
    }
    if r["action"] == "merge" {
        if parents.len() < 2 {
            return false;
        }
    } else if parents.len() > 1 {
        return false;
    }
    git.run(&[
        "for-each-ref",
        &format!("--contains={sha}"),
        "--format=%(refname)",
        "refs/heads",
        "refs/tags",
    ])
    .is_ok_and(|s| !s.trim().is_empty())
}

fn unique_start(haystack: &[&str], needle: &[&str]) -> Option<usize> {
    if needle.is_empty() || needle.len() > haystack.len() {
        return None;
    }
    let mut found = haystack
        .windows(needle.len())
        .enumerate()
        .filter(|(_, w)| *w == needle);
    let index = found.next()?.0;
    found.next().is_none().then_some(index)
}
fn unique_text(haystack: &str, needle: &str) -> Option<usize> {
    if needle.is_empty() {
        return None;
    }
    let start = haystack.find(needle)?;
    // Include overlapping occurrences in the ambiguity check.
    let next = start + haystack[start..].chars().next()?.len_utf8();
    haystack[next..].find(needle).is_none().then_some(start)
}
/// A parent file is a replay baseline, never an observed historical file state.
fn parent_text(git: &Git, sha: &str, path: &str) -> Option<String> {
    let parents = git.parents(sha)?;
    let Some(parent) = parents.first() else {
        return Some(String::new());
    };
    git.blob(parent, path).or_else(|| {
        git.run(&["ls-tree", parent, "--", path])
            .ok()?
            .is_empty()
            .then(String::new)
    })
}

// Git dates have one-second precision. Treat the two seconds on either side
// of a boundary as uncertain rather than accepting edits across that boundary.
const CLOCK_TOLERANCE_SECONDS: i64 = 2;

fn timestamp(r: &Value) -> Option<i64> {
    chrono::DateTime::parse_from_rfc3339(text(r, "ts")?)
        .ok()
        .map(|t| t.timestamp_millis())
}

fn commit_time(git: &Git, sha: &str) -> Option<i64> {
    git.run(&["show", "-s", "--format=%at", sha])
        .ok()?
        .trim()
        .parse::<i64>()
        .ok()?
        .checked_mul(1000)
}

fn edit_in_window(git: &Git, stream: &Stream, index: usize, sha: &str, path: &str) -> bool {
    let r = &stream.records[index];
    let Some(parents) = git.parents(sha) else {
        return false;
    };
    if r.get("ts").is_some() {
        let Some(at) = timestamp(r) else {
            return false;
        };
        let Some(end) = commit_time(git, sha) else {
            return false;
        };
        let margin = CLOCK_TOLERANCE_SECONDS * 1000;
        if at >= end - margin {
            return false;
        }
        return parents.first().is_none_or(|parent| {
            // Include deletions: an older Write must not seed a re-created file.
            git.run(&["log", "-1", "--format=%at", parent, "--", path])
                .ok()
                .is_some_and(|date| {
                    date.trim().is_empty()
                        || date
                            .trim()
                            .parse::<i64>()
                            .is_ok_and(|start| at > start * 1000 + margin)
                })
        });
    }
    // Without a time, require original commit evidence on both sides of the
    // edit. A baseCommit is the observed HEAD at the edit, not an after-state.
    let Some(parent) = parents.first() else {
        return false;
    };
    let after_parent = text(r, "baseCommit") == Some(parent.as_str())
        || stream.records[..index].iter().enumerate().any(|(i, r)| {
            r["type"] == "vcs" && !stream.copied(i) && commit_match(git, stream, r, parent)
        });
    after_parent
        && stream.records[index + 1..]
            .iter()
            .enumerate()
            .any(|(i, r)| {
                r["type"] == "vcs"
                    && !stream.copied(index + 1 + i)
                    && commit_match(git, stream, r, sha)
            })
}

fn after_commit(git: &Git, r: &Value, sha: &str) -> bool {
    timestamp(r)
        .zip(commit_time(git, sha))
        .is_some_and(|(at, end)| at > end + CLOCK_TOLERANCE_SECONDS * 1000)
}

#[derive(Debug, PartialEq)]
enum ReplayError {
    Missing,
    Ambiguous,
    Unsupported,
}
enum ReplayState {
    Known(String, String),
    Unknown,
}

/// Replay the recorded edits from the actual parent in file order. A failed
/// transition closes that path instead of reseeding it from a dirty snapshot.
fn replay_states(git: &Git, stream: &Stream, sha: &str) -> BTreeMap<usize, ReplayState> {
    let mut files = BTreeMap::<String, Option<String>>::new();
    let mut states = BTreeMap::new();
    let mut observed = BTreeSet::new();
    let mut gap = false;
    for (i, r) in stream.records.iter().enumerate() {
        if r["type"] == "gap" && !after_commit(git, r, sha) {
            files.values_mut().for_each(|state| *state = None);
            gap = true;
        }
        if r["type"] != "file_change" {
            continue;
        }
        let Some(path) = text(r, "path").and_then(|p| relative(git, stream, p)) else {
            continue;
        };
        if !edit_in_window(git, stream, i, sha, &path) {
            if !after_commit(git, r, sha) {
                if files.contains_key(&path) {
                    files.insert(path, None);
                }
                states.insert(i, ReplayState::Unknown);
            }
            continue;
        }
        if matches!(text(r, "status"), Some("failed" | "proposed")) {
            continue;
        }
        let baseline = files
            .entry(path.clone())
            .or_insert_with(|| (!gap).then(|| parent_text(git, sha, &path)).flatten());
        let next = baseline.as_ref().and_then(|before| {
            if r["status"] != "applied" || r["truncated"] == true {
                return None;
            }
            if !codex_anchors_match(git, stream, r, &path, before) {
                return None;
            }
            replay_change(git, r, sha, &path, before, observed.contains(&path))
                .map(|after| (before.clone(), after))
        });
        let state = if let Some((before, after)) = next {
            *baseline = Some(after.clone());
            observed.insert(path);
            ReplayState::Known(before, after)
        } else {
            *baseline = None;
            ReplayState::Unknown
        };
        states.insert(i, state);
    }
    states
}

/// The fallback converter keeps the original apply_patch call. Its @@ symbol
/// anchors constrain placement even though core replacement snippets lack them.
fn codex_anchors_match(git: &Git, stream: &Stream, r: &Value, path: &str, before: &str) -> bool {
    let Some(call) = text(r, "callId").and_then(|id| stream.unique_call(id)) else {
        return true;
    };
    let Some(patch) = text(call, "inputText").filter(|_| call["name"] == "apply_patch") else {
        return true;
    };
    let mut active = false;
    let mut anchors = Vec::new();
    for line in patch.lines() {
        if let Some(file) = line.strip_prefix("*** Update File: ") {
            active = relative(git, stream, file).as_deref() == Some(path);
        } else if line.starts_with("*** ") {
            active = false;
        } else if active && line.starts_with("@@") {
            anchors.push(line.strip_prefix("@@ "));
        }
    }
    let edits = r["edits"].as_array();
    anchors.iter().enumerate().all(|(i, anchor)| {
        let Some(anchor) = anchor else { return true };
        let lines: Vec<_> = before.split_inclusive('\n').collect();
        let Some(line) = unique_start(&lines, &[&format!("{anchor}\n")]) else {
            return false;
        };
        let anchor_offset: usize = lines[..line].iter().map(|line| line.len()).sum();
        edits
            .and_then(|edits| edits.get(i))
            .and_then(|e| text(e, "oldText"))
            .and_then(|old| unique_text(before, old))
            .is_some_and(|offset| offset >= anchor_offset)
    })
}

fn replay_change(
    git: &Git,
    r: &Value,
    sha: &str,
    path: &str,
    before: &str,
    observed: bool,
) -> Option<String> {
    let recorded = state_text(git, &r["before"], sha, path);
    if recorded.as_ref().is_some_and(|recorded| recorded != before) {
        return None;
    }
    let native_context = r["patch"].is_string()
        || r["_meta"]["com.anthropic.claude-code"]["result"]["structuredPatch"]
            .as_array()
            .is_some_and(|hunks| !hunks.is_empty());
    if recorded.is_none() && !native_context {
        // Partial strings can attach to a person's different line. Missing
        // original contents require complete lines at one unique placement.
        if let Some(edits) = r["edits"].as_array() {
            for edit in edits {
                let old = text(edit, "oldText")?;
                let start = unique_text(before, old)?;
                if old.is_empty()
                    || !old.ends_with('\n')
                    || (start > 0 && !before[..start].ends_with('\n'))
                {
                    return None;
                }
            }
        } else if !observed {
            let confirmed_add = r["op"] == "add"
                && before.is_empty()
                && git.parents(sha)?.first().is_none_or(|parent| {
                    git.run(&["ls-tree", parent, "--", path])
                        .is_ok_and(|tree| tree.is_empty())
                });
            if !confirmed_add {
                return None;
            }
        }
    }
    let after = if r["patch"].is_string() || r["edits"].is_array() {
        let next = apply_change(before, r).ok()?;
        if state_text(git, &r["after"], sha, path).is_some_and(|after| after != next) {
            return None;
        }
        next
    } else if r["op"] == "delete" {
        String::new()
    } else {
        state_text(git, &r["after"], sha, path)?
    };
    claude_context_matches(before, &after, r).then_some(after)
}

fn apply_change(before: &str, record: &Value) -> std::result::Result<String, ReplayError> {
    if let Some(patch) = text(record, "patch") {
        return apply_patch(before, patch);
    }
    let after = apply_edits(before, record)?;
    if !claude_context_matches(before, &after, record) {
        return Err(ReplayError::Missing);
    }
    Ok(after)
}

/// Claude's native hunks retain positions and surrounding lines even when
/// originalFile is null. Verify both sides against the replacement replay.
fn claude_context_matches(before: &str, after: &str, record: &Value) -> bool {
    let Some(hunks) =
        record["_meta"]["com.anthropic.claude-code"]["result"]["structuredPatch"].as_array()
    else {
        return true;
    };
    let before: Vec<_> = before.split_terminator('\n').collect();
    let after: Vec<_> = after.split_terminator('\n').collect();
    hunks.iter().all(|hunk| {
        let Some(lines) = hunk["lines"].as_array() else {
            return false;
        };
        let mut old = Vec::new();
        let mut new = Vec::new();
        for line in lines {
            let Some(line) = line.as_str() else {
                return false;
            };
            match line.as_bytes().first() {
                Some(b' ') => {
                    old.push(&line[1..]);
                    new.push(&line[1..]);
                }
                Some(b'-') => old.push(&line[1..]),
                Some(b'+') => new.push(&line[1..]),
                Some(b'\\') if line == "\\ No newline at end of file" => {}
                _ => return false,
            }
        }
        [
            ("oldStart", "oldLines", &before, old),
            ("newStart", "newLines", &after, new),
        ]
        .into_iter()
        .all(|(start, count, contents, expected)| {
            let Some(start) = hunk[start].as_u64().and_then(|n| usize::try_from(n).ok()) else {
                return false;
            };
            hunk[count].as_u64() == Some(expected.len() as u64)
                && (expected.is_empty() || start > 0)
                && contents.get(
                    start.saturating_sub(1)..start.saturating_sub(1).saturating_add(expected.len()),
                ) == Some(expected.as_slice())
        })
    })
}

/// Compare complete zero-context change hunks by their parent coordinates and
/// exact replacement bytes. Adjacent unexplained person changes close the hunk.
fn hunk_explained(parent: &str, committed: &str, replayed: &str, line: usize) -> bool {
    let committed_lines: Vec<_> = committed.split_inclusive('\n').collect();
    let replayed_lines: Vec<_> = replayed.split_inclusive('\n').collect();
    let diff = TextDiff::from_lines(parent, committed);
    let replay = TextDiff::from_lines(parent, replayed);
    for group in diff.grouped_ops(0) {
        let old = group.first().unwrap().old_range().start..group.last().unwrap().old_range().end;
        let new = group.first().unwrap().new_range().start..group.last().unwrap().new_range().end;
        if !new.contains(&line.saturating_sub(1)) {
            continue;
        }
        return replay.grouped_ops(0).iter().any(|ops| {
            let a = ops.first().unwrap().old_range().start..ops.last().unwrap().old_range().end;
            let b = ops.first().unwrap().new_range().start..ops.last().unwrap().new_range().end;
            a == old && replayed_lines[b] == committed_lines[new.clone()]
        });
    }
    false
}

fn old_mentions(r: &Value, target: &str) -> bool {
    if let Some(before) = text(&r["before"], "text") {
        return before.split_inclusive('\n').any(|line| line == target);
    }
    if let Some(hunks) =
        r["_meta"]["com.anthropic.claude-code"]["result"]["structuredPatch"].as_array()
    {
        if !hunks.is_empty() {
            return hunks
                .iter()
                .flat_map(|h| h["lines"].as_array().into_iter().flatten())
                .filter_map(Value::as_str)
                .any(|line| {
                    line.strip_prefix([' ', '-'])
                        .is_some_and(|old| old == target.trim_end_matches('\n'))
                });
        }
    }
    if let Some(patch) = text(r, "patch") {
        return patch.lines().any(|line| {
            line.strip_prefix([' ', '-'])
                .is_some_and(|old| old == target.trim_end_matches('\n'))
        });
    }
    r["edits"]
        .as_array()
        .into_iter()
        .flatten()
        .any(|e| text(e, "oldText").is_some_and(|old| !old.is_empty() && target.contains(old)))
}

/// The first recorded view is independent of Git and recording-machine clocks.
fn already_observed(git: &Git, stream: &Stream, index: usize, path: &str, target: &str) -> bool {
    for (i, r) in stream.records.iter().enumerate().take(index + 1) {
        if r["type"] == "tool_result" && r["status"] == "completed" {
            let call = text(r, "callId").and_then(|id| stream.unique_call(id));
            if let Some(call) = call.filter(|c| c["kind"] == "read") {
                let input = r.get("input").unwrap_or(&call["input"]);
                let file = text(input, "file_path").or_else(|| text(input, "path"));
                if file.and_then(|p| relative(git, stream, p)).as_deref() == Some(path) {
                    let contents = r["content"]
                        .as_array()
                        .into_iter()
                        .flatten()
                        .filter_map(|p| text(p, "text"))
                        .collect::<String>();
                    return contents.contains(target.trim_end_matches('\n'));
                }
            }
        }
        if r["type"] == "file_change"
            && text(r, "path")
                .and_then(|p| relative(git, stream, p))
                .as_deref()
                == Some(path)
            && r["status"] == "applied"
        {
            return old_mentions(r, target)
                || (i < index
                    && text(&r["after"], "text")
                        .is_some_and(|s| s.split_inclusive('\n').any(|line| line == target)));
        }
    }
    false
}

/// Preselect possible removals once per query. The store may contain thousands
/// of competing sessions, so disjoint insertions must not cause a quadratic scan.
fn possible_removals(streams: &[Stream], target: &str) -> Vec<(usize, usize)> {
    let mut removals = Vec::new();
    for (s, stream) in streams.iter().enumerate() {
        let mut previous = BTreeMap::<&str, &str>::new();
        for (i, r) in stream.records.iter().enumerate() {
            if r["type"] != "file_change"
                || matches!(text(r, "status"), Some("failed" | "proposed"))
            {
                continue;
            }
            // A later recorded before-state can expose an unrecorded reset.
            // Re-adding the same text cannot preserve the earlier origin.
            let reset = text(r, "path")
                .and_then(|path| previous.get(path))
                .zip(text(&r["before"], "text"))
                .is_some_and(|(last, before)| last.contains(target) && !before.contains(target));
            let removes = if let Some(after) = text(&r["after"], "text") {
                if let Some(path) = text(r, "path") {
                    previous.insert(path, after);
                }
                !after.split_inclusive('\n').any(|line| line == target)
            } else if r["op"] == "delete" {
                true
            } else if let Some(patch) = text(r, "patch") {
                patch
                    .lines()
                    .any(|line| line.strip_prefix('-') == Some(target.trim_end_matches('\n')))
            } else if r["edits"].is_array() {
                old_mentions(r, target)
            } else {
                true
            };
            if removes || reset {
                removals.push((s, i));
            }
        }
    }
    removals
}

fn survives_store(
    git: &Git,
    streams: &[Stream],
    removals: &[(usize, usize)],
    candidate: (usize, usize),
    path: &str,
) -> bool {
    removals.iter().all(|&(s, i)| {
        if s == candidate.0 {
            return true; // File order is checked separately.
        }
        let stream = &streams[s];
        let r = &stream.records[i];
        let same_path = ["path", "oldPath"].iter().any(|key| {
            text(r, key)
                .and_then(|p| relative(git, stream, p))
                .as_deref()
                == Some(path)
        });
        // Independent machine clocks cannot establish that a destructive edit
        // preceded this candidate or followed its commit. Only recorded stream
        // relationships can establish the earlier side. Unordered removals veto.
        !same_path
            || parent_before_child(stream, i, &streams[candidate.0])
            || delegation_bounds(&streams[candidate.0], stream)
                .1
                .is_some_and(|result| candidate.1 > result)
    })
}

fn carry_lines(before: &str, after: &str, origins: &[bool]) -> Vec<bool> {
    if before == after {
        return origins.to_vec();
    }
    let old: Vec<_> = before.split_inclusive('\n').collect();
    let new: Vec<_> = after.split_inclusive('\n').collect();
    let mut result = vec![false; new.len()];
    for change in TextDiff::from_lines(before, after).iter_all_changes() {
        if change.tag() == ChangeTag::Equal {
            if let (Some(a), Some(b)) = (change.old_index(), change.new_index()) {
                // Repeated lines cannot establish which copy survived a change.
                result[b] = origins.get(a).copied().unwrap_or(false)
                    && old.iter().filter(|s| **s == change.value()).count() == 1
                    && new.iter().filter(|s| **s == change.value()).count() == 1;
            }
        }
    }
    result
}

/// Keep only inserted lines that survive every later applied edit in this
/// stream, in file order, up to this commit. Re-adding a line loses its origin.
fn survives_session(
    git: &Git,
    stream: &Stream,
    states: &BTreeMap<usize, ReplayState>,
    index: usize,
    sha: &str,
    path: &str,
    target: &str,
) -> bool {
    let (mut current, mut origins) = match states.get(&index) {
        Some(ReplayState::Known(before, after)) => {
            let mut origins = vec![false; after.split_inclusive('\n').count()];
            for change in TextDiff::from_lines(before, after).iter_all_changes() {
                if change.tag() == ChangeTag::Insert && change.value() == target {
                    if let Some(i) = change.new_index() {
                        origins[i] = true;
                    }
                }
            }
            (after.clone(), origins)
        }
        _ => return false,
    };
    let mut path = path.to_owned();
    for (i, r) in stream.records.iter().enumerate().skip(index + 1) {
        if after_commit(git, r, sha) {
            continue;
        }
        if r["type"] == "gap" {
            return false;
        }
        if r["type"] != "file_change" {
            continue;
        }
        let dest = text(r, "path").and_then(|p| relative(git, stream, p));
        let source = if matches!(text(r, "op"), Some("move" | "copy")) {
            text(r, "oldPath").and_then(|p| relative(git, stream, p))
        } else {
            dest.clone()
        };
        if source.as_deref() != Some(&path) && dest.as_deref() != Some(&path) {
            continue;
        }
        if matches!(text(r, "status"), Some("failed" | "proposed")) {
            continue;
        }
        if r["status"] != "applied"
            || !edit_in_window(git, stream, i, sha, dest.as_deref().unwrap_or(&path))
        {
            return false;
        }
        if r["op"] == "delete" {
            return false;
        }
        if matches!(text(r, "op"), Some("move" | "copy")) {
            let Some(dest) = dest else { return false };
            path = dest;
            // A pure move carries existing text without newly authoring it.
            if r.get("before").is_none()
                && r.get("after").is_none()
                && r.get("patch").is_none()
                && r.get("edits").is_none()
            {
                continue;
            }
        }
        let Some(ReplayState::Known(before, after)) = states.get(&i) else {
            return false;
        };
        origins = carry_lines(&current, before, &origins);
        origins = carry_lines(before, after, &origins);
        current = after.clone();
        if !origins.iter().any(|o| *o) {
            return false;
        }
    }
    origins.iter().any(|o| *o)
}
fn apply_edits(before: &str, record: &Value) -> std::result::Result<String, ReplayError> {
    let edits = record["edits"].as_array().ok_or(ReplayError::Unsupported)?;
    let result = &record["_meta"]["com.anthropic.claude-code"]["result"];
    let replace_all = result["replaceAll"] == true || result["replace_all"] == true;
    let mut after = before.to_owned();
    for edit in edits {
        let old = text(edit, "oldText").ok_or(ReplayError::Unsupported)?;
        let new = text(edit, "newText").ok_or(ReplayError::Unsupported)?;
        if old.is_empty() {
            return Err(ReplayError::Unsupported);
        }
        if !after.contains(old) {
            return Err(ReplayError::Missing);
        }
        if replace_all {
            after = after.replace(old, new);
        } else {
            let start = unique_text(&after, old).ok_or(ReplayError::Ambiguous)?;
            after.replace_range(start..start + old.len(), new);
        }
    }
    Ok(after)
}

/// Apply unified hunks by their exact, unique old lines, including hunk-only
/// Codex FileChange diffs. No commands from a recorded patch are executed.
fn apply_patch(before: &str, patch: &str) -> std::result::Result<String, ReplayError> {
    let mut hunks = Vec::<(String, String)>::new();
    let mut active = false;
    let mut previous = None;
    for line in patch.split_inclusive('\n') {
        if line.starts_with("@@") {
            active = true;
            previous = None;
            hunks.push((String::new(), String::new()));
        } else if active {
            let (old, new) = hunks.last_mut().ok_or(ReplayError::Unsupported)?;
            match line.as_bytes().first() {
                Some(b' ') => {
                    old.push_str(&line[1..]);
                    new.push_str(&line[1..]);
                }
                Some(b'-') => old.push_str(&line[1..]),
                Some(b'+') => new.push_str(&line[1..]),
                Some(b'\\') if line.trim_end() == "\\ No newline at end of file" => {
                    if matches!(previous, Some(b' ' | b'-')) && old.ends_with('\n') {
                        old.pop();
                    }
                    if matches!(previous, Some(b' ' | b'+')) && new.ends_with('\n') {
                        new.pop();
                    }
                    continue;
                }
                _ => return Err(ReplayError::Unsupported),
            }
            previous = line.as_bytes().first().copied();
        } else if !(line.starts_with("diff ")
            || line.starts_with("index ")
            || line.starts_with("--- ")
            || line.starts_with("+++ "))
        {
            return Err(ReplayError::Unsupported);
        }
    }
    if hunks.is_empty() {
        return Err(ReplayError::Unsupported);
    }
    let mut after = before.to_owned();
    for (old, new) in hunks {
        // Context-free insertion is only unambiguous in an empty file.
        let start = if old.is_empty() {
            if !after.is_empty() {
                return Err(ReplayError::Ambiguous);
            }
            0
        } else {
            if !after.contains(&old) {
                return Err(ReplayError::Missing);
            }
            unique_text(&after, &old).ok_or(ReplayError::Ambiguous)?
        };
        let end = start + old.len();
        if (start != 0 && !after[..start].ends_with('\n'))
            || (end != after.len() && !old.ends_with('\n'))
        {
            return Err(ReplayError::Missing);
        }
        after.replace_range(start..end, &new);
    }
    Ok(after)
}

fn states_match(before: &str, after: &str, blob: &str, line: usize) -> bool {
    let lines: Vec<_> = blob.split_inclusive('\n').collect();
    let after_lines: Vec<_> = after.split_inclusive('\n').collect();
    if let Some(start) = unique_start(&lines, &after_lines) {
        let ambiguous = lines.get(line.saturating_sub(1)).is_some_and(|target| {
            before.split_inclusive('\n').any(|s| s == *target)
                && after_lines.iter().filter(|s| **s == *target).count() > 1
        });
        return !ambiguous
            && TextDiff::from_lines(before, after)
                .iter_all_changes()
                .any(|c| {
                    c.tag() == ChangeTag::Insert
                        && c.new_index().is_some_and(|i| start + i + 1 == line)
                });
    }
    let Some(target) = blob.split_inclusive('\n').nth(line.saturating_sub(1)) else {
        return false;
    };
    // A distinct inserted line can survive unrelated later edits to the full state.
    if blob.split_inclusive('\n').filter(|s| *s == target).count() != 1
        || after.split_inclusive('\n').filter(|s| *s == target).count() != 1
        || before.split_inclusive('\n').any(|s| s == target)
    {
        return false;
    }
    TextDiff::from_lines(before, after)
        .iter_all_changes()
        .any(|c| c.tag() == ChangeTag::Insert && c.value() == target)
}

fn state_text(git: &Git, state: &Value, sha: &str, path: &str) -> Option<String> {
    if let Some(s) = text(state, "text") {
        return Some(s.into());
    }
    let id = text(state, "objectId")?;
    match text(state, "objectIdType").unwrap_or("git-blob-sha1") {
        "git-blob-sha1" | "git-blob-sha256"
            if full_id(id)
                && id.len()
                    == if text(state, "objectIdType") == Some("git-blob-sha256") {
                        64
                    } else {
                        40
                    } =>
        {
            let raw = git.bytes(&["cat-file", "blob", id]).ok()?;
            String::from_utf8(raw).ok()
        }
        "sha256" => {
            let candidates =
                std::iter::once(sha.to_owned()).chain(git.parents(sha).unwrap_or_default());
            candidates
                .filter_map(|candidate| git.blob(&candidate, path))
                .find(|blob| digest(blob.as_bytes()) == id)
        }
        _ => None,
    }
}
fn evidence(stream: &Stream, r: &Value) -> Value {
    let session = stream.session();
    let call = text(r, "callId").and_then(|id| stream.unique_call(id));
    let inference = call.and_then(|c| text(c, "inferenceId")).and_then(|id| {
        let v: Vec<_> = stream
            .records
            .iter()
            .filter(|r| r["type"] == "inference" && text(r, "id") == Some(id))
            .collect();
        (v.len() == 1).then(|| v[0])
    });
    let turn = call
        .and_then(|r| text(r, "turnId"))
        .or_else(|| text(r, "turnId"))
        .or_else(|| inference.and_then(|i| text(i, "turnId")));
    let prompts: Vec<_> = stream
        .records
        .iter()
        .filter(|m| m["type"] == "message" && turn.is_some() && text(m, "turnId") == turn)
        .filter_map(|m| {
            let content: Vec<_> = m["content"]
                .as_array()?
                .iter()
                .filter(|p| {
                    p.get("author").or_else(|| m.get("author")) == Some(&json!("human"))
                        && p.get("origin").or_else(|| m.get("origin")) != Some(&json!("compaction"))
                })
                .collect();
            (!content.is_empty()).then(|| json!({"reference":cite(&session,m),"content":content}))
        })
        .collect();
    let approvals: Vec<_> = stream
        .records
        .iter()
        .filter(|a| a["type"] == "approval" && call.is_some() && a.get("callId") == r.get("callId"))
        .map(|a| json!({"reference":cite(&session,a),"decision":a}))
        .collect();
    let model = inference
        .map(|i| {
            if let Some(served) = i["model"].get("id") {
                json!({"kind":"served","value":served,"reference":cite(&session,i)})
            } else if let Some(requested) = i["model"].get("requested") {
                json!({"kind":"requested","value":requested,"reference":cite(&session,i)})
            } else {
                Value::Null
            }
        })
        .unwrap_or(Value::Null);
    let mut unresolved = Vec::new();
    if call.is_none() && r.get("callId").is_some() {
        unresolved.push("call");
    }
    if model.is_null() {
        unresolved.push("model");
    }
    if prompts.is_empty() {
        unresolved.push("prompt");
    }
    json!({"session":session,"reference":cite(&session,r),"actor":r.get("actor"),"credit":match text(r,"actor") {Some("human")=>"person",Some("external")=>"untracked",_=>"session"},"call":call.map(|c|cite(&session,c)),"model":model,"prompts":prompts,"approvals":approvals,"unresolved":unresolved})
}

fn parent_before_child(parent: &Stream, parent_index: usize, child: &Stream) -> bool {
    let link = &child.records[0]["parent"];
    if text(link, "session") == Some(parent.session().as_str()) && link["kind"] == "fork" {
        if let Some(boundary) = text(link, "record").and_then(|id| {
            parent
                .records
                .iter()
                .position(|r| text(r, "id") == Some(id))
        }) {
            if parent_index <= boundary {
                return true;
            }
        }
    }
    delegation_bounds(parent, child)
        .0
        .is_some_and(|launch| parent_index < launch)
}
fn delegation_bounds(parent: &Stream, child: &Stream) -> (Option<usize>, Option<usize>) {
    let parent_ref = parent.session();
    let child_ref = child.session();
    let link = &child.records[0]["parent"];
    let call =
        if text(link, "session") == Some(parent_ref.as_str()) && link["kind"] == "subagent" {
            text(link, "callId")
        } else {
            None
        }
        .or_else(|| {
            parent
                .records
                .iter()
                .find(|r| {
                    matches!(text(r, "type"), Some("tool_call" | "tool_result"))
                        && text(&r["subagent"], "session") == Some(child_ref.as_str())
                })
                .and_then(|r| text(r, "callId"))
        });
    let Some(call) = call.filter(|id| parent.unique_call(id).is_some()) else {
        return (None, None);
    };
    let launch = parent
        .records
        .iter()
        .position(|r| r["type"] == "tool_call" && text(r, "callId") == Some(call));
    let completed = parent
        .result(call)
        .filter(|r| r["status"] == "completed")
        .and_then(|result| parent.records.iter().position(|r| std::ptr::eq(r, result)));
    (launch, completed)
}
/// Only native relationship links can order edits in different sessions.
fn edit_order(streams: &[Stream], positions: &[(usize, usize)]) -> Vec<Vec<usize>> {
    let mut by_reference = BTreeMap::<String, Vec<usize>>::new();
    let mut by_stream = BTreeMap::new();
    for (node, &(stream, _)) in positions.iter().enumerate() {
        by_reference
            .entry(streams[stream].session())
            .or_default()
            .push(node);
        by_stream.insert(stream, node);
    }
    let mut pairs = BTreeSet::new();
    for (&stream, &node) in &by_stream {
        let header = &streams[stream].records[0];
        let parent = text(&header["parent"], "session");
        let references = parent.into_iter().chain(
            streams[stream]
                .records
                .iter()
                .filter(|r| matches!(text(r, "type"), Some("tool_call" | "tool_result")))
                .filter_map(|r| text(&r["subagent"], "session")),
        );
        for reference in references {
            if reference == streams[stream].session() {
                continue;
            }
            for &other in by_reference.get(reference).into_iter().flatten() {
                pairs.insert((node.min(other), node.max(other)));
            }
        }
    }
    let mut edges = vec![Vec::new(); positions.len()];
    for (a, b) in pairs {
        for (from, to) in [(a, b), (b, a)] {
            let x = positions[from];
            let y = positions[to];
            if parent_before_child(&streams[x.0], x.1, &streams[y.0])
                || delegation_bounds(&streams[y.0], &streams[x.0])
                    .1
                    .is_some_and(|result| y.1 > result)
            {
                edges[from].push(to);
            }
        }
    }
    edges
}

/// Sink strongly connected components retain unresolved competitors, including cycles.
fn latest_edits(edges: &[Vec<usize>]) -> Vec<bool> {
    let mut reverse = vec![Vec::new(); edges.len()];
    for (from, tos) in edges.iter().enumerate() {
        for &to in tos {
            reverse[to].push(from);
        }
    }
    let mut visited = vec![false; edges.len()];
    let mut order = Vec::new();
    for node in 0..edges.len() {
        let mut stack = vec![(node, false)];
        while let Some((at, finished)) = stack.pop() {
            if finished {
                order.push(at);
            } else if !visited[at] {
                visited[at] = true;
                stack.push((at, true));
                stack.extend(edges[at].iter().map(|&to| (to, false)));
            }
        }
    }
    let mut component = vec![usize::MAX; edges.len()];
    for node in order.into_iter().rev() {
        if component[node] != usize::MAX {
            continue;
        }
        let mut stack = vec![node];
        component[node] = node;
        while let Some(at) = stack.pop() {
            for &to in &reverse[at] {
                if component[to] == usize::MAX {
                    component[to] = node;
                    stack.push(to);
                }
            }
        }
    }
    let mut sink = vec![true; edges.len()];
    for (from, tos) in edges.iter().enumerate() {
        if tos.iter().any(|&to| component[from] != component[to]) {
            sink[component[from]] = false;
        }
    }
    component.into_iter().map(|c| sink[c]).collect()
}

pub fn run(options: Options) -> Result<Value> {
    if options.line == 0 {
        return Err("line must be at least 1".into());
    }
    let initial = Git::new(options.repo.canonicalize()?);
    let git = Git::new(
        PathBuf::from(initial.run(&["rev-parse", "--show-toplevel"])?.trim()).canonicalize()?,
    );
    let path = if options.file.is_absolute() {
        options.file.clone()
    } else {
        git.root.join(&options.file)
    };
    let path = normalize(&path);
    let path = path
        .strip_prefix(&git.root)
        .map_err(|_| "file is outside repository")?
        .to_str()
        .ok_or("non UTF-8 path")?;
    if path.chars().any(char::is_control) {
        return Err("control characters in paths are unsupported".into());
    }
    let blame = git.run(&[
        "blame",
        "--no-textconv",
        "--line-porcelain",
        "-L",
        &format!("{},{}", options.line, options.line),
        "--",
        path,
    ])?;
    let first: Vec<_> = blame
        .lines()
        .next()
        .ok_or("missing Git blame")?
        .split_whitespace()
        .collect();
    if first.len() < 3 {
        return Err("invalid Git blame response".into());
    }
    let commit = first[0];
    let original_line: usize = first[1].parse()?;
    let original_path = blame
        .lines()
        .find_map(|s| s.strip_prefix("filename "))
        .ok_or("missing blame path")?;
    if original_path.starts_with('"') || original_path.chars().any(char::is_control) {
        return Err("quoted blame path is unresolved".into());
    }
    let mut streams = Vec::new();
    let mut files = BTreeSet::new();
    let mut source_errors = 0;
    for source in options.sessions {
        if source.is_dir() {
            for entry in walkdir::WalkDir::new(source).follow_links(false) {
                let entry = entry?;
                let p = entry.path();
                if entry.file_type().is_file()
                    && p.extension().is_some_and(|e| e == "jsonl")
                    && !p.to_string_lossy().ends_with(".annotations.jsonl")
                {
                    files.insert(p.to_owned());
                }
            }
        } else {
            files.insert(source);
        }
    }
    for p in files {
        match Stream::load(&p) {
            Ok(s) => streams.push(s),
            Err(_) => source_errors += 1,
        }
    }
    // Corrections are applied in file order before considering annotation rewrites.
    let mut annotation_pairs = Vec::new();
    for file in options.annotations {
        let mut reader = Reader::new(BufReader::new(fs::File::open(file)?), LIMIT);
        let mut annotations = BTreeMap::new();
        while let Some(line) = reader.read()? {
            if let Line::Record(r) = line {
                if let Some(previous) = text(&r, "supersedes") {
                    annotations.remove(previous);
                }
                if let Some(id) = text(&r, "id") {
                    annotations.insert(id.to_owned(), r);
                }
            } else {
                source_errors += 1;
            }
        }
        for a in annotations
            .values()
            .filter(|a| a["kind"] == "vcs" && a["data"]["status"] == "completed")
        {
            let belongs = streams.iter().find(|s| {
                text(a, "session")
                    .is_some_and(|r| r.split('#').next() == Some(s.session().as_str()))
            });
            if text(&a["data"], "repo").is_some_and(|p| same_repo(&git, p))
                || belongs.is_some_and(|s| vcs_repo(&git, s, &a["data"]))
            {
                annotation_pairs.extend(rewrites(&a["data"]));
            }
        }
    }
    let mut pairs = annotation_pairs;
    for stream in &streams {
        for (i, r) in stream
            .records
            .iter()
            .enumerate()
            .filter(|(_, r)| r["type"] == "vcs")
        {
            if !stream.copied(i) && vcs_repo(&git, stream, r) && successful(stream, r) {
                pairs.extend(rewrites(r));
            }
        }
    }
    let mut candidates = BTreeSet::from([commit.to_owned()]);
    let mut pending = vec![commit.to_owned()];
    while let Some(to) = pending.pop() {
        for (from, dest) in &pairs {
            if dest == &to
                && from != dest
                && git.exists(from)
                && git.exists(dest)
                && candidates.insert(from.clone())
            {
                pending.push(from.clone());
            }
        }
    }
    let final_blob = git.blob(commit, original_path).unwrap_or_default();
    let target = final_blob.split_inclusive('\n').nth(original_line - 1);
    let final_added = git.added(commit, original_path).contains(&original_line);
    let mut committed = Vec::new();
    let mut edited = Vec::new();
    let mut edit_positions = Vec::new();
    let mut alternatives = Vec::new();
    let mut touched = BTreeMap::new();
    // These repository facts are shared by every session being inspected.
    let mut candidate_files: Vec<_> = candidates
        .iter()
        .filter_map(|sha| {
            let blob = git.blob(sha, original_path)?;
            let positions: Vec<_> = blob
                .split_inclusive('\n')
                .enumerate()
                .filter(|(_, s)| Some(*s) == target)
                .map(|(i, _)| i + 1)
                .collect();
            let line = if sha == commit {
                Some(original_line)
            } else if positions.len() == 1 {
                Some(positions[0])
            } else {
                None
            }?;
            (final_added && git.added(sha, original_path).contains(&line))
                .then_some((sha, blob, line))
        })
        .collect();
    // A rewrite can change its commit date. For a surviving line, use the
    // earliest recorded predecessor that added it, not the rewrite's later date.
    let line_commits: BTreeSet<_> = candidates
        .iter()
        .filter(|sha| {
            git.blob(sha, original_path).is_some_and(|blob| {
                let added = git.added(sha, original_path);
                blob.split_inclusive('\n')
                    .enumerate()
                    .any(|(i, line)| Some(line) == target && added.contains(&(i + 1)))
            })
        })
        .cloned()
        .collect();
    candidate_files.retain(|(sha, _, _)| {
        let mut pending = vec![(*sha).clone()];
        let mut seen = BTreeSet::new();
        while let Some(to) = pending.pop() {
            for (from, dest) in &pairs {
                if dest == &to && seen.insert(from.clone()) {
                    if from != *sha && line_commits.contains(from) {
                        return false;
                    }
                    pending.push(from.clone());
                }
            }
        }
        true
    });
    let removals = possible_removals(&streams, target.unwrap_or_default());
    for (session_index, stream) in streams.iter().enumerate() {
        let mut matches = Vec::new();
        for sha in &candidates {
            for (i, r) in stream
                .records
                .iter()
                .enumerate()
                .filter(|(_, r)| r["type"] == "vcs")
            {
                if !stream.copied(i) && commit_match(&git, stream, r, sha) {
                    committed.push(json!({"session":stream.session(),"reference":cite(&stream.session(),r),"commit":sha,"introducingCommit":commit,"actor":r.get("actor"),"credit":match text(r,"actor") {Some("human")=>"person",Some("external")=>"untracked",_=>"session"}}));
                }
            }
        }
        for (sha, blob, line) in &candidate_files {
            let states = replay_states(&git, stream, sha);
            let explained = states
                .iter()
                .rev()
                .find(|(i, _)| {
                    text(&stream.records[**i], "path")
                        .and_then(|p| relative(&git, stream, p))
                        .as_deref()
                        == Some(original_path)
                })
                .is_some_and(|(_, state)| match state {
                    ReplayState::Known(_, replayed) => parent_text(&git, sha, original_path)
                        .is_some_and(|parent| hunk_explained(&parent, blob, replayed, *line)),
                    ReplayState::Unknown => false,
                });
            let mut candidate_path = original_path.to_owned();
            for (i, r) in stream
                .records
                .iter()
                .enumerate()
                .rev()
                .filter(|(_, r)| r["type"] == "file_change")
            {
                if stream.copied(i) {
                    continue;
                }
                let Some(rpath) = text(r, "path").and_then(|p| relative(&git, stream, p)) else {
                    continue;
                };
                if rpath != candidate_path {
                    continue;
                }
                touched.insert(
                    cite(&stream.session(), r),
                    json!({"session":stream.session(),"reference":cite(&stream.session(),r)}),
                );
                let matched = match states.get(&i) {
                    Some(ReplayState::Known(before, after)) => {
                        states_match(before, after, blob, *line)
                    }
                    _ => false,
                };
                if r["status"] == "applied"
                    && r["truncated"] != true
                    && matched
                    && explained
                    && target.is_some_and(|target| {
                        !already_observed(&git, stream, i, &rpath, target)
                            && survives_session(&git, stream, &states, i, sha, &rpath, target)
                            && survives_store(&git, &streams, &removals, (session_index, i), &rpath)
                    })
                {
                    matches.push((i, evidence(stream, r)));
                }
                if r["status"] == "applied"
                    && matches!(text(r, "op"), Some("move" | "copy"))
                    && edit_in_window(&git, stream, i, sha, &rpath)
                {
                    if let Some(old) = text(r, "oldPath").and_then(|p| relative(&git, stream, p)) {
                        candidate_path = old;
                    }
                }
            }
        }
        matches.sort_by_key(|(i, _)| *i);
        matches.dedup_by_key(|(i, _)| *i);
        if let Some((index, last)) = matches.pop() {
            edit_positions.push((session_index, index));
            edited.push(last);
        }
        alternatives.extend(matches.into_iter().map(|(_, v)| v));
    }
    let retain = latest_edits(&edit_order(&streams, &edit_positions));
    let mut latest = Vec::new();
    for (i, value) in edited.into_iter().enumerate() {
        if retain[i] {
            latest.push(value);
        } else {
            alternatives.push(value);
        }
    }
    let edited = latest;
    let status = if edited.is_empty() {
        "unknown"
    } else if edited.len() > 1 {
        "unresolved"
    } else {
        "matched"
    };
    let available = streams.iter().map(Stream::session).collect();
    Ok(
        json!({"file":path,"line":options.line,"introducingCommit":commit,"pathAtCommit":original_path,"lineAtCommit":original_line,
        "editedBy":edited,"editStatus":status,"alternatives":alternatives,"committedBy":committed,"touched":touched.into_values().collect::<Vec<_>>(),
        "sessions":streams.iter().map(|s|resolved_diagnostics(s,&available)).collect::<Vec<_>>(),"relationships":relationships(&streams),"sourceErrors":source_errors,"proof":false}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn state_matches_require_exact_surviving_lines() {
        assert!(states_match(
            "prefix old suffix\n",
            "prefix new suffix\n",
            "prefix new suffix\n",
            1
        ));
        assert!(!states_match(
            "prefix old suffix\n",
            "prefix new suffix\n",
            "prefix new suffix # human\n",
            1
        ));
        assert!(!states_match("old", "new", "new suffix\n", 1));
    }
    #[test]
    fn patch_replay_preserves_newlines_and_rejects_ambiguous_or_partial_lines() {
        assert_eq!(
            apply_patch("old\n", "@@ -1 +1 @@\n-old\n+new\n"),
            Ok("new\n".into())
        );
        assert_eq!(apply_patch("old", "@@ -1 +1 @@\n-old\n\\ No newline at end of file\n+new\n\\ No newline at end of file\n"), Ok("new".into()));
        assert_eq!(
            apply_patch("old\nold\n", "@@\n-old\n+new\n"),
            Err(ReplayError::Ambiguous)
        );
        assert_eq!(
            apply_patch("prefix old\n", "@@\n-old\n+new\n"),
            Err(ReplayError::Missing)
        );
        assert_eq!(
            apply_patch("old\n", "@@\n+new\n"),
            Err(ReplayError::Ambiguous)
        );
        assert_eq!(
            apply_patch("old\n", "@@\n-old\n+new\ninvalid\n"),
            Err(ReplayError::Unsupported)
        );
    }
    #[test]
    fn replay_requires_unique_old_text_and_applies_edits_in_order() {
        let mut record = json!({"edits":[{"oldText":"old","newText":"middle"},{"oldText":"middle","newText":"new\nextra"}]});
        assert_eq!(
            apply_edits("prefix old suffix\n", &record).ok().as_deref(),
            Some("prefix new\nextra suffix\n")
        );
        assert!(apply_edits("old old\n", &record).is_err());
        record["_meta"] = json!({"com.anthropic.claude-code":{"result":{"replaceAll":true}}});
        assert_eq!(
            apply_edits("old old\n", &record).ok().as_deref(),
            Some("new\nextra new\nextra\n")
        );
        record["edits"] = json!([{"oldText":"","newText":"new"}]);
        assert!(apply_edits("old", &record).is_err());
    }
    #[test]
    fn replay_does_not_carry_a_baseline_across_missing_or_unknown_history() {
        let temp = tempfile::tempdir().unwrap();
        let git = Git::new(temp.path().canonicalize().unwrap());
        for interruption in [
            json!({"type":"gap","id":"gap","reason":"not_retained"}),
            json!({"type":"file_change","id":"unknown","path":"file.txt","op":"modify","status":"unknown"}),
        ] {
            let stream = Stream {
                records: vec![
                    json!({"type":"session","agent":{"name":"com.example.agent"},"sessionId":"synthetic","cwd":git.root}),
                    json!({"type":"file_change","id":"write","path":"file.txt","op":"add","status":"applied","after":{"text":"old\n"}}),
                    interruption,
                    json!({"type":"file_change","id":"later","path":"file.txt","op":"modify","status":"applied","after":{"text":"dirty external line\nnew\n"}}),
                ],
                warnings: vec![],
                sha256: String::new(),
            };
            assert!(matches!(
                replay_states(&git, &stream, "unused").get(&3),
                Some(ReplayState::Unknown)
            ));
        }
    }

    #[test]
    fn order_graph_preserves_competitors_cycles_and_transitive_links() {
        assert_eq!(
            latest_edits(&[vec![1], vec![2], vec![], vec![]]),
            vec![false, false, true, true]
        );
        assert_eq!(
            latest_edits(&[vec![1], vec![0], vec![]]),
            vec![true, true, true]
        );
        assert_eq!(
            latest_edits(&[vec![1], vec![0, 2], vec![]]),
            vec![false, false, true]
        );
    }
}

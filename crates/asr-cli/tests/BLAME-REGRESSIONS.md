# Blame regression coverage

`blame_replay.rs` converts native Claude Code and Codex records in scratch Git
repositories. It validates each stream and queries the real CLI. A query names
its permitted causing call or requires unknown. A named call may also become
unknown when the evidence does not explain the complete committed hunk. An
incorrect call still fails. `tools.rs` and `convert_blame.rs` retain positive
checks that require matches, citations, models and commit evidence.

| Review cases | Regression tests |
| --- | --- |
| B1, partial and multiline replacements with and without original contents, mixed and later person commits | `person_changes_after_claude_are_unknown_in_later_and_mixed_commits` |
| B2, neighboring patches, surviving multiline edits, shifted writes and formatting | `codex_replays_neighboring_patches_and_rejects_person_changes`, `claude_recovers_surviving_multiline_edits_and_preserves_person_lines`, formatter tests and `convert_blame.rs` |
| C1, old flag edits, renames, replaceAll and competing short edits | `c1_old_flag_rename_and_replace_all_cannot_replay_on_later_person_commits`, `c1_old_short_edit_is_not_a_competitor_for_a_second_sessions_other_flag` |
| C1, deleted Claude writes, Codex adds, reverted and retyped lines | `c1_deleted_claude_writes_and_codex_adds_do_not_credit_recreated_files`, `c1_retyped_reverts_are_unknown_and_revert_of_revert_is_conservative` |
| C2, later sessions with original contents, an earlier write, later unrelated work and uncertain times | `c2_future_edits_cannot_credit_existing_lines_with_any_recorded_baseline`, `timestamps_missing_invalid_or_inside_clock_margin_stay_unknown` |
| C3, same-session undo, with and without contents, and an undo after the commit | `c3_undone_edits_are_not_present_in_the_sessions_net_result`, `c3_later_undo_after_the_commit_does_not_erase_the_committed_edit` |
| C4, independently typed identical edits and shared new-file text | `c4_identical_person_retyping_is_indistinguishable_from_recorded_text` |
| Renames, mixed adjacent and distant person changes, moved lines, independent sessions, separate and shared commits, resets and squash merges | The `reviewer_` tests, `an_unrelated_parent_commit_does_not_reset_the_file_time_window` and move tests in `tools.rs` |
| D1, person commits followed by a session and an amend, rebase or cherry-pick, with and without original contents | `d1_later_roundtrips_do_not_acquire_credit_after_amend_rebase_or_cherry_pick` |
| D1, agent work amended into a person commit, person additions to agent commits, trailing-space amends, agent rebases and cherry-picks with and without -x | `recheck4_rewrites_keep_person_lines_unknown_and_recheck_surviving_agent_hunks` |
| D2, slow agent clocks, fast Git clocks, first original contents, earlier writes and read results | `d2_first_observation_blocks_skewed_roundtrips_from_original_write_and_old_text`, `first_read_and_untimed_other_session_removals_are_clock_free_vetoes` |
| D3, plain ASR and Claude partial replacements without context | `d3_context_free_partial_edits_cannot_attach_to_a_persons_other_flag` |
| D4, another session or subagent undoes the origin, Claude with and without contents and Codex patches | `d4_other_sessions_and_subagents_undo_the_original_origin` |
| D4, untimed removals, clock-skewed removals and a stale before-state after delegation | `d4_generated_skewed_cross_session_undo_cannot_leave_an_earlier_agent_credited` and delegation tests in `tools.rs` |
| Separate and adjacent session edits, stale parallel writes, partial staging and later commits | `recheck4_mixed_sessions_stale_writes_and_partial_staging_are_conservative` |
| Agent changes staged before an unstaged undo, person changes staged before an agent edit and excluded agent work | `recheck4_index_and_worktree_divergence_does_not_invent_committed_origins` |
| CRLF, autocrlf, newline conversion, trailing spaces, tabs, whitespace round trips, agent reindentation and changed Codex context | `recheck4_crlf_autocrlf_whitespace_and_context_variants_never_credit_person_lines` |
| D5 and C5, short values, full states, split patches, escaped copies and unrelated calls | Mask tests in `tools.rs` and the converted mask test in `blame_replay.rs` |
| D7, a Codex symbol anchor with a fuzzy old line and an exact copy elsewhere, including a person edit at that copy | `recheck4_codex_apply_patch_symbol_anchors_cannot_credit_the_other_copy` |

The seeded generator runs at least 2,000 additional histories in CI. It tracks
line ownership as it generates events, independently of the blame algorithm.
Its oracle fails on every incorrect match, checks that some correct matches
remain and reports correct and unknown rates. It covers person edits, multiple
sessions, subagents, undos, writes, partial replacements, whole-line replacements,
Claude original states and context, Codex patches, post-commit edits, clock skew,
amends, rebases and cherry-picks. Temporary output is validated before removal.

The native tests retain the documented limit for independently typed identical
text. The generator is bounded evidence over its seed and event vocabulary. It
does not prove historical authorship or remove that information limit.

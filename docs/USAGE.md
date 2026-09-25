# VOD scan usage

`reticle scan` appends one record for each completed scan to
`<store>/notes/usage.jsonl`. View recent records with `reticle usage [SESSION]`.
Use `reticle usage [SESSION] --json` to inspect the full timing buckets.

Each record names the VOD session, source content key, profile, frame source,
reader rates, and active span counts. It counts retrieved frames and each
reader's `feed` calls. Source time measures the shared wait for the next
decoded frame or cached crop. Reader time measures each `feed` and `finish`
call. Setup and publication bracket the pass. The remaining pass time includes
dispatch, progress display, and instrumentation. Source time belongs to the
pass, not to each reader, so add it only once when comparing costs.

The fixed buckets store frequencies of call durations; boundaries are in
nanoseconds under `bucket_upper_ns`. A call exactly on a boundary enters the
next bucket. The record does not retain per-frame timings or pixels. Completed
scans alone enter the log; cache hits, failed scans, standalone commands, and
`trial` do not. Compare records with similar source, rates, spans, and reader
sets. Wall time can also vary with disk cache and machine load.

This is VOD usage, not LLM working-session usage. The latter would need a
separate source of tool-call, token, and model-time observations; Reticle's
scan process cannot infer those from its own timers.

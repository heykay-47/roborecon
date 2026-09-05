# Changelog

## Unreleased

- Fixed hosted reconciliation requests timing out by batching result persistence and keeping optional AI investigations out of the serverless request path.
- Added crossed-reference noise to the fixed benchmark so it reports bounded matcher errors instead of perfect scores, with acceptance floors aligned to at least 98% precision and 90% match/autonomy.
- Fixed AI investigation API response serialization for citation objects and added regression coverage for non-empty, camel-case citations.
- Added dark/light theme support, clearer reconciliation terminology, named accessibility landmarks, and safe quarantine error messaging.
- Updated advisory AI defaults to Google `gemma-4-31b-it` and Groq `qwen/qwen3.8-27b`, and corrected live provider tool contracts and safe API-key verification.

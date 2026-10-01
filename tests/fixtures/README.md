# Test fixtures

- `cassettes/` — VCR cassettes recorded once from the real chess.com public API
  and replayed deterministically by the test suite. One cassette per account
  archive URL, named after the account it was recorded from.
- PGN and archive-shaped JSON fixtures for unit and integration tests live
  beside the cassettes in the unit that records them.

Data policy: the chess.com Published Data API is public and unauthenticated, so
a cassette holds only what that account already publishes. Never record an
account that is not public, and never store credentials — this project
authenticates to nothing.

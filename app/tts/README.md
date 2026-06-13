# TTS Policy

Phase 1.3 uses `LocalStubTTSProvider` by default. It does not call external APIs and writes silent WAV audio for preview rendering.

Allowed voice:

- `neutral_zh`

Blocked voice intent:

- Trump or any political figure voice
- Celebrity voice
- Voice cloning
- Impersonation
- Likeness-targeted speech

Future providers must preserve this policy.


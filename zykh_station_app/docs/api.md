# API

Base URL during development:

```text
http://127.0.0.1:8000
```

## Endpoints

### GET /api/health

Returns service, database, QSM mode and dry-run status.

### GET /api/status

Returns top-level station status for the terminal shell:

- network mode;
- AI mode;
- peripheral device status;
- sync status;
- dry-run flag;
- status chips.

### GET /api/site

Returns the station profile displayed by the terminal.

### POST /api/site

Updates the station profile fields used by the terminal.

### GET /api/dashboard

Returns fixed first-stage homepage data:

- site profile;
- top status chips;
- today medication summary;
- emergency inquiry summary;
- quick actions;
- bottom station stats;
- safety notice.

### GET /api/qsm/status

Returns mock or real peripheral gateway status. First stage defaults to mock mode.

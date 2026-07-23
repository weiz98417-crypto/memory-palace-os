# route-fix — 路由修复

## ADDED Requirements

### Requirement: /admin serves static files without redirect
`GET /admin` SHALL return the admin dashboard HTML with status 200, without redirecting to `/admin/`.

#### Scenario: Admin page direct access
- **WHEN** a GET request is sent to `/admin`
- **THEN** the response status is 200 and the content is the admin HTML page

### Requirement: /api/v1/skills returns skill list without redirect
`GET /api/v1/skills` SHALL return the skills list JSON with status 200, without redirecting.

#### Scenario: Skills list API
- **WHEN** a GET request is sent to `/api/v1/skills`
- **THEN** the response status is 200 and the content is JSON with a `data` array

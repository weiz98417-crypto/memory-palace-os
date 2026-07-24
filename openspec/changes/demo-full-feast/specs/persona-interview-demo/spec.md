## ADDED Requirements

### Requirement: Start interview
`POST /demo/persona/interview/start` SHALL create a new PersonaExtract interview session and return the first question.

#### Scenario: Start interview with job title
- **WHEN** POST with `{job_title: "安全巡检主管"}`
- **THEN** returns `{code: 0, data: {interview_id: string, question: string, question_number: 1}}`

#### Scenario: Start interview with venue
- **WHEN** POST with `{job_title: "安全巡检主管", venue_id: "venue_01"}`
- **THEN** returns interview_id and first question with venue context

### Requirement: Continue interview
`POST /demo/persona/interview/continue` SHALL accept user answer and return next question. Auto-finalizes after question 4.

#### Scenario: Continue with answer
- **WHEN** POST with `{interview_id: "abc", answer: "每天早班先检查消防设备"}`
- **THEN** returns `{code: 0, data: {question: string, question_number: int, is_complete: false, extracted_entries_count?: int}}`

#### Scenario: Final question triggers auto-finalize
- **WHEN** continue is called at question_number=4
- **THEN** returns `{is_complete: true, extracted_entries_count: int}` and interview state is cleared

### Requirement: Finalize interview
`POST /demo/persona/interview/finalize` SHALL save extracted persona to DB and return logic entries.

#### Scenario: Finalize existing interview
- **WHEN** POST with `{interview_id: "abc"}`
- **THEN** returns `{code: 0, data: {logic_entries: [{trigger, behavior, reason}], persona_id?: string}}`

#### Scenario: Finalize nonexistent interview
- **WHEN** POST with invalid interview_id
- **THEN** returns `{code: 1, error: "interview not found"}`

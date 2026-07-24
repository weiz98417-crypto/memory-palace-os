## ADDED Requirements

### Requirement: Auto-play engine
The demo console SHALL provide an auto-play mode that executes a predefined timeline without user interaction.

#### Scenario: Start auto-play
- **WHEN** user clicks "Auto Play" button
- **THEN** system executes timeline steps sequentially: send messages, switch tabs, trigger decompositions, run interviews

#### Scenario: Timeout handling
- **WHEN** a timeline step exceeds 20 seconds without result
- **THEN** system logs warning and advances to next step

#### Scenario: Three consecutive timeouts
- **WHEN** three consecutive steps time out
- **THEN** auto-play stops and shows error banner

### Requirement: Play/Pause/Stop controls
The status bar SHALL show Play, Pause, and Stop controls during auto-play.

#### Scenario: Pause and resume
- **WHEN** user clicks Pause during auto-play
- **THEN** timeline pauses at current step. Clicking Play resumes from paused step.

#### Scenario: Stop auto-play
- **WHEN** user clicks Stop
- **THEN** auto-play terminates and returns console to manual mode

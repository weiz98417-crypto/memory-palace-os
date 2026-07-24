## ADDED Requirements

### Requirement: Print-optimized report
The demo console SHALL include `@media print` CSS that formats the current demo state as a report.

#### Scenario: Print report
- **WHEN** user triggers browser print (Ctrl+P or Export button)
- **THEN** printed output hides tabs, buttons, status bar and shows demo title, timestamp, messages, pipeline traces, stats, watcher log

#### Scenario: Export report contains demo session data
- **WHEN** messages have been sent and results received during the session
- **THEN** printed report includes all message-reply pairs with pipeline routing information

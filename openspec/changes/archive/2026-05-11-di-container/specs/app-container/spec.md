# app-container — 轻量 DI 容器

## ADDED Requirements

### Requirement: Container manages all service singletons
`AppContainer` SHALL provide lazy-loaded access to db_client, vector_store, llm_client, wechat_client, context_tier, and agent_memory via properties.

#### Scenario: First access creates instance
- **WHEN** `container.db_client` is accessed for the first time
- **THEN** the db_client singleton is created and returned

#### Scenario: Repeated access returns same instance
- **WHEN** `container.db_client` is accessed multiple times
- **THEN** the same instance is returned each time

### Requirement: Container supports Mock override
`AppContainer.override()` SHALL allow replacing any service with a Mock for testing.

#### Scenario: Mock injection
- **WHEN** `container.override(llm_client=mock_llm)` is called
- **THEN** subsequent `container.llm_client` returns the mock instance

### Requirement: Container supports reset
`AppContainer.reset()` SHALL clear all overrides, restoring original behavior.

#### Scenario: Reset after test
- **WHEN** `container.reset()` is called after `container.override(...)`
- **THEN** all properties return original instances

### Requirement: Container is available as global singleton
A module-level `container = AppContainer()` SHALL be available for import.

#### Scenario: Global singleton import
- **WHEN** `from src.memory_palace.core.container import container` is executed
- **THEN** a pre-instantiated AppContainer is available

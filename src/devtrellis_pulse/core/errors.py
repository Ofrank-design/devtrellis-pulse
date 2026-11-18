"""Error types. Each carries the process exit code defined in the specification (section 10.3)."""

EXIT_OK = 0
EXIT_GENERAL = 1
EXIT_USAGE = 2
EXIT_CONFIG = 3
EXIT_NOT_REPOSITORY = 4
EXIT_POLICY = 5
EXIT_LOCKED = 6
EXIT_TASKS_FAILED = 7
EXIT_VALIDATION = 8
EXIT_COMMIT = 9
EXIT_DEPENDENCY = 10
EXIT_BUDGET = 11
EXIT_PERSISTENCE = 12
EXIT_INTERRUPTED = 130


class PulseError(Exception):
    exit_code = EXIT_GENERAL
    error_code = "general_error"


class UsageError(PulseError):
    exit_code = EXIT_USAGE
    error_code = "invalid_arguments"


class ConfigError(PulseError):
    exit_code = EXIT_CONFIG
    error_code = "invalid_configuration"


class GitError(PulseError):
    error_code = "git_error"


class NotARepositoryError(GitError):
    exit_code = EXIT_NOT_REPOSITORY
    error_code = "not_a_repository"


class PolicyError(PulseError):
    exit_code = EXIT_POLICY
    error_code = "policy_blocked"


class LockError(PulseError):
    exit_code = EXIT_LOCKED
    error_code = "already_running"


class ValidationFailure(PulseError):
    exit_code = EXIT_VALIDATION
    error_code = "validation_failed"


class CommitError(PulseError):
    exit_code = EXIT_COMMIT
    error_code = "commit_failed"


class DependencyError(PulseError):
    exit_code = EXIT_DEPENDENCY
    error_code = "dependency_unavailable"


class BudgetExceeded(PulseError):
    exit_code = EXIT_BUDGET
    error_code = "budget_exceeded"


class PersistenceError(PulseError):
    exit_code = EXIT_PERSISTENCE
    error_code = "persistence_failed"


class TaskTimeout(PulseError):
    exit_code = EXIT_TASKS_FAILED
    error_code = "task_timed_out"

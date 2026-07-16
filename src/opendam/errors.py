class OpenDamError(Exception):
    """Base class for all opendam errors."""


class GitCommandError(OpenDamError):
    def __init__(self, args, returncode, stderr):
        self.args_ = args
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"git {' '.join(args)} failed ({returncode}): {stderr.strip()}")


class RemoteUnreachableError(OpenDamError):
    pass


class LockHeldError(OpenDamError):
    def __init__(self, project, lock):
        self.project = project
        self.lock = lock
        holder = lock.locked_by["user"] if lock.locked_by else "unknown"
        super().__init__(
            f"'{project}' is already checked out by {holder} "
            f"({lock.locked_by.get('hostname', '?')}) since {lock.locked_at}"
        )


class NotLockHolderError(OpenDamError):
    pass


class StaleLockRaceError(OpenDamError):
    """Raised when the optimistic lock-claim loop exhausts its retries."""


class DirtyWorkingTreeError(OpenDamError):
    pass


class ProjectNotFoundError(OpenDamError):
    pass


class PremiereNotFoundError(OpenDamError):
    pass

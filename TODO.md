# TODO: SSHManager Project

## 1. Documentation
- [ ] Add detailed module, class, and function docstrings throughout codebase.
- [ ] Set up Sphinx or mkdocs for automated HTML documentation.
- [ ] Improve README with usage, setup, and architecture notes.
- [ ] Add practical code examples for common use cases.

## 2. Logging & Error Handling
- [ ] Review all logging statements for clarity, context, and correct levels (INFO/WARNING/ERROR/DEBUG).
- [ ] Improve error messages to include actionable hints.
- [ ] Catch and log edge-case exceptions with enough info for debugging.

## 3. Retry Logic & Robustness
- [ ] Implement retry logic for all SSH/SFTP operations (configurable retry count and backoff).
- [ ] Ensure errors during file transfer or command execution are recoverable where possible.
- [ ] Add context managers where needed to guarantee resource cleanup.

## 4. CLI Tool
- [ ] Design and implement a basic CLI (`sshmanager`) with commands:
    - [ ] `exec` – run a command on one or all hosts
    - [ ] `put` / `get` – upload/download files or directories
    - [ ] `init` – generate a sample hosts YAML/JSON config
    - [ ] `status` – check cluster connectivity
- [ ] Support loading config/hosts from file.
- [ ] Add help (`--help`) and error output for CLI.

## 5. Stretch/Future
- [ ] Live streaming of command output.
- [ ] Pluggable transfer backends (SCP, rsync).
- [ ] Proxy/jump host support.
- [ ] Support for more SSH authentication methods.

---
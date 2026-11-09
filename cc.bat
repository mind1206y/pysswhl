@echo off
chcp 65001
set ANTHROPIC_BASE_URL=http://127.0.0.1:15721
set ANTHROPIC_AUTH_TOKEN=PROXY_MANAGED
set DISABLE_AUTOUPDATER=1
claude --dangerously-skip-permissions %*
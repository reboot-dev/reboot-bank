#!/bin/bash

set -e # Exit if a command exits with an error.
set -x # Echo executed commands to help debug failures.

# MacOS tests can fail due to a race in `protoc` writing files to disk,
# so now we check only occurences of the expected lines in the output.
# See https://github.com/reboot-dev/respect/issues/3433
check_lines_in_file() {
  local expected="$1"
  local actual="$2"

  while IFS= read -r line; do
    if ! grep -Fxq "$line" "$actual"; then
      echo "Line $line is missing in the actual output."
      exit 1
    fi
  done < "$expected"
}

# Convert symlinks to files that we need to mutate into copies.
for file in "requirements.lock" "requirements-dev.lock" "pyproject.toml"; do
  cp "$file" "${file}.tmp"
  rm "$file"
  mv "${file}.tmp" "$file"
done

# Use the published Resemble pip package by default, but allow the test system
# to override them with a different value.
if [ -n "$REBOOT_RESEMBLE_WHL_FILE" ]; then
  # Install the `reboot-resemble` package from the specified path explicitly, over-
  # writing the version from `pyproject.toml`.
  rye remove --no-sync reboot-resemble
  rye remove --no-sync --dev reboot-resemble
  rye add --dev reboot-resemble --absolute --path=$REBOOT_RESEMBLE_WHL_FILE
fi

# Create and activate a virtual environment.
rye sync --no-lock
source .venv/bin/activate

rsm protoc

mypy backend/

if [ -n "$EXPECTED_RSM_DEV_OUTPUT_FILE" ]; then
  actual_output_file=$(mktemp)

  rsm dev run --terminate-after-health-check > "$actual_output_file"

  check_lines_in_file "$EXPECTED_RSM_DEV_OUTPUT_FILE" "$actual_output_file"

  rm "$actual_output_file"
fi

# Deactivate the virtual environment, since we can run a test which may require
# another virtual environment (currently we do that only in `all_tests.sh`).
deactivate

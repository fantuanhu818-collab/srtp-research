version 18
clear all
set more off
capture log close _all
log using "D:/SRTP科研/logs/storage_environment_stata.log", text replace name(storage_check)

display "STATA_TMPDIR=" c(tmpdir)
assert substr(lower(c(tmpdir)), 1, 2) == "d:"

tempfile storage_probe
display "STATA_TEMP_FILE=`storage_probe'"
display "STATA_STORAGE_GATE=PASS"
display "STATA_TASK=PASS"
log close storage_check

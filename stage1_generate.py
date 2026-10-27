"""Generate answers in a new dated result directory; --run resumes an existing one."""
from crest.cli import stage_main

if __name__ == '__main__':
    raise SystemExit(stage_main('generate'))

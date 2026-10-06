"""Compatibility entry. Use ima_client operation JSON; never command-line credentials."""
from ima_client import main
if __name__ == '__main__': raise SystemExit(main())

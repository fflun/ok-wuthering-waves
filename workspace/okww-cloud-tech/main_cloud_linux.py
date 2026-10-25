"""Linux offline verification entry; game task execution is intentionally unavailable."""
import argparse
from pathlib import Path
import runpy


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe', action='store_true', help='Launch a network-disabled blank browser and synthetic OCR/template checks')
    args = parser.parse_args(argv)
    if not args.probe:
        print('LINUX_OFFLINE: no browser or game task started. --probe runs synthetic validation only.')
        return
    runpy.run_path(str(Path(__file__).parent/'linux/runtime_probe.py'), run_name='__main__')


if __name__ == '__main__':
    main()

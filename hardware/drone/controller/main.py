import time

from drone import start_drone


def main() -> int:
    d = start_drone()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0
    finally:
        d.stop()


if __name__ == "__main__":
    raise SystemExit(main())


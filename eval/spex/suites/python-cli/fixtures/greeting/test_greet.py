import subprocess
import sys
import unittest
from pathlib import Path


class GreetingTests(unittest.TestCase):
    def test_greeting(self):
        cli = Path(__file__).with_name("greet.py")
        for flags, expected in (([], "Hello, Ada!\n"), (["--upper"], "HELLO, ADA!\n")):
            with self.subTest(flags=flags):
                result = subprocess.run(
                    [sys.executable, str(cli), "Ada", *flags],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                self.assertEqual(result.stdout, expected)


if __name__ == "__main__":
    unittest.main()

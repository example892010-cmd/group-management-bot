"""Root entry point for Render and local execution.

Run the application as a package so app.main relative imports resolve correctly.
"""

from app.main import run


if __name__ == "__main__":
    run()

"""
Global configuration for Steps 4-5.

This file is intentionally dependency-free and safe to import anywhere.
"""

# Step 4: PCA merge
VARIANCE_THRESHOLD = float(__import__("os").environ.get("MEMORY_VARIANCE_THRESHOLD", "0.6"))
BOLD_STRENGTH = float(__import__("os").environ.get("MEMORY_BOLD_STRENGTH", "0.1"))

# Step 5: Safe subspace projection
MIN_AGREEMENT = float(__import__("os").environ.get("MEMORY_MIN_AGREEMENT", "0.6"))


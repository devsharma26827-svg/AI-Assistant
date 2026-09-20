import sys
import os

def test_imports_sanity():
    """Verify that all core modules can be imported without syntax or runtime errors."""
    try:
        import agent
        import prompts
        import memory_store
        import gemini_key_manager

        assert agent.ASSISTANT_NAME == "Cynthia"
        assert memory_store.MEMORY_FILE == "memory.json"
        assert gemini_key_manager.GeminiKeyManager is not None
    except Exception as e:
        assert False, f"Failed import sanity check: {e}"

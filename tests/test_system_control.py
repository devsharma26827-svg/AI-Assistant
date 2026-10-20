import pytest
import os
import asyncio
from system_control_tools import (
    is_website, get_url, resolve_location, search_item, _count_windows
)

def test_is_website_detection():
    # True website cases
    assert is_website("youtube") is True
    assert is_website("https://google.com") is True
    assert is_website("github.com") is True
    assert is_website("openai.com") is True
    assert is_website("myproject.ai") is True
    assert is_website("www.wikipedia.org") is True
    
    # Document / Code files that MUST NOT be classified as websites
    assert is_website("main.py") is False
    assert is_website("inventory_system.py") is False
    assert is_website("notes.txt") is False
    assert is_website("data.csv") is False
    assert is_website("report.pdf") is False
    assert is_website("document.docx") is False
    assert is_website("script.bat") is False

def test_get_url_mapping():
    assert get_url("youtube") == "https://www.youtube.com"
    assert get_url("gmail") == "https://mail.google.com"
    assert get_url("https://example.com") == "https://example.com"
    assert "google.com/search" in get_url("random search query")

def test_resolve_location():
    desktop = resolve_location("desktop")
    assert os.path.isabs(desktop)
    assert os.path.exists(desktop) or "Desktop" in desktop
    
    docs = resolve_location("documents")
    assert os.path.isabs(docs)
    
    custom = resolve_location("D:\\MyFolder")
    assert custom == "D:\\MyFolder"

def test_search_item_exact_and_substring():
    async def _test():
        index = [
            {"name": "My First Project", "path": "D:/My First Project", "type": "folder"},
            {"name": "Project", "path": "D:/Project", "type": "folder"},
            {"name": "script.py", "path": "D:/script.py", "type": "file"},
            {"name": "notes.txt", "path": "D:/notes.txt", "type": "file"},
        ]
        
        # Exact match
        exact = await search_item("script.py", index, "file")
        assert exact is not None
        assert exact["name"] == "script.py"
        
        # Exact match case-insensitive
        exact_case = await search_item("PROJECT", index, "folder")
        assert exact_case is not None
        assert exact_case["name"] == "Project"
        
        # Unambiguous substring
        sub = await search_item("First Project", index, "folder")
        assert sub is not None
        assert sub["name"] == "My First Project"
        
        # Missing item
        none_item = await search_item("Nonexistent_Folder_12345", index, "folder")
        assert none_item is None
        
    asyncio.run(_test())

def test_count_windows_sanity():
    # Counting windows shouldn't raise exceptions even when win32gui runs
    count = _count_windows("NonExistentWindow99999")
    assert count == 0

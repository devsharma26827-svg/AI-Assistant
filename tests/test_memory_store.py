import os
import json
import pytest
from datetime import datetime, timedelta
from memory_store import MemoryStore, DEFAULT_MEMORY
from intelligence_tools import _remember_fact_impl, _forget_fact_impl, _learn_habit_impl, _forget_habit_impl

@pytest.fixture
def temp_memory_file(tmp_path):
    mem_file = str(tmp_path / "test_memory.json")
    return mem_file

def test_memory_add_read_update_remove(temp_memory_file):
    store = MemoryStore(filepath=temp_memory_file)
    
    # 1. Add fact
    msg = store.add_fact("hobbies", "gaming")
    assert "Remembered new fact" in msg
    facts = store.memory["facts"]["hobbies"]
    assert len(facts) == 1
    assert facts[0]["text"] == "gaming"
    assert facts[0]["confidence"] == 0.5
    
    # 2. Update/reinforce fact
    msg_reinforce = store.add_fact("hobbies", "gaming")
    assert "Reinforced" in msg_reinforce
    assert store.memory["facts"]["hobbies"][0]["count"] == 2
    assert store.memory["facts"]["hobbies"][0]["confidence"] == 0.6
    
    # 3. Read formatted context
    ctx = store.get_formatted_context()
    assert "gaming" in ctx
    
    # 4. Remove fact
    rm_msg = store.remove_fact("hobbies", "gaming")
    assert "Removed fact" in rm_msg
    assert len(store.memory["facts"]["hobbies"]) == 0
    assert "gaming" not in store.get_formatted_context()

def test_memory_reinitialize_persistence(temp_memory_file):
    store1 = MemoryStore(filepath=temp_memory_file)
    store1.add_fact("coding", "likes Python")
    store1.save_memory()
    
    # Reinitialize new store instance pointing to same file
    store2 = MemoryStore(filepath=temp_memory_file)
    assert "coding" in store2.memory["facts"]
    assert store2.memory["facts"]["coding"][0]["text"] == "likes Python"

def test_memory_malformed_json_recovery_preserves_backup(temp_memory_file):
    # Write corrupted/malformed JSON to the file
    with open(temp_memory_file, "w", encoding="utf-8") as f:
        f.write("{ invalid json text ... }")
        
    store = MemoryStore(filepath=temp_memory_file)
    # Confirm it safely fell back to default memory schema
    assert store.memory["user_profile"]["name"] == DEFAULT_MEMORY["user_profile"]["name"]
    assert "facts" in store.memory
    
    # Confirm corrupted backup file was preserved on disk!
    parent_dir = os.path.dirname(temp_memory_file)
    backup_files = [f for f in os.listdir(parent_dir) if ".corrupt." in f and f.endswith(".bak")]
    assert len(backup_files) == 1
    with open(os.path.join(parent_dir, backup_files[0]), "r", encoding="utf-8") as bf:
        assert bf.read() == "{ invalid json text ... }"

def test_memory_projects_and_detail(temp_memory_file):
    store = MemoryStore(filepath=temp_memory_file)
    res = store.create_project("AI Assistant", "Build Cynthia assistant", "2026-12-31")
    assert "Created Project" in res
    assert len(store.memory["projects"]) == 1
    
    task_res = store.add_project_task("AI Assistant", "Implement testing suite")
    assert "Added task" in task_res
    
    # Summary
    summary = store.get_projects_summary()
    assert "AI Assistant" in summary
    assert "Implement testing suite" in summary
    
    # Detail
    detail = store.get_project_detail("AI Assistant")
    assert "AI Assistant" in detail
    assert "Implement testing suite" in detail
    assert "2026-12-31" in detail
    
    # Update task status
    upd = store.update_project_task_status("AI Assistant", "Implement testing suite", "completed")
    assert "Updated" in upd
    assert store.memory["projects"][0]["progress"] == 100

def test_memory_workflows(temp_memory_file):
    store = MemoryStore(filepath=temp_memory_file)
    save_msg = store.save_workflow("Morning Routine", "good morning", ["open weather", "check tasks"], "morning")
    assert "saved successfully" in save_msg
    
    wf = store.get_workflow("morning routine")
    assert wf is not None
    assert len(wf["steps"]) == 2
    
    wf_list = store.list_workflows()
    assert "Morning Routine" in wf_list

def test_memory_habits_learning_decay_forget(temp_memory_file):
    store = MemoryStore(filepath=temp_memory_file)
    store.learn_habit("User says Start", "Open VS Code")
    assert len(store.memory["habits"]) == 1
    assert store.memory["habits"][0]["confidence"] == 0.3
    
    # Reinforce
    store.learn_habit("User says Start", "Open VS Code")
    assert store.memory["habits"][0]["count"] == 2
    assert store.memory["habits"][0]["confidence"] == 0.4
    
    # Simulate time lapse > 14 days for decay
    old_time = (datetime.now() - timedelta(days=15)).isoformat()
    store.memory["habits"][0]["last_used"] = old_time
    store.decay_habits()
    assert store.memory["habits"][0]["confidence"] < 0.4
    
    # Forget habit
    forget_res = store.forget_habit("Start", "Open VS Code")
    assert "Habit forgotten" in forget_res
    assert len(store.memory["habits"]) == 0

def test_remember_fact_blocks_sensitive_secrets(monkeypatch, temp_memory_file):
    # Wire memory module to temp file
    import memory_store
    monkeypatch.setattr(memory_store.memory, "filepath", temp_memory_file)
    monkeypatch.setattr(memory_store.memory, "memory", memory_store.memory.load_memory())
    
    # Attempt to remember an API key
    res = _remember_fact_impl("credentials", "My key is sk-1234567890abcdef1234567890")
    assert "⛔ Cannot store sensitive secret" in res
    assert "OpenAI API Key" in res
    assert "credentials" not in memory_store.memory.memory["facts"]
    
    # Attempt to remember a Google key
    res_google = _remember_fact_impl("credentials", "Key is AIzaSyD1234567890abcdef1234567890abc")
    assert "⛔ Cannot store sensitive secret" in res_google
    assert "Google / Gemini API Key" in res_google

    # Valid non-secret fact should succeed
    res_ok = _remember_fact_impl("preferences", "Likes green tea")
    assert "Remembered new fact" in res_ok
    assert "preferences" in memory_store.memory.memory["facts"]

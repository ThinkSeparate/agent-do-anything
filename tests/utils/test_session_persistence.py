"""Tests for SessionPersistence class."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from utils.session_persistence import SessionPersistence


def test_session_persistence():
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        sp = SessionPersistence(tmpdir)

        # Create session
        sid = sp.create_session("测试任务")
        assert sid > 0

        # Save state
        sp.save_state(sid, {"messages": [], "consecutive_failures": 0})

        # Load state
        state = sp.load_state(sid)
        assert state["consecutive_failures"] == 0

        # Get session
        session = sp.get_session(sid)
        assert session["status"] == "running"

        # Mark completed
        sp.mark_completed(sid)
        session = sp.get_session(sid)
        assert session["status"] == "completed"

        print("All tests passed!")


if __name__ == "__main__":
    test_session_persistence()

"""
test_voice_commands.py — Automated Integration Test Suite for J.A.R.V.I.S.
Targets: Chat, Weather, News, and Contextual Memory.
Excludes: Browser control, File operations, and System control.
"""

import sys
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Configure sys.path to resolve project root imports
sys.path.append(str(Path(__file__).parent.absolute()))

import main
import core.speaker
import core.brain
import memory.db
import memory.context_manager

# Reconfigure stdout to use UTF-8
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


class JarvisVoiceCommandsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 1. Initialize SQLite Database
        main.initialize_db()
        # 2. Initialize Brain
        main.brain = core.brain.Brain()
        # 3. Mute real speaker output
        core.speaker.set_muted(True)

    def setUp(self):
        # Capture speak calls
        self.speak_calls = []
        self.speak_async_calls = []

        self.speak_patcher = patch('main.speak', side_effect=self._mock_speak)
        self.speak_async_patcher = patch('main.speak_async_fire', side_effect=self._mock_speak_async)
        self.speak_patcher.start()
        self.speak_async_patcher.start()

        # Mock requests.get for Weather & News to avoid actual API calls
        self.get_patcher = patch('requests.get')
        self.mock_get = self.get_patcher.start()

    def tearDown(self):
        self.speak_patcher.stop()
        self.speak_async_patcher.stop()
        self.get_patcher.stop()

    def _mock_speak(self, text, priority=1):
        self.speak_calls.append(text)

    def _mock_speak_async(self, text, priority=2):
        self.speak_async_calls.append(text)

    def test_voice_commands(self):
        # List of test queries: (query, expected_intent_family)
        test_queries = [
            # 1. Chat & Greetings (fast-path routing)
            ("hello jarvis", ["CHAT"]),
            ("who are you?", ["CHAT"]),
            ("what is the date today?", ["CHAT"]),
            ("tell me the current time", ["CHAT"]),
            
            # 2. Weather
            ("what is the weather in Sonipat?", ["WEATHER"]),
            ("check the forecast for Delhi tomorrow", ["WEATHER"]),
            
            # 3. News
            ("tell me the latest headlines", ["NEWS"]),
            ("what is the latest tech news?", ["NEWS"]),
            
            # 4. Contextual Memory / Recall
            ("what did we talk about earlier?", ["MEMORY_RECALL"]),
            ("do you remember what I asked?", ["MEMORY_RECALL"]),
        ]

        passed_count = 0
        total = len(test_queries)

        print(f"\nRunning J.A.R.V.I.S. Subset Voice Command Tests...\n")
        print(f"{'QUERY':<45} | {'ROUTE INTENT':<15} | {'STATUS':<6}")
        print("-" * 72)

        for query, expected_intents in test_queries:
            self.speak_calls.clear()
            self.speak_async_calls.clear()

            # Mock successful responses for APIs
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "weather": [{"description": "clear sky", "icon": "01d"}],
                "main": {"temp": 298.15, "feels_like": 298.15, "humidity": 50},
                "wind": {"speed": 5.0},
                "sys": {"country": "IN"},
                "name": "Sonipat",
                "list": [
                    {
                        "dt_txt": "2026-06-11 21:00:00",
                        "main": {"temp": 298.15},
                        "weather": [{"description": "clear sky"}]
                    }
                ],
                "articles": [
                    {"title": "Test Headline", "source": {"name": "Test Source"}}
                ]
            }
            self.mock_get.return_value = mock_response

            # Classify intent using the router
            intent = main.route(query, main.brain)
            
            # Run the input handler
            with patch('core.brain.Brain.ask', return_value="Mocked response"):
                main.handle_input(query)

            # Check if intent is correct
            is_valid_intent = any(expected in intent for expected in expected_intents)
            status = "PASS" if is_valid_intent else "FAIL"
            if is_valid_intent:
                passed_count += 1

            print(f"{query[:45]:<45} | {intent:<15} | {status:<6}")

        pass_rate = (passed_count / total) * 100
        print(f"\nCompleted: {passed_count}/{total} passed ({pass_rate:.1f}%)\n")
        self.assertGreaterEqual(pass_rate, 90.0, "Pass rate is below 90%!")

    def test_contextual_memory_handling(self):
        """Test that the context manager correctly splits earlier sessions and current session history."""
        # 1. Clean the database table to prevent interference
        conn = memory.db._get_connection()
        try:
            conn.execute("DELETE FROM conversations")
            conn.commit()
        finally:
            conn.close()

        # 2. Insert test conversations
        conn = memory.db._get_connection()
        try:
            # Earlier session conversation
            conn.execute(
                "INSERT INTO conversations (date, timestamp, user_input, jarvis_response) VALUES (?, ?, ?, ?)",
                ("2026-06-11", "2026-06-11T11:00:00", "what is 5+5?", "It is 10, Sir.")
            )
            # Current session conversation
            conn.execute(
                "INSERT INTO conversations (date, timestamp, user_input, jarvis_response) VALUES (?, ?, ?, ?)",
                ("2026-06-11", "2026-06-11T13:00:00", "my name is Harsh", "Understood, Harsh.")
            )
            conn.commit()
        finally:
            conn.close()

        # 3. Call build_context_block with mocked SESSION_START
        with patch('memory.context_manager.SESSION_START', '2026-06-11T12:00:00'), \
             patch('memory.context_manager.get_recent_summaries', return_value=[]):
            context_block = memory.context_manager.build_context_block()

        # 4. Verify context block layout
        print("\nGenerated Context Block for Verification:")
        print(context_block)
        
        self.assertIn("(Earlier Sessions Today)", context_block)
        self.assertIn("what is 5+5?", context_block)
        self.assertIn("(Current Session)", context_block)
        self.assertIn("my name is Harsh", context_block)


if __name__ == "__main__":
    unittest.main()
